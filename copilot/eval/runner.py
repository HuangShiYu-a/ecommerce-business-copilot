"""评测 runner（D1c 离线 Phase A / D2 live / D3 M8）。

离线：fake LLM 按 case 预设"正确行为" → 全数据集应 100%（验证 harness/谓词/标签无 bug）；
M4 为确定性（直接 search_knowledge）。live：DeepSeek repeat=3（阶段 4 后半）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import yaml
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from ..agent.react import build_react_graph, run_agent_react
from ..tests.fake_llm import ScriptedFakeModel, tool_call
from .judgments import extract_trace, judge_m1_plan, judge_m3_trace, judge_m4_retrieval
from .predicates import FACTS, predicate_for

ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_CASES = ROOT / "data" / "eval-cases"
SC_PATH = ROOT / "data" / "scenarios" / "eval" / "scenarios.yaml"

_SKU_RE = re.compile(r"SKU_\d+_[A-Z0-9_]+")
_ORDER_RE = re.compile(r"ORD_\d+_\d+")
_SKU_TOOLS = {"get_inventory", "analyze_stockout_risk", "analyze_sales_anomaly",
              "calculate_product_health", "query_product_performance", "op05_restock_workflow"}
_ORDER_TOOLS = {"get_order", "get_shipping_status", "analyze_fulfillment_delay",
                "check_return_eligibility", "cs08_return_workflow"}


def _load(name: str):
    with open(EVAL_CASES / name, encoding="utf-8") as f:
        return yaml.safe_load(f)["cases"]


def _sc_data():
    sc = yaml.safe_load(SC_PATH.read_text(encoding="utf-8"))
    return [s for s in sc["scenarios"] if s["nature"] == "data"]


# ---- 问题模板 / 工具映射（M2）----

QUESTION = {
    "ON_TIME_DELIVERY": "{order} 有没有延误", "PAST_PROMISED": "{order} 有没有延误",
    "MISSING_PROMISED_AT": "{order} 有没有延误",
    "WITHIN_WINDOW": "{order} 可以退货吗", "WINDOW_EXPIRED": "{order} 还能退吗",
    "MISSING_SIGNED_AT": "{order} 可以退货吗", "PREEXISTING_AFTERSALES": "{order} 申请退货",
    "SLOW_MOVING": "{sku} 是不是慢销商品", "NO_SLOW_IN_SCOPE": "beauty 类目有哪些慢销商品",
    "SLOW_WITH_HEALTH": "{sku} 是不是慢销商品",
    "LOW_STOCK_HIGH_SALES": "{sku} 缺货风险怎么样", "HEALTHY_DOI": "{sku} 会不会断货",
    "MISSING_SALES_WINDOW": "{sku} 缺货风险怎么样",
    "RESTOCK_NEEDED": "{sku} 需要补货吗", "STOCK_SUFFICIENT": "{sku} 需要补货吗",
    "MISSING_LEAD_TIME_CONFIG": "{sku} 需要补货吗", "SKIP_PRESCREEN": "{sku} 需要补货吗",
    "FULL_CORE": "{sku} 健康度怎么样", "MISSING_OPTIONAL": "{sku} 健康度怎么样",
    "MISSING_CORE": "{sku} 健康度怎么样",
    "DROP_OVER_THRESHOLD": "{sku} 销售有没有异常", "BELOW_THRESHOLD": "{sku} 销售有没有异常",
    "MISSING_ANOMALY_CONFIG": "{sku} 销售有没有异常", "DROP_WITH_PRICE_EVIDENCE": "{sku} 销售有没有异常",
    "CROSS_STORE": "查一下 {order} 的订单详情",
}
WF_TOOL = {
    "CS-06": "analyze_fulfillment_delay", "CS-08": "check_return_eligibility",
    "OP-03": "query_product_performance", "OP-04": "analyze_stockout_risk",
    "OP-05": "op05_restock_workflow", "OP-07": "calculate_product_health",
    "OP-08": "analyze_sales_anomaly", "ISO": "get_order",
}
MODE_OF = {"CS-06": "CUSTOMER_SERVICE", "CS-08": "CUSTOMER_SERVICE", "OP-03": "OPERATIONS",
           "OP-04": "OPERATIONS", "OP-05": "OPERATIONS", "OP-07": "OPERATIONS",
           "OP-08": "OPERATIONS", "ISO": "CUSTOMER_SERVICE"}


def question_for(sc: dict) -> str:
    tpl = QUESTION[sc.get("trigger_type")]
    order = sc.get("order_no") or ""
    sku = (sc.get("sku_ids") or [""])[0]
    return tpl.format(order=order, sku=sku)


def tool_args_for(sc: dict) -> dict:
    wf = sc.get("workflow")
    if wf == "ISO":
        return {"order_no": sc.get("order_no")}
    if wf == "OP-03" and sc.get("trigger_type") == "NO_SLOW_IN_SCOPE":
        return {"category": "beauty"}
    if sc.get("order_no"):
        return {"order_no": sc.get("order_no")}
    sku = (sc.get("sku_ids") or [""])[0]
    return {"sku_code": sku}


def _script(calls, final="处理完成。"):
    return [AIMessage(content="", tool_calls=calls), AIMessage(content=final)]


def _build(mode: str, script: list):
    return build_react_graph(model=ScriptedFakeModel(script=script), mode=mode,
                             checkpointer=InMemorySaver())


def _run_offline_case(mode: str, script, question: str, thread: str) -> tuple[dict, object]:
    """返回 (out, graph)；graph 复用（resume 需同一 checkpointer）。"""
    g = _build(mode, script)
    sess = {"session_id": thread, "user_id": 1, "workspace_mode": mode, "store_id": 1}
    return run_agent_react(g, thread, sess, question), g


def _resume_if_needed(out: dict, graph, mode: str, thread: str) -> dict:
    """V1.2.3 resume 保护：有 __interrupt__ 才 resume（CS-08 already_exists 不 resume）。"""
    if not (out.get("response", {}).get("approval_required")
            and out.get("state", {}).get("__interrupt__")):
        return out
    sess = {"session_id": thread, "user_id": 1, "workspace_mode": mode, "store_id": 1}
    return run_agent_react(graph, thread, sess, "", resume={"decision": "approved"})


# ---- M1 离线 ----

def _m1_fake(ap: dict, question: str):
    """按 acceptable_plan 预设正确调用；args 保证工具可执行（从问题补实体/query）。"""
    def _valid_args(t, base):
        a = dict(base)
        m = _SKU_RE.search(question)
        if m and t in _SKU_TOOLS and "sku_code" not in a:
            a["sku_code"] = m.group(0)
        m2 = _ORDER_RE.search(question)
        if m2 and t in _ORDER_TOOLS and "order_no" not in a:
            a["order_no"] = m2.group(0)
        if t == "search_business_knowledge" and "query" not in a:
            a["query"] = question
        return a

    pt = ap.get("type")
    if pt in ("single_tool", "multi_tool", "knowledge_qa", "workflow_request", "boundary"):
        req = ap.get("required_tools") or []
        pick = req if pt == "multi_tool" else req[:1]
        base = ap.get("required_args") or {}
        calls = [tool_call(t, _valid_args(t, dict(base)), f"m1-{i}") for i, t in enumerate(pick)]
        return _script(calls)
    if pt == "capability":
        return _script([tool_call("request_capability", {"domain": ap.get("domain")}, "m1-cap")])
    if pt == "clarify":
        return [AIMessage(content="请提供订单号。")]
    if pt == "no_tool":
        return [AIMessage(content="好的。")]
    return [AIMessage(content="。")]


def run_offline_m1() -> dict:
    cases = _load("tool_sel.yaml")
    n_ok = n_total = 0
    detail = []
    for i, c in enumerate(cases):
        mode = c.get("mode", "UNSET")
        out, _ = _run_offline_case(mode, _m1_fake(c["acceptable_plan"], c["question"]),
                                   c["question"], f"d1c-m1-{i}")
        resp = out["response"]
        r = judge_m1_plan(extract_trace(out["state"]["messages"]), c["acceptable_plan"],
                          resp.get("status", ""), resp.get("message", ""))
        n_total += 1
        n_ok += int(r["exact"])
        if not r["exact"]:
            detail.append({"id": c["id"], "plan_type": c["plan_type"], "judge": r,
                           "resp_status": resp.get("status")})
    return {"n_ok": n_ok, "n_total": n_total, "failures": detail}


# ---- M3 离线 ----

def _m3_fake(gold: dict):
    first = gold.get("first_tool")
    sku = gold.get("_sku")
    if gold["pattern"] == "conditional_multihop":
        deep = gold["required_deep_tools"][0]
        return _script([tool_call(first, {"sku_code": sku}, "m3-0"),
                        tool_call(deep, {"sku_code": sku}, "m3-1")], "风险 HIGH，已深入分析。")
    if gold["pattern"] == "early_stop":
        return _script([tool_call(first, {"sku_code": sku}, "m3-0")], "库存充足，无需深挖。")
    if gold["pattern"] == "single_hop":
        return _script([tool_call(first, {"sku_code": sku}, "m3-0")], "库存 35 件。")
    if gold["pattern"] == "multi_tool_parallel":
        req = gold.get("required_tools") or []
        calls = [tool_call(t, {"order_no": "ORD_01_000438"} if "shipping" in t or "eligibility" in t
                          else {"sku_code": sku}, f"m3-{i}") for i, t in enumerate(req)]
        return _script(calls, "查询完成。")
    return [AIMessage(content="。")]


def run_offline_m3() -> dict:
    cases = _load("multihop_gold.yaml")
    n_ok = n_total = 0
    detail = []
    for i, c in enumerate(cases):
        mode = c.get("mode", "OPERATIONS")
        c["_sku"] = (_SKU_RE.search(c["question"]) or [None])[0]
        out, _ = _run_offline_case(mode, _m3_fake(c), c["question"], f"d1c-m3-{i}")
        ok = judge_m3_trace(extract_trace(out["state"]["messages"]), out["response"], c)
        n_total += 1
        n_ok += int(ok)
        if not ok:
            detail.append({"id": c["id"], "pattern": c["pattern"]})
    return {"n_ok": n_ok, "n_total": n_total, "failures": detail}


# ---- M2 离线（26 SC，fake 预设正确工具）----

def run_offline_m2() -> dict:
    scs = _sc_data()
    n_ok = n_total = 0
    detail = []
    for i, sc in enumerate(scs):
        wf = sc["workflow"]
        tool = "cs08_return_workflow" if sc["scenario_id"] == "SC-CS08-006" else WF_TOOL[wf]
        args = tool_args_for(sc)
        mode = MODE_OF[wf]
        labels = "、".join(FACTS.get(sc["scenario_id"], {}).keys())
        final = f"处理完成，结论：{labels}。" if labels else "处理完成。"
        out, g = _run_offline_case(mode, _script([tool_call(tool, args, f"m2-{i}")], final),
                                   question_for(sc), f"d1c-m2-{i}")
        resp = _resume_if_needed(out, g, mode, f"d1c-m2-{i}")["response"]
        pred = predicate_for(sc)
        ok, detail_ = pred(resp)
        n_total += 1
        n_ok += int(ok)
        if not ok:
            detail.append({"id": sc["scenario_id"], "wf": wf, "predicate": detail_,
                           "resp_status": resp.get("status")})
    return {"n_ok": n_ok, "n_total": n_total, "failures": detail}


# ---- M4 确定性出数 ----

def run_offline_m4() -> dict:
    from ..db import connect
    from ..rag import resolve_rules, search_knowledge
    gold = _load("rag_gold.yaml")
    conn = connect()
    n_ans = n_hit = n_un = n_abstain = n_conf = n_conf_ok = 0
    mrrs = []
    try:
        for c in gold:
            if c.get("expect") == "RULE_CONFLICT":
                r = resolve_rules(conn, c["query"], c["store_id"], scope=c.get("scope"))
                n_conf += 1
                n_conf_ok += int(r["status"] == "RULE_CONFLICT")
            elif c.get("answerable") is False:
                rows = search_knowledge(conn, c["query"], c["store_id"], top_k=5)
                n_un += 1
                n_abstain += int(len(rows) == 0)
            else:
                rows = search_knowledge(conn, c["query"], c["store_id"], top_k=10)
                r = judge_m4_retrieval(rows, c)
                n_ans += 1
                n_hit += int(r["hit5"])
                mrrs.append(r["mrr"])
    finally:
        conn.close()
    return {"hit5": f"{n_hit}/{n_ans}", "mrr": (sum(mrrs) / len(mrrs) if mrrs else 0.0),
            "abstention": f"{n_abstain}/{n_un}", "conflict": f"{n_conf_ok}/{n_conf}"}


def run_offline() -> dict:
    """离线 Phase A：M1/M3/M2 期望 100%，M4 确定性出数。"""
    return {
        "m1": run_offline_m1(), "m3": run_offline_m3(),
        "m2": run_offline_m2(), "m4": run_offline_m4(),
    }

"""OP-05 补货建议 Agent 工作流（S4.4 LangGraph 竖切）。

对齐 Workflow Spec V1.0：
- Node = 业务步骤（意图 / 执行 / 草稿 / 确认 / 收尾）
- Conditional Edge 只看结构化 state（route_status），不看 LLM 自由文本
- HITL：HAS_RECO 才经 LangGraph interrupt() + checkpointer 等人工确认

职责边界：LLM 只做「意图抽取 / 结果解释」；route_status 与补货量由确定性
T-R-01 裁定（LLM 不参与）。LLM_MODE=dryrun 时离线可测（SC 校验不依赖密钥）。
"""
from __future__ import annotations

import re
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .. import llm
from ..context import ops_ctx
from ..tool import run_tool

SKU_RE = re.compile(r"SKU_\d+_[A-Z0-9_]+")

SYSTEM_INTENT = (
    "你是电商运营 Copilot 的意图解析器。用户消息可能包含 SKU 编码"
    "（形如 SKU_01_STOCKOUT_01）。请只回复你识别到的 SKU 编码；"
    "未识别到时回复：UNKNOWN"
)
SYSTEM_EXPLAIN = (
    "你是电商运营 Copilot 的回复助手。你只负责用中文、简洁、面向运营人员地"
    "解释「确定性工具」给出的计算结果。严禁自行重新计算、修改或补充与工具结果"
    "冲突的数值；工具结果由 JSON 提供。"
)


class Op05State(TypedDict, total=False):
    request_id: str
    store_id: int
    message: str
    sku_code: str | None
    route_status: str          # HAS_RECO/NO_RECO/UNDETERMINED/NEED_CLARIFICATION/ERROR(...)
    tool_result: dict
    explanation: str
    confirm_decision: str | None
    final_message: str


def extract_sku(text: str) -> str | None:
    m = SKU_RE.search(text or "")
    return m.group(0) if m else None


def _llm_extract_sku(message: str) -> str | None:
    resp = llm.get_llm().invoke(
        [("system", SYSTEM_INTENT), ("user", message)])
    return extract_sku(str(resp.content)) or None


def _explain_template(state: Op05State) -> str:
    route = state.get("route_status", "")
    sku = state.get("sku_code")
    tr = state.get("tool_result", {})
    if route == "HAS_RECO":
        return (f"SKU {sku} 建议补货 {tr.get('recommended_quantity')} 件"
                f"（近 {tr.get('avg_daily_sales_est')} 件/天，约 {tr.get('days_until_stockout')} 天后缺货）。")
    if route == "NO_RECO":
        return f"SKU {sku} 库存充足，当前无需补货。"
    if route == "UNDETERMINED":
        return f"SKU {sku} 暂无法给出补货建议：{tr.get('error_detail')}。"
    if route == "NEED_CLARIFICATION":
        return "请提供要查询的 SKU 编码（形如 SKU_01_STOCKOUT_01）。"
    return f"SKU {sku} 查询失败：{tr.get('error_detail', route)}。"


def _explain(state: Op05State) -> str:
    if llm.mode() == "dryrun":
        return _explain_template(state)
    if state.get("route_status") == "NEED_CLARIFICATION":
        return _explain_template(state)
    resp = llm.get_llm(temperature=0.3).invoke(
        [("system", SYSTEM_EXPLAIN),
         ("user", f"工具结果：{state.get('tool_result')}\n"
                 f"路由状态：{state.get('route_status')}\n请向运营人员解释。")])
    return str(resp.content).strip()


# ---- 节点 ----

def intent_node(state: Op05State) -> dict:
    sku = extract_sku(state.get("message", ""))
    if sku is None and llm.mode() == "live":
        sku = _llm_extract_sku(state.get("message", ""))
    return {"sku_code": sku}


def run_tool_node(state: Op05State) -> dict:
    sku = state.get("sku_code")
    if not sku:
        return {"route_status": "NEED_CLARIFICATION", "tool_result": {}}
    res = run_tool("T-R-01", ops_ctx(state["store_id"]), sku_code=sku)
    if res.ok:
        route = "HAS_RECO" if res.data.get("recommended_quantity", 0) > 0 else "NO_RECO"
        detail = res.data
    elif res.error_code == "DATA_UNAVAILABLE":
        route, detail = "UNDETERMINED", {"error_detail": res.error_detail}
    else:
        route = f"ERROR({res.error_code})"
        detail = {"error_code": res.error_code, "error_detail": res.error_detail}
    return {"route_status": route, "tool_result": detail}


def draft_node(state: Op05State) -> dict:
    return {"explanation": _explain(state)}


def confirm_node(state: Op05State) -> dict:
    decision = interrupt({
        "prompt": "是否确认生成补货建议单？",
        "sku_code": state.get("sku_code"),
        "tool_result": state.get("tool_result"),
    })
    return {"confirm_decision": decision}


def finalize_node(state: Op05State) -> dict:
    route = state.get("route_status")
    if route == "HAS_RECO":
        accepted = state.get("confirm_decision") == "accepted"
        return {
            "route_status": "COMPLETED" if accepted else "TERMINATED",
            "final_message": ("已确认，补货建议生效：\n" + state.get("explanation", ""))
            if accepted else "已取消补货建议。",
        }
    return {"final_message": state.get("explanation", "")}


# ---- 图 ----

def build_graph(checkpointer=None):
    g = StateGraph(Op05State)
    g.add_node("intent", intent_node)
    g.add_node("run_tool", run_tool_node)
    g.add_node("draft", draft_node)
    g.add_node("confirm", confirm_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "intent")
    g.add_edge("intent", "run_tool")
    g.add_edge("run_tool", "draft")
    g.add_conditional_edges(
        "draft",
        lambda s: "confirm" if s.get("route_status") == "HAS_RECO" else "finalize",
    )
    g.add_edge("confirm", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())

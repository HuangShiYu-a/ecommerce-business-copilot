"""G2 六类 live 评估（DeepSeek + 真实工具 + PG）。

用法：python scripts/eval_g2.py
逐类打印 PASS/FAIL；硬门禁 C（条件多跳）与 F（能力扩展）失败 → exit 非 0。
类别：A 单跳 / B 并行多工具 / C 条件多跳 / D 错误恢复 / E 上下文追问（working state）
      / F 能力扩展（F1 request_capability + F2 pending + F3 重跑无重复用户消息）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from copilot.agent.react import build_react_graph, run_agent_react

HARD_GATES = {"C", "F"}
results: dict[str, bool] = {}


def collect_calls(msgs, start=0):
    """从 messages[start:] 收集 (tool_name, args)。"""
    calls = []
    for m in msgs[start:]:
        for tc in getattr(m, "tool_calls", None) or []:
            calls.append((tc.get("name"), dict(tc.get("args") or {})))
    return calls


def main() -> int:
    saver = InMemorySaver()
    sess_ops = {"session_id": "g2", "user_id": 1, "workspace_mode": "OPERATIONS", "store_id": 1}
    sess_unset = {"session_id": "g2", "user_id": 1, "workspace_mode": "UNSET", "store_id": 1}
    g_ops = build_react_graph(model=None, mode="OPERATIONS", checkpointer=saver)

    # ---- A 单跳 ----
    out = run_agent_react(g_ops, "A1", sess_ops, "SKU_01_STOCKOUT_01 库存多少")
    calls = collect_calls(out["state"]["messages"])
    results["A"] = bool(calls) and calls[-1][0] == "get_inventory"

    # ---- B 并行多工具 ----
    out = run_agent_react(g_ops, "B1", sess_ops, "ORD_01_000438 能退货吗，另外物流到哪了")
    names = {c[0] for c in collect_calls(out["state"]["messages"])}
    results["B"] = {"check_return_eligibility", "get_shipping_status"} <= names

    # ---- C 条件多跳（硬门禁）----
    out = run_agent_react(g_ops, "C1", sess_ops,
                          "SKU_01_STOCKOUT_01 有没有缺货风险？如果有，帮我进一步分析原因")
    calls = collect_calls(out["state"]["messages"])
    c_names = {c[0] for c in calls}
    deep = {"get_inventory", "analyze_sales_anomaly", "calculate_product_health",
            "query_product_performance"}
    results["C"] = len(calls) >= 2 and "analyze_stockout_risk" in c_names and bool(c_names & deep)

    # ---- D 错误恢复 ----
    out = run_agent_react(g_ops, "D1", sess_ops, "查一下订单 ORD_99_NOPE 的物流状态")
    ans = out["response"]["message"]
    # D 判定：NOT_FOUND 后如实转述（回答含"不存在/查不到"类措辞），不编造订单数据
    results["D"] = any(w in ans for w in ("不存在", "查不到", "没有", "未找到", "找不到"))

    # ---- E 上下文追问（working state 复用 + 覆盖）----
    t1 = run_agent_react(g_ops, "E1", sess_ops, "ORD_01_000002 物流到哪了")
    n1 = len(t1["state"]["messages"])
    t2 = run_agent_react(g_ops, "E1", sess_ops, "那能退吗")
    calls2 = collect_calls(t2["state"]["messages"], start=n1)
    e_reuse = any(name == "check_return_eligibility"
                  and args.get("order_no") == "ORD_01_000002" for name, args in calls2)
    # 覆盖：中途换 ORD_01_000438
    n2 = len(t2["state"]["messages"])
    t3 = run_agent_react(g_ops, "E1", sess_ops, "ORD_01_000438 呢")
    calls3 = collect_calls(t3["state"]["messages"], start=n2)
    e_override = any(name == "check_return_eligibility"
                     and args.get("order_no") == "ORD_01_000438" for name, args in calls3)
    results["E"] = e_reuse or e_override   # 至少验证 working state 复用/覆盖之一
    e_detail = f"reuse_ORD2={e_reuse} override_ORD438={e_override} calls2={calls2[:2]}"

    # ---- F 能力扩展（硬门禁：F1/F2/F3）----
    g_unset = build_react_graph(model=None, mode="UNSET", checkpointer=saver)
    f_msg = "SKU_01_STOCKOUT_01 缺货风险怎么样"
    f1 = run_agent_react(g_unset, "F1", sess_unset, f_msg)
    f_calls = collect_calls(f1["state"]["messages"])
    F1 = any(name == "request_capability" for name, _ in f_calls)
    F1 &= not any(name == "analyze_stockout_risk" for name, _ in f_calls)  # 未越权
    pending = f1["response"]["result"].get("capability_pending") or {}
    F2 = pending.get("domain") == "operations" and pending.get("original_message") == f_msg
    # 切换 + 重跑（共享 saver → 同 thread 状态保留）
    g_ops2 = build_react_graph(model=None, mode="OPERATIONS", checkpointer=saver)
    sess_ops_after = dict(sess_ops)
    f2 = run_agent_react(g_ops2, "F1", sess_ops_after, "", capability_replay=True)
    f2_calls = collect_calls(f2["state"]["messages"])
    F3a = any(name == "analyze_stockout_risk" for name, _ in f2_calls)
    user_count = sum(1 for m in f2["state"]["messages"] if isinstance(m, HumanMessage))
    F3b = user_count == 1
    results["F"] = F1 and F2 and F3a and F3b
    f_detail = f"F1={F1} F2={F2} F3a={F3a} F3b={F3b} user_count={user_count}"

    # ---- 输出 ----
    for k in ["A", "B", "C", "D", "E", "F"]:
        mark = "PASS" if results[k] else "FAIL"
        extra = {"E": e_detail, "F": f_detail}.get(k, "")
        print(f"[{mark}] {k}  {extra}")
        if k == "D":
            print(f"        answer: {out['response']['message'][:120]!r}")
        if k == "E":
            print(f"        msg2: {t2['response']['message'][:100]!r}")

    ok = all(results.values())
    failed_hard = [k for k in HARD_GATES if not results[k]]
    print(f"\n结果: {sum(results.values())}/6；硬门禁失败: {failed_hard or '无'}")
    return 1 if (not ok or failed_hard) else 0


if __name__ == "__main__":
    sys.exit(main())

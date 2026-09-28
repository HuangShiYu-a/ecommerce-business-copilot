"""G3 live 全链路评估（DeepSeek + 真实工具 + PG）。

用法：python scripts/eval_g3.py
4 条 live 链：退货建单（含幂等）/ ineligible 不 interrupt / 补货确认 / 拒绝路径。
任一失败 exit 非 0。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from langgraph.checkpoint.memory import InMemorySaver

from copilot.agent.react import build_react_graph, run_agent_react
from copilot.db import connect, query_one

results: dict[str, bool] = {}


def audit_count(resource_id):
    with connect() as conn:
        row = query_one(conn, "SELECT COUNT(*) AS n FROM audit_logs "
                              "WHERE action='CREATE_RETURN_REQUEST' AND resource_id=%s",
                        (resource_id,))
        return row["n"]


def main() -> int:
    # GBK 终端打印修复（阶段 7 补，阶段 2 发现的缺陷）：live LLM 答案含非 GBK 字符（如 ❌）
    # 时 print 曾抛 UnicodeEncodeError 且崩溃跳过结尾 CS08-* 清理 → 强制 UTF-8 + 替换不可编码字符
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sess_cs = {"session_id": "g3", "user_id": 1, "workspace_mode": "CUSTOMER_SERVICE", "store_id": 1}
    sess_ops = {"session_id": "g3", "user_id": 1, "workspace_mode": "OPERATIONS", "store_id": 1}

    # ---- 1) 拒绝路径（cancelled；前置：438 尚无退货单，可触发 interrupt）----
    g_cs4 = build_react_graph(model=None, mode="CUSTOMER_SERVICE", checkpointer=InMemorySaver())
    run_agent_react(g_cs4, "R5", sess_cs, "ORD_01_000438 申请退货")
    out7 = run_agent_react(g_cs4, "R5", sess_cs, "", resume={"decision": "rejected"})
    r7 = out7["response"]
    cancelled = (r7.get("result") or {}).get("decision") == "cancelled"
    results["拒绝路径"] = r7["status"] == "completed" and cancelled
    print(f"[{'PASS' if results['拒绝路径'] else 'FAIL'}] 拒绝路径 cancelled={cancelled}")

    # ---- 2) 退货建单（eligible → 挂起 → 确认 → 建单 + 审计 + 重放不重复）----
    g_cs = build_react_graph(model=None, mode="CUSTOMER_SERVICE", checkpointer=InMemorySaver())
    out1 = run_agent_react(g_cs, "R1", sess_cs, "ORD_01_000438 申请退货")
    r1 = out1["response"]
    if r1["status"] != "approval_required":
        print("[FAIL] 退货-eligible 未进入审批挂起:", r1["status"], r1["message"][:100])
        results["退货建单"] = False
    else:
        out2 = run_agent_react(g_cs, "R1", sess_cs, "", resume={"decision": "approved"})
        r2 = out2["response"]
        res = r2.get("result") or {}
        rid = res.get("return_request_id")
        ok1 = r2["status"] == "completed" and rid is not None
        ok2 = audit_count(rid) >= 1 if rid else False
        # H1 重放：新 thread 同订单 → 已有退货单，不再触发审批/建单（返回 already_exists）
        g_cs2 = build_react_graph(model=None, mode="CUSTOMER_SERVICE", checkpointer=InMemorySaver())
        out3 = run_agent_react(g_cs2, "R2", sess_cs, "ORD_01_000438 申请退货")
        r3 = out3["response"]
        ok3 = (r3["status"] == "completed"
               and r3.get("approval_required") is False
               and (r3.get("result") or {}).get("status") == "already_exists")
        results["退货建单"] = ok1 and ok2 and ok3
        print(f"[{'PASS' if results['退货建单'] else 'FAIL'}] 退货建单 建单={ok1} 审计={ok2} 重放不重复={ok3} request_id={rid}")

    # ---- 3) ineligible 不触发 interrupt ----
    g_cs3 = build_react_graph(model=None, mode="CUSTOMER_SERVICE", checkpointer=InMemorySaver())
    out4 = run_agent_react(g_cs3, "R3", sess_cs, "ORD_01_000427 申请退货")
    r4 = out4["response"]
    no_int = r4["status"] == "completed" and r4.get("approval_required") is False
    answered = any(w in r4["message"] for w in ("窗口", "不能退", "不可退", "ineligible", "不支持"))
    results["ineligible不中断"] = no_int and answered
    print(f"[{'PASS' if results['ineligible不中断'] else 'FAIL'}] ineligible不中断 status={r4['status']} 应答含窗口/不能退={answered}")
    print(f"        answer: {r4['message'][:110]!r}")

    # ---- 4) 补货确认（HAS_RECO → 挂起 → 确认 → confirmed，不写业务表）----
    g_ops = build_react_graph(model=None, mode="OPERATIONS", checkpointer=InMemorySaver())
    out5 = run_agent_react(g_ops, "R4", sess_ops, "SKU_01_STOCKOUT_01 需要补货吗")
    r5 = out5["response"]
    if r5["status"] != "approval_required":
        results["补货确认"] = False
        print("[FAIL] 补货未进入审批挂起:", r5["status"], r5["message"][:100])
    else:
        out6 = run_agent_react(g_ops, "R4", sess_ops, "", resume={"decision": "approved"})
        r6 = out6["response"]
        conf = (r6.get("result") or {}).get("status") == "confirmed"
        results["补货确认"] = r6["status"] == "completed" and conf
        print(f"[{'PASS' if results['补货确认'] else 'FAIL'}] 补货确认 confirmed={conf}")

    ok = all(results.values())
    print(f"\n结果: {sum(results.values())}/4")
    # 清理本评估建的 CS08-* 售后/审计行（防污染 legacy 测试；下次运行从干净态开始，幂等语义仍可验证）
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM audit_logs WHERE request_id LIKE 'CS08-%%' AND action='CREATE_RETURN_REQUEST'")
        cur.execute("DELETE FROM after_sales_requests WHERE idempotency_key LIKE 'CS08-%%'")
        conn.commit()
        cur.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

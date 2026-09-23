"""G6 FastAPI HTTP E2E（Phase 6 核查）：业务问答 / 审批确认 / 能力切换 / 会话持久化。

用法：python scripts/e2e_g6.py（需 127.0.0.1:8123 上的 copilot.api.app）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

BASE = "http://127.0.0.1:8123"


def post(path, body):
    r = requests.post(f"{BASE}{path}", json=body, timeout=120)
    r.raise_for_status()
    return r.json()


def main() -> int:
    results = {}

    # ---- 1) 业务问答（OPERATIONS）----
    sid1 = post("/api/session", {"user_id": 1, "workspace_mode": "OPERATIONS", "store_id": 1})["session_id"]
    r1 = post("/api/agent", {"session_id": sid1, "user_id": 1, "workspace_mode": "OPERATIONS",
                             "store_id": 1, "message": "SKU_01_STOCKOUT_01 缺货风险怎么样"})
    results["业务问答"] = r1["status"] == "completed" and "缺货" in r1["message"]
    print(f"[{'PASS' if results['业务问答'] else 'FAIL'}] 业务问答 status={r1['status']}")

    # ---- 2) 审批流（CUSTOMER_SERVICE：申请退货 → 挂起 → 确认 → 建单）----
    sid2 = post("/api/session", {"user_id": 1, "workspace_mode": "CUSTOMER_SERVICE", "store_id": 1})["session_id"]
    r2 = post("/api/agent", {"session_id": sid2, "user_id": 1, "workspace_mode": "CUSTOMER_SERVICE",
                             "store_id": 1, "message": "ORD_01_000438 申请退货"})
    a_ok = r2["approval_required"] and r2["status"] == "approval_required"
    r3 = post("/api/agent", {"session_id": sid2, "user_id": 1, "workspace_mode": "CUSTOMER_SERVICE",
                             "store_id": 1, "message": "", "resume": {"decision": "approved"}})
    b_ok = bool(r3["status"] == "completed" and (r3["result"] or {}).get("return_request_id"))
    results["审批确认建单"] = bool(a_ok and b_ok)
    print(f"[{'PASS' if results['审批确认建单'] else 'FAIL'}] 审批确认建单 挂起={a_ok} 建单={b_ok}")

    # ---- 3) 能力切换（UNSET → 缺货风险 → capability_required → 重跑）----
    sid3 = post("/api/session", {"user_id": 1, "workspace_mode": "UNSET", "store_id": 1})["session_id"]
    r4 = post("/api/agent", {"session_id": sid3, "user_id": 1, "workspace_mode": "UNSET",
                             "store_id": 1, "message": "SKU_01_STOCKOUT_01 缺货风险怎么样"})
    c_ok = r4["capability_required"] and (r4["capability_pending"] or {}).get("domain") == "operations"
    r5 = post("/api/agent", {"session_id": sid3, "user_id": 1, "workspace_mode": "OPERATIONS",
                             "store_id": 1, "message": "", "capability_replay": True})
    d_ok = r5["status"] == "completed" and "缺货" in r5["message"]
    results["能力切换重跑"] = c_ok and d_ok
    print(f"[{'PASS' if results['能力切换重跑'] else 'FAIL'}] 能力切换 请求={c_ok} 重跑完成={d_ok}")

    # ---- 4) 会话持久化（runtime.session 应有 3 个会话）----
    from copilot.db import connect, query
    with connect() as conn:
        rows = query(conn, "SELECT session_id, role FROM runtime.session WHERE session_id IN (%s,%s,%s)",
                     (sid1, sid2, sid3))
    results["会话持久化"] = len(rows) == 3
    print(f"[{'PASS' if results['会话持久化'] else 'FAIL'}] 会话持久化 rows={[(r['session_id'][:6], r['role']) for r in rows]}")

    ok = all(results.values())
    print(f"\n结果: {sum(results.values())}/4")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

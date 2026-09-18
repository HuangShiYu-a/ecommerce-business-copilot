"""SC 路由驱动：读 scenarios.yaml，对 data SC 跑对应 Tool，核对 expected_route。

当前覆盖 OP-05（T-R-01 正式结论）；其余 WF 随竖切扩展。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .context import ops_ctx
from .db import connect
from .tool import run_tool

SCENARIOS_PATH = Path(__file__).resolve().parent.parent / "data" / "scenarios" / "eval" / "scenarios.yaml"


def map_op05(result) -> tuple[str, str | None]:
    """T-R-01 结果 → route_status（UNDETERMINED 语义：缺事实≠不用补）。"""
    if result.ok:
        return ("HAS_RECO" if result.data.get("recommended_quantity", 0) > 0 else "NO_RECO"), None
    if result.error_code == "DATA_UNAVAILABLE":
        return "UNDETERMINED", result.error_detail
    return f"ERROR({result.error_code})", result.error_detail


def run_op05(s: dict, conn) -> dict:
    ctx = ops_ctx(2 if s["store_id"] == "STORE_02" else 1)
    res = run_tool("T-R-01", ctx, conn=conn, sku_code=s["sku_ids"][0])
    route, reason = map_op05(res)
    match = route == s["expected_route"]
    if s.get("expected_reason") and reason != s.get("expected_reason"):
        match = False
    return {
        "scenario_id": s["scenario_id"],
        "expected_route": s["expected_route"],
        "expected_reason": s.get("expected_reason"),
        "actual_route": route,
        "actual_reason": reason,
        "match": match,
        "detail": res.data or {"error": res.error_detail},
    }


def run_workflow(workflow: str = "OP-05") -> dict:
    payload = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
    scs = [s for s in payload["scenarios"]
           if s["workflow"] == workflow and s["nature"] == "data"]
    conn = connect()
    try:
        results = [run_op05(s, conn) for s in scs]
    finally:
        conn.close()
    passed = sum(1 for r in results if r["match"])
    return {
        "workflow": workflow,
        "total": len(results),
        "passed": passed,
        "gate": "PASS" if passed == len(results) else "FAIL",
        "results": results,
    }

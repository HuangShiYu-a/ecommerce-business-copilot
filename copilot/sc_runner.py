"""SC 路由驱动：读 scenarios.yaml，对 data SC 跑对应 Tool，核对 expected_route。

当前覆盖：OP-05（T-R-01）、OP-04（T-A-07）；其余 WF 随竖切扩展。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .context import ops_ctx
from .db import connect
from .tool import run_tool

SCENARIOS_PATH = Path(__file__).resolve().parent.parent / "data" / "scenarios" / "eval" / "scenarios.yaml"


def _store_id(code: str) -> int:
    return 2 if code == "STORE_02" else 1


def _match(s: dict, route: str, reason: str | None) -> bool:
    if route != s["expected_route"]:
        return False
    if s.get("expected_reason") and (not reason or s["expected_reason"] not in (reason or "")):
        return False
    return True


def _report(s: dict, route: str, reason: str | None, detail) -> dict:
    return {
        "scenario_id": s["scenario_id"],
        "expected_route": s["expected_route"],
        "expected_reason": s.get("expected_reason"),
        "actual_route": route,
        "actual_reason": reason,
        "match": _match(s, route, reason),
        "detail": detail,
    }


# ---- OP-05：T-R-01 → HAS_RECO / NO_RECO / UNDETERMINED ----
def map_op05(result) -> tuple[str, str | None]:
    if result.ok:
        return ("HAS_RECO" if result.data.get("recommended_quantity", 0) > 0 else "NO_RECO"), None
    if result.error_code == "DATA_UNAVAILABLE":
        return "UNDETERMINED", result.error_detail
    return f"ERROR({result.error_code})", result.error_detail


def run_op05(s: dict, conn) -> dict:
    res = run_tool("T-R-01", ops_ctx(_store_id(s["store_id"])), conn=conn,
                   sku_code=s["sku_ids"][0])
    route, reason = map_op05(res)
    return _report(s, route, reason, res.data or {"error": res.error_detail})


# ---- OP-04：T-A-07 → HAS_RISK / NO_RISK / UNDETERMINED ----
def map_op04(result) -> tuple[str, str | None]:
    if result.ok:
        return ("HAS_RISK" if result.data.get("risk_level") == "HIGH" else "NO_RISK"), None
    if result.error_code == "DATA_UNAVAILABLE":
        return "UNDETERMINED", result.error_detail
    return f"ERROR({result.error_code})", result.error_detail


def run_op04(s: dict, conn) -> dict:
    res = run_tool("T-A-07", ops_ctx(_store_id(s["store_id"])), conn=conn,
                   sku_code=s["sku_ids"][0], forecast_days=s.get("input_scope", {}).get("horizon_days"))
    route, reason = map_op04(res)
    return _report(s, route, reason, res.data or {"error": res.error_detail})


# ---- OP-07：T-A-05 → HEALTHY / UNDETERMINED ----
def map_op07(result) -> tuple[str, str | None]:
    if result.ok:
        return "HEALTHY", None
    if result.error_code == "DATA_UNAVAILABLE":
        return "UNDETERMINED", result.error_detail
    return f"ERROR({result.error_code})", result.error_detail


def run_op07(s: dict, conn) -> dict:
    res = run_tool("T-A-05", ops_ctx(_store_id(s["store_id"])), conn=conn,
                   sku_code=s["sku_ids"][0],
                   window_days=s.get("input_scope", {}).get("window_days"))
    route, reason = map_op07(res)
    return _report(s, route, reason, res.data or {"error": res.error_detail})


# ---- OP-08：T-A-06 → ANOMALY / NORMAL / UNDETERMINED ----
def map_op08(result) -> tuple[str, str | None]:
    if result.ok:
        return ("ANOMALY" if result.data.get("is_anomaly") else "NORMAL"), None
    if result.error_code == "DATA_UNAVAILABLE":
        return "UNDETERMINED", result.error_detail
    return f"ERROR({result.error_code})", result.error_detail


def run_op08(s: dict, conn) -> dict:
    res = run_tool("T-A-06", ops_ctx(_store_id(s["store_id"])), conn=conn,
                   sku_code=s["sku_ids"][0],
                   baseline_policy=s.get("input_scope", {}).get("baseline_policy"))
    route, reason = map_op08(res)
    return _report(s, route, reason, res.data or {"error": res.error_detail})


# ---- OP-03：T-A-04 → HAS_CANDIDATES / EMPTY / UNDETERMINED ----
def map_op03(result) -> tuple[str, str | None]:
    if result.ok:
        return ("HAS_CANDIDATES" if result.data.get("candidates") else "EMPTY"), None
    if result.error_code == "DATA_UNAVAILABLE":
        return "UNDETERMINED", result.error_detail
    return f"ERROR({result.error_code})", result.error_detail


def run_op03(s: dict, conn) -> dict:
    params = {}
    if s.get("sku_ids"):
        params["sku_code"] = s["sku_ids"][0]
    if s.get("input_scope", {}).get("category"):
        params["category"] = s["input_scope"]["category"]
    res = run_tool("T-A-04", ops_ctx(_store_id(s["store_id"])), conn=conn,
                   mode="slow_moving", **params)
    route, reason = map_op03(res)
    return _report(s, route, reason, res.data or {"error": res.error_detail})


# ---- CS-06：T-A-01 → NORMAL / ANOMALY / UNDETERMINED ----
def map_cs06(result) -> tuple[str, str | None]:
    if result.ok:
        return result.data.get("status"), None
    if result.error_code == "DATA_UNAVAILABLE":
        return "UNDETERMINED", result.error_detail
    return f"ERROR({result.error_code})", result.error_detail


def run_cs06(s: dict, conn) -> dict:
    res = run_tool("T-A-01", ops_ctx(_store_id(s["store_id"])), conn=conn,
                   order_no=s["order_no"])
    route, reason = map_cs06(res)
    return _report(s, route, reason, res.data or {"error": res.error_detail})


# ---- CS-08：T-A-09 → eligible / ineligible / undetermined ----
def map_cs08(result) -> tuple[str, str | None]:
    if result.ok:
        return result.data.get("decision"), result.data.get("reason_code")
    return f"ERROR({result.error_code})", result.error_detail


def run_cs08(s: dict, conn) -> dict:
    res = run_tool("T-A-09", ops_ctx(_store_id(s["store_id"])), conn=conn,
                   order_no=s["order_no"])
    route, reason = map_cs08(res)
    return _report(s, route, reason, res.data or {"error": res.error_detail})


# ---- ISO：T-A-01 跨店读 → NORMAL（D7 读放开 + source_store 标注）----
def run_iso(s: dict, conn) -> dict:
    # 上下文店 = STORE_01，读 STORE_02 订单 → 跨店读放开返回 NORMAL + source_store
    res = run_tool("T-A-01", ops_ctx(_store_id(s["store_id"])), conn=conn,
                   order_no=s["order_no"])
    route, reason = map_cs06(res)
    rep = _report(s, route, reason, res.data or {"error": res.error_detail})
    if res.ok and res.data.get("source_store"):
        rep["detail"] = {**rep["detail"], "source_store": res.data["source_store"]}
    return rep


RUNNERS = {"OP-05": run_op05, "OP-04": run_op04, "OP-07": run_op07,
           "OP-08": run_op08, "OP-03": run_op03, "CS-06": run_cs06,
           "CS-08": run_cs08, "ISO": run_iso}


def run_workflow(workflow: str = "OP-05") -> dict:
    runner = RUNNERS.get(workflow)
    if runner is None:
        raise ValueError(f"未实现的 workflow runner: {workflow}")
    payload = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
    scs = [s for s in payload["scenarios"]
           if s["workflow"] == workflow and s["nature"] == "data"]
    conn = connect()
    try:
        results = [runner(s, conn) for s in scs]
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

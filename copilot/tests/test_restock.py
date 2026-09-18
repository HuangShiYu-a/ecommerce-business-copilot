"""S4.2 集成测试（OP-05 竖切）：依赖 Docker PG（localhost:5434）+ dev 数据已导入。

运行前提：docker-compose up -d && schema.sql && import_data.py --profile dev。
"""
import pytest

from copilot.context import ops_ctx
from copilot.sc_runner import run_workflow
from copilot.tool import run_tool


def test_restock_stockout_has_reco():
    res = run_tool("T-R-01", ops_ctx(1), sku_code="SKU_01_STOCKOUT_01")
    assert res.ok, res
    assert res.data["recommended_quantity"] > 0
    assert res.data["method"] == "historical_sales_estimate"


def test_restock_normal_no_reco():
    res = run_tool("T-R-01", ops_ctx(1), sku_code="SKU_01_NORMAL_01")
    assert res.ok, res
    assert res.data["recommended_quantity"] == 0


def test_restock_missing_lead_time_undetermined():
    res = run_tool("T-R-01", ops_ctx(2), sku_code="SKU_02_STOCKOUT_01")
    assert not res.ok
    assert res.error_code == "DATA_UNAVAILABLE"
    assert res.error_detail == "MISSING_LEAD_TIME_CONFIG"


def test_stockout_risk_stockout_high():
    res = run_tool("T-A-07", ops_ctx(1), sku_code="SKU_01_STOCKOUT_01", forecast_days=14)
    assert res.ok, res
    assert res.data["risk_level"] == "HIGH"


def test_get_inventory_query():
    res = run_tool("T-Q-03", ops_ctx(1), sku_code="SKU_01_STOCKOUT_01")
    assert res.ok, res
    assert res.data["sku_code"] == "SKU_01_STOCKOUT_01"
    assert res.data["available_qty"] >= 0


def test_sc_runner_op05_all_data_sc_pass():
    report = run_workflow("OP-05")
    assert report["total"] == 4, report   # SC-OP05-001/002/003/004（data 型）
    assert report["passed"] == 4, report
    assert report["gate"] == "PASS"


def test_sc_runner_route_details():
    report = run_workflow("OP-05")
    by_id = {r["scenario_id"]: r for r in report["results"]}
    assert by_id["SC-OP05-001"]["actual_route"] == "HAS_RECO"
    assert by_id["SC-OP05-002"]["actual_route"] == "NO_RECO"
    assert by_id["SC-OP05-003"]["actual_route"] == "UNDETERMINED"
    assert by_id["SC-OP05-003"]["actual_reason"] == "MISSING_LEAD_TIME_CONFIG"
    assert by_id["SC-OP05-004"]["actual_route"] == "HAS_RECO"


# ---- OP-04（T-A-07）----

def test_stockout_sparse_undetermined():
    res = run_tool("T-A-07", ops_ctx(1), sku_code="SKU_01_SPARSE_SALES_01", forecast_days=14)
    assert not res.ok
    assert res.error_code == "DATA_UNAVAILABLE"
    assert res.error_detail == "MISSING_SALES_WINDOW"


def test_stockout_normal_no_risk():
    res = run_tool("T-A-07", ops_ctx(1), sku_code="SKU_01_NORMAL_01", forecast_days=14)
    assert res.ok, res
    assert res.data["risk_level"] == "NORMAL"


def test_sc_runner_op04_all_data_sc_pass():
    report = run_workflow("OP-04")
    assert report["total"] == 4, report
    assert report["passed"] == 4, report
    assert report["gate"] == "PASS"


def test_sc_runner_op04_route_details():
    report = run_workflow("OP-04")
    by_id = {r["scenario_id"]: r for r in report["results"]}
    assert by_id["SC-OP04-001"]["actual_route"] == "HAS_RISK"
    assert by_id["SC-OP04-002"]["actual_route"] == "NO_RISK"
    assert by_id["SC-OP04-003"]["actual_route"] == "UNDETERMINED"
    assert by_id["SC-OP04-003"]["actual_reason"] == "MISSING_SALES_WINDOW"
    assert by_id["SC-OP04-004"]["actual_route"] == "HAS_RISK"

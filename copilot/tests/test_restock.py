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


# ---- CS-08（T-A-09 资格三态 / T-X-01 创建退货申请）----

from copilot.context import UserContext

CS_CTX = UserContext(user_id=1, role="customer_service", store_id=1)


def test_ta09_eligible_within_window():
    res = run_tool("T-A-09", CS_CTX, order_no="ORD_01_000438")
    assert res.ok, res
    assert res.data["decision"] == "eligible"
    assert res.data["reason_code"] == "WITHIN_RETURN_WINDOW"


def test_ta09_ineligible_expired():
    res = run_tool("T-A-09", CS_CTX, order_no="ORD_01_000427")
    assert res.ok, res
    assert res.data["decision"] == "ineligible"
    assert res.data["reason_code"] == "RETURN_WINDOW_EXPIRED"


def test_ta09_undetermined_missing_signed():
    res = run_tool("T-A-09", CS_CTX, order_no="ORD_01_000036")
    assert res.ok, res
    assert res.data["decision"] == "undetermined"
    assert res.data["reason_code"] == "MISSING_SIGNED_AT"


def test_ta09_rule_conflict():
    """SC-CS08-007：CONF-01(7日)/CONF-02(15日) 同层冲突 → RULE_CONFLICT → undetermined。"""
    res = run_tool("T-A-09", CS_CTX, order_no="ORD_01_CS0807_001")
    assert res.ok, res
    assert res.data["decision"] == "undetermined"
    assert res.data["reason_code"] == "RULE_CONFLICT"


@pytest.fixture
def _clean_tx01():
    from copilot.db import connect

    # P5：前置清理 CS08 残留（手动 live 测试会建 CS08-* 行；test_restock 按字母序先于
    # test_workflow 运行，不前置清理会被可退数量校验误伤）。
    conn = connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM after_sales_requests WHERE idempotency_key LIKE 'CS08-%'")
    cur.execute("DELETE FROM audit_logs WHERE request_id LIKE 'CS08-%' AND action='CREATE_RETURN_REQUEST'")
    conn.commit()
    cur.close()
    conn.close()

    yield
    conn = connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM audit_logs WHERE request_id LIKE 'tx01_%'")
    cur.execute("DELETE FROM after_sales_requests WHERE idempotency_key LIKE 'tx01_%'")
    conn.commit()
    cur.close()
    conn.close()


def test_tx01_requires_approval(_clean_tx01):
    res = run_tool("T-X-01", CS_CTX, order_id=438, item_id=438, quantity=1,
                   reason="七天无理由", request_id="tx01_noappr")
    assert res.error_code == "APPROVAL_REQUIRED"


def test_tx01_rejected_approval(_clean_tx01):
    ap = {"approver_id": 5, "approved_at": "2026-09-17", "decision": "rejected"}
    res = run_tool("T-X-01", CS_CTX, order_id=438, item_id=438, quantity=1,
                   reason="x", request_id="tx01_rej", approval=ap)
    assert res.error_code == "APPROVAL_REQUIRED"


def test_tx01_over_quantity(_clean_tx01):
    ap = {"approver_id": 5, "approved_at": "2026-09-17", "decision": "approved"}
    res = run_tool("T-X-01", CS_CTX, order_id=438, item_id=438, quantity=99,
                   reason="x", request_id="tx01_over", approval=ap)
    assert res.error_code == "PRECONDITION_FAILED"


def test_tx01_create_and_idempotent(_clean_tx01):
    ap = {"approver_id": 5, "approved_at": "2026-09-17", "decision": "approved"}
    r1 = run_tool("T-X-01", CS_CTX, order_id=438, item_id=438, quantity=1,
                  reason="七天无理由", request_id="tx01_ok", approval=ap)
    assert r1.ok, r1
    rid = r1.data["return_request_id"]
    # 幂等：同一 request_id 重复提交 → 返回同一单
    r2 = run_tool("T-X-01", CS_CTX, order_id=438, item_id=438, quantity=1,
                  reason="七天无理由", request_id="tx01_ok", approval=ap)
    assert r2.ok and r2.data["return_request_id"] == rid
    assert r2.data.get("idempotent") is True

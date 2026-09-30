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


# ---- CS-06（T-A-01 物流履约，H2：在途超期→ANOMALY）----

def test_ta01_in_transit_overdue_anomaly():
    """H2：已发货未送达且承诺日已过 as_of → ANOMALY(overdue_in_transit)。"""
    res = run_tool("T-A-01", ops_ctx(1), order_no="ORD_01_001454")
    assert res.ok, res
    assert res.data["status"] == "ANOMALY"
    assert res.data["reason"] == "overdue_in_transit"
    assert res.data["overdue_days"] >= 1


def test_ta01_in_transit_not_overdue_normal():
    """H2：已发货未送达但承诺日未过 as_of → NORMAL(in_transit)。"""
    res = run_tool("T-A-01", ops_ctx(1), order_no="ORD_01_000001")
    assert res.ok, res
    assert res.data["status"] == "NORMAL"
    assert res.data["reason"] == "in_transit"


def test_ta01_delivered_late_anomaly():
    """SC-CS06-002 等价：已送达但超 promised → ANOMALY(over_promised)。"""
    res = run_tool("T-A-01", ops_ctx(1), order_no="ORD_01_000002")
    assert res.ok, res
    assert res.data["status"] == "ANOMALY"
    assert res.data["reason"] == "over_promised"


def test_ta01_delivered_on_time_normal():
    res = run_tool("T-A-01", ops_ctx(1), order_no="ORD_01_000003")
    assert res.ok, res
    assert res.data["status"] == "NORMAL"
    assert res.data["reason"] == "on_time"


def test_ta01_missing_promised_undetermined():
    """SC-CS06-003 等价：缺 promised_delivery_at → UNDETERMINED。"""
    res = run_tool("T-A-01", ops_ctx(1), order_no="ORD_01_000035")
    assert not res.ok
    assert res.error_code == "DATA_UNAVAILABLE"
    assert res.error_detail == "MISSING_PROMISED_AT"


# ---- H3/L4（状态口径：可退数量 / 健康度 returns 只算成功态）----

from copilot.db import connect, query_one  # noqa: E402


def _next_asr_id(conn):
    return query_one(conn, "SELECT COALESCE(MAX(id),0)+1 AS n FROM after_sales_requests")["n"]


def _insert_asr(conn, key, status, quantity=1, item_id=438, order_id=438, customer_id=183):
    """插入一条受控 after_sales 行（item 438 / SKU_01_NORMAL_01），幂等键=key。"""
    nid = _next_asr_id(conn)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO after_sales_requests
                (id, store_id, request_no, order_id, order_item_id, customer_id, type,
                 quantity, status, idempotency_key, reason)
            VALUES (%s,1,%s,%s,%s,%s,'RETURN',%s,%s,%s,'口径测试')
            ON CONFLICT (store_id, idempotency_key) DO NOTHING
        """, (nid, f"ASRH3{nid:09d}", order_id, item_id, customer_id, quantity, status, key))
    conn.commit()


def test_h3_rejected_not_counted_returnable():
    """H3：REJECTED 售后不占可退量——预置 REJECTED 行后同 item 仍可申请。"""
    ap = {"approver_id": 5, "approved_at": "2026-09-17", "decision": "approved"}
    conn = connect()
    try:
        _insert_asr(conn, "h3rej", "REJECTED")
        res = run_tool("T-X-01", CS_CTX, order_id=438, item_id=438, quantity=1,
                       reason="测试", request_id="h3ok", approval=ap)
        assert res.ok, res
        assert res.data["status"] == "APPROVED"
    finally:
        cur = conn.cursor()
        cur.execute("DELETE FROM audit_logs WHERE request_id IN ('h3rej','h3ok')")
        cur.execute("DELETE FROM after_sales_requests WHERE idempotency_key IN ('h3rej','h3ok')")
        conn.commit()
        cur.close()
        conn.close()


def test_health_returns_success_status_only():
    """L4：健康度 returns 维度只算成功态（REJECTED 不计、COMPLETED 计）。"""
    conn = connect()
    try:
        _insert_asr(conn, "h3l4rej", "REJECTED")
        res = run_tool("T-A-05", ops_ctx(1), sku_code="SKU_01_NORMAL_01")
        assert res.ok, res
        assert res.data["dimensions"]["returns"] == "missing", res.data["dimensions"]
        with conn.cursor() as cur:
            cur.execute("UPDATE after_sales_requests SET status='COMPLETED' WHERE idempotency_key='h3l4rej'")
        conn.commit()
        res2 = run_tool("T-A-05", ops_ctx(1), sku_code="SKU_01_NORMAL_01")
        assert res2.ok, res2
        assert res2.data["dimensions"]["returns"] == "present", res2.data["dimensions"]
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM after_sales_requests WHERE idempotency_key LIKE 'h3l4%%'")
        conn.commit()
        conn.close()


# ---- M1：慢销窗口销量只算窗口内有效订单 ----

def test_slow_moving_window_units_excludes_cancelled():
    """M1：SKU_01_SLOW_01 窗口销量应为 4（原实现含 CANCELLED 误计为 6）。"""
    res = run_tool("T-A-04", ops_ctx(1), sku_code="SKU_01_SLOW_01")
    assert res.ok, res
    cand = {c["sku_code"]: c for c in res.data["candidates"]}
    assert "SKU_01_SLOW_01" in cand, res.data
    assert cand["SKU_01_SLOW_01"]["units"] == 4, cand["SKU_01_SLOW_01"]


def test_slow_moving_full_scan_no_filter():
    """慢销全量：不传 sku_code/category → 返回全店候选（含 SKU_01_SLOW_01）。

    修复：原 gate 对「无参」返回 PERF_QUERY_FAIL，无法回答『有哪些慢销商品』；
    calc 本就支持 category=None 全店扫描，放行即可。
    """
    res = run_tool("T-A-04", ops_ctx(1))
    assert res.ok, res
    cand = {c["sku_code"]: c for c in res.data["candidates"]}
    assert "SKU_01_SLOW_01" in cand, res.data


# ---- L6：销售异常基线不足标注 ----

def test_sales_anomaly_baseline_insufficient_flag():
    """L6：前 7 天无销量基线 → baseline_insufficient=true（判定按口径不判异常，仅标注）。"""
    res = run_tool("T-A-06", ops_ctx(1), sku_code="SKU_01_SLOW_HEALTHY_01")
    assert res.ok, res
    assert res.data["prev_7d_units"] == 0
    assert res.data["baseline_insufficient"] is True

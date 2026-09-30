"""M2 谓词单测（C1）：8 个 workflow 的 predicate 闭包 + predicate_for 派发。"""
from __future__ import annotations

from copilot.eval.predicates import (cs06, cs08_already_exists, cs08_eligibility,
                                     iso_cross_store, op03, op04, op05, op07, op08,
                                     predicate_for)


def _resp(result, status="completed", msg="", approval_required=False):
    return {"message": msg, "status": status, "approval_required": approval_required,
            "result": result}


def test_cs06_routes():
    assert cs06("ANOMALY")(_resp({"route": "ANOMALY"}, msg="订单已延误"))[0] is True
    assert cs06("NORMAL")(_resp({"route": "ANOMALY"}))[0] is False
    assert cs06("UNDETERMINED")(_resp({"route": "UNDETERMINED"}))[0] is True


def test_cs08_eligibility_and_already_exists():
    assert cs08_eligibility("eligible")(_resp({"decision": "eligible"},
                                              msg="可以退货"))[0] is True
    assert cs08_eligibility("ineligible")(_resp({"decision": "eligible"}))[0] is False
    # H1：已成功售后 → already_exists，不 approval_required
    assert cs08_already_exists()(_resp({"status": "already_exists"},
                                       approval_required=False))[0] is True
    # 若已 approval_required（interrupt）→ 不是 already_exists 路径
    assert cs08_already_exists()(_resp({"status": "already_exists"},
                                       approval_required=True))[0] is False


def test_op03_candidates():
    assert op03("HAS_CANDIDATES", "SKU_01_SLOW_01")(
        _resp({"candidates": [{"sku_code": "SKU_01_SLOW_01", "units": 4}]}))[0] is True
    assert op03("HAS_CANDIDATES", "SKU_01_SLOW_01")(
        _resp({"candidates": [{"sku_code": "OTHER"}]}))[0] is False   # 未命中指定 SKU
    assert op03("EMPTY")(_resp({"candidates": []}))[0] is True
    assert op03("HAS_CANDIDATES")(_resp({"candidates": []}))[0] is False


def test_op04_risk():
    assert op04("HAS_RISK")(_resp({"risk_level": "HIGH"}))[0] is True
    assert op04("NO_RISK")(_resp({"risk_level": "NORMAL"}))[0] is True
    assert op04("HAS_RISK")(_resp({"risk_level": "NORMAL"}))[0] is False
    assert op04("UNDETERMINED")(_resp({"error_code": "DATA_UNAVAILABLE"}))[0] is True


def test_op05_workflow():
    assert op05("HAS_RECO")(_resp({"status": "confirmed"}))[0] is True
    assert op05("HAS_RECO")(_resp({"status": "no_reco"}))[0] is False
    assert op05("NO_RECO")(_resp({"status": "no_reco"}))[0] is True
    assert op05("UNDETERMINED")(_resp({"error_code": "CONFIG_MISSING"}))[0] is True


def test_op07_health_smoke():
    assert op07()(_resp({"score": 100.0}))[0] is True
    assert op07()(_resp({"error_code": "DATA_UNAVAILABLE"}))[0] is False


def test_op08_anomaly():
    assert op08("ANOMALY")(_resp({"is_anomaly": True}))[0] is True
    assert op08("NORMAL")(_resp({"is_anomaly": False}))[0] is True
    assert op08("ANOMALY")(_resp({"is_anomaly": False}))[0] is False
    assert op08("UNDETERMINED")(_resp({"error_code": "X"}))[0] is True


def test_iso_cross_store():
    assert iso_cross_store()(_resp({"source_store": 2}))[0] is True
    assert iso_cross_store()(_resp({"source_store": 1}))[0] is False


def test_predicate_for_dispatch():
    # CS-08-006 → already_exists 路径；CS-08-001 → eligibility
    p1 = predicate_for({"scenario_id": "SC-CS08-006", "workflow": "CS-08",
                        "expected_route": None})
    assert p1(_resp({"status": "already_exists"}, approval_required=False,
                    msg="订单已有退货申请，不再重复创建"))[0] is True
    p2 = predicate_for({"scenario_id": "SC-CS08-001", "workflow": "CS-08",
                        "expected_route": "eligible"})
    assert p2(_resp({"decision": "eligible"}, msg="可以退货"))[0] is True
    # OP-03 带 SKU
    p3 = predicate_for({"scenario_id": "SC-OP03-001", "workflow": "OP-03",
                        "expected_route": "HAS_CANDIDATES", "sku_ids": ["SKU_01_SLOW_01"]})
    assert p3(_resp({"candidates": [{"sku_code": "SKU_01_SLOW_01"}]}))[0] is True

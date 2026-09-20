"""P8 / S3.7 eval 切片门禁测试：含全部 SC 引用 / 同 seed / 是 dev 子集 / validate 无 P0 失败 / §12A 对照。"""
import json
from pathlib import Path

import pytest
import yaml

from data.generator.config import load_config
from data.generator.eval_slice import EVAL_TABLES
from data.generator.generate import generate
from data.generator.scenarios import SCENARIOS_PATH
from data.generator.transactions import _read_csv


def _read(path: Path):
    return _read_csv(path)


@pytest.fixture()
def ev(tmp_path):
    generate(load_config("dev"), output_root=tmp_path)
    generate(load_config("eval"), output_root=tmp_path)
    return tmp_path


def test_eval_manifest_seed_and_stage(ev):
    m = json.loads((ev / "eval" / "canonical" / "manifest.json").read_text(encoding="utf-8"))
    assert m["seed"] == 42
    assert m["stage"] == "S3.7-eval"
    assert m["basis"] == "dev 同库 + manifest 过滤"


def test_eval_contains_all_sc_refs(ev):
    payload = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
    eval_skus = {r["sku_code"] for r in _read(ev / "eval" / "canonical" / "product_skus.csv")}
    eval_orders = {r["order_no"] for r in _read(ev / "eval" / "canonical" / "orders.csv")}
    for s in payload["scenarios"]:
        for code in s.get("sku_ids") or []:
            assert code in eval_skus, s["scenario_id"]
        if s["order_no"]:
            assert s["order_no"] in eval_orders, s["scenario_id"]


def test_eval_is_subset_of_dev(ev):
    for t in EVAL_TABLES:
        dev = {tuple(sorted(r.items())) for r in _read(ev / "dev" / "canonical" / f"{t}.csv")}
        evl = {tuple(sorted(r.items())) for r in _read(ev / "eval" / "canonical" / f"{t}.csv")}
        assert evl <= dev, f"{t} 含 dev 之外的行"


def test_eval_validate_gate(ev):
    rep = json.loads((ev / "eval" / "validate_report.json").read_text(encoding="utf-8"))
    assert rep["gate"] == "PASS"
    assert rep["p0_failures"] == []


def test_eval_has_s12a_context(ev):
    statuses = {o["status"] for o in _read(ev / "eval" / "canonical" / "orders.csv")}
    assert "CANCELLED" in statuses
    assert "PENDING_PAYMENT" in statuses


def test_eval_has_knowledge_and_conflict_order(ev):
    docs = _read(ev / "eval" / "canonical" / "knowledge_documents.csv")
    assert len(docs) == 12
    orders = {o["order_no"] for o in _read(ev / "eval" / "canonical" / "orders.csv")}
    assert "ORD_01_CS0807_001" in orders

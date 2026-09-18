"""P5 / S3.4 Scenario 绑定门禁测试：33 条 / 26 data+7 runtime / 引用可解析 / conflict 绑定 / runtime 仅前置。"""
import csv
import json
from pathlib import Path

import pytest
import yaml

from data.generator.config import load_config
from data.generator.generate import generate
from data.generator.scenarios import SCENARIOS_PATH

CLEAN_RETURNABLE = {"服装/服饰", "家居/家纺", "母婴/玩具"}
EXCLUDED_TAGS = {"apparel-intimate", "apparel-conflict-test"}


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture()
def sc(tmp_path):
    cfg = load_config("dev")
    generate(cfg, output_root=tmp_path)
    return SCENARIOS_PATH


def test_scenarios_written_and_count(sc):
    assert sc.exists()
    payload = yaml.safe_load(sc.read_text(encoding="utf-8"))
    scs = payload["scenarios"]
    assert len(scs) == 33
    assert len({s["scenario_id"] for s in scs}) == 33
    assert payload["dataset"]["seed"] == 42


def test_data_runtime_split(sc):
    payload = yaml.safe_load(sc.read_text(encoding="utf-8"))
    n_data = sum(1 for s in payload["scenarios"] if s["nature"] == "data")
    n_runtime = sum(1 for s in payload["scenarios"] if s["nature"] == "runtime_eval")
    assert n_data == 26 and n_runtime == 7


def test_data_scenarios_references_resolvable(tmp_path):
    """data 型 SC 的 sku_ids / order_no 必须能在生成数据中解析。"""
    from data.generator.transactions import _read_csv

    generate(load_config("dev"), output_root=tmp_path)
    canonical = tmp_path / "dev" / "canonical"
    sku_codes = {s["sku_code"] for s in _read_csv(canonical / "product_skus.csv")}
    order_nos = {o["order_no"] for o in _read_csv(canonical / "orders.csv")}

    payload = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
    for s in payload["scenarios"]:
        for code in s.get("sku_ids") or []:
            assert code in sku_codes, s["scenario_id"]
        if s["order_no"]:
            assert s["order_no"] in order_nos, s["scenario_id"]


def test_conflict_order_bound(sc):
    payload = yaml.safe_load(sc.read_text(encoding="utf-8"))
    s007 = next(s for s in payload["scenarios"] if s["scenario_id"] == "SC-CS08-007")
    assert s007["nature"] == "runtime_eval"
    assert "CS0807" in s007["order_no"]
    assert s007["expected_route"] == "undetermined"
    assert s007["expected_reason"] == "RULE_CONFLICT"


def test_store02_config_scenarios_on_store02(sc):
    payload = yaml.safe_load(sc.read_text(encoding="utf-8"))
    for sid in ("SC-OP05-003", "SC-OP08-003"):
        s = next(s for s in payload["scenarios"] if s["scenario_id"] == sid)
        assert s["store_id"] == "STORE_02"


def test_runtime_eval_only_preconditions(sc):
    payload = yaml.safe_load(sc.read_text(encoding="utf-8"))
    for s in payload["scenarios"]:
        if s["nature"] == "runtime_eval":
            assert "harness" in s["remarks"] or "S4" in s["remarks"], s["scenario_id"]


def test_cs08_eligible_ineligible_on_clean_returnable(tmp_path):
    """SC-CS08-001/002 应绑定到无条件可退类目（apparel/home/baby），且非 intimate/conflict 产品。"""
    generate(load_config("dev"), output_root=tmp_path)
    canonical = tmp_path / "dev" / "canonical"
    orders = _read_csv(canonical / "orders.csv")
    items = _read_csv(canonical / "order_items.csv")
    skus = _read_csv(canonical / "product_skus.csv")
    products = _read_csv(canonical / "products.csv")
    categories = _read_csv(canonical / "product_categories.csv")

    order_by_no = {o["order_no"]: o for o in orders}
    item_by_order = {}
    for it in items:
        item_by_order.setdefault(it["order_id"], []).append(it)
    sku_by_id = {int(s["id"]): s for s in skus}
    prod_by_id = {int(p["id"]): p for p in products}
    cat_by_id = {int(c["id"]): c["name"] for c in categories}

    payload = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
    for sid in ("SC-CS08-001", "SC-CS08-002"):
        s = next(s for s in payload["scenarios"] if s["scenario_id"] == sid)
        o = order_by_no[s["order_no"]]
        it = item_by_order[o["id"]][0]
        sku = sku_by_id[int(it["sku_id"])]
        attrs = json.loads(sku["attributes"])
        assert attrs.get("product_type") not in EXCLUDED_TAGS, sid
        cat = cat_by_id[int(prod_by_id[int(sku["product_id"])]["category_id"])]
        assert cat in CLEAN_RETURNABLE, sid

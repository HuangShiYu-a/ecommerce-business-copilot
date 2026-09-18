"""P2 / S3.1 Master 门禁测试：7 表存在 / FK 自洽 / 两店隔离 / StoreConfig / 角色覆盖 / conflict / 类目。"""
import csv
import json
from pathlib import Path

import pytest

from data.generator.config import load_config
from data.generator.master import (
    CONFLICT_SKU_CODE,
    CONFLICT_TAG,
    INTIMATE_SKU_CODE,
    INTIMATE_TAG,
    MASTER_TABLES,
    ROLE_CATEGORY,
    generate_master,
)


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture()
def master(tmp_path):
    cfg = load_config("dev")
    canonical = tmp_path / "dev" / "canonical"
    generate_master(cfg, canonical, tmp_path)
    data = {t: _read_csv(canonical / f"{t}.csv") for t in MASTER_TABLES}
    data["sku_roles"] = _read_csv(tmp_path / "dev" / "sku_roles.csv")
    return {"canonical": canonical, "data": data}


def test_all_master_tables_created(master):
    for t in MASTER_TABLES:
        assert (master["canonical"] / f"{t}.csv").exists()
    assert len(master["data"]["stores"]) == 2
    assert len(master["data"]["products"]) > 0


def test_fk_integrity(master):
    d = master["data"]
    store_ids = {int(r["id"]) for r in d["stores"]}
    for t in ["staff_users", "warehouses", "products", "product_skus", "store_configs"]:
        for row in d[t]:
            assert int(row["store_id"]) in store_ids, (t, row)

    cat_ids = {int(r["id"]): int(r["store_id"]) for r in d["product_categories"]}
    for p in d["products"]:
        assert int(p["category_id"]) in cat_ids
        assert cat_ids[int(p["category_id"])] == int(p["store_id"]), p

    prod_ids = {int(r["id"]): int(r["store_id"]) for r in d["products"]}
    for s in d["product_skus"]:
        assert int(s["product_id"]) in prod_ids
        assert prod_ids[int(s["product_id"])] == int(s["store_id"]), s


def test_two_store_isolation_and_categories(master):
    d = master["data"]
    cats = {1: [], 2: []}
    for r in d["product_categories"]:
        cats[int(r["store_id"])].append(r["name"])
    assert len(cats[1]) == 8
    assert 0 < len(cats[2]) < 8

    prods = {1: [], 2: []}
    for r in d["products"]:
        prods[int(r["store_id"])].append(r)
    assert len(prods[1]) > 0 and len(prods[2]) > 0
    # 隔离：STORE_02 的 products 的 category_id 都属于 STORE_02 的类目
    cat_store = {int(r["id"]): int(r["store_id"]) for r in d["product_categories"]}
    for p in prods[2]:
        assert cat_store[int(p["category_id"])] == 2


def test_store_config_keys(master):
    d = master["data"]
    cfg1 = {r["config_key"]: r["config_value"] for r in d["store_configs"] if r["store_id"] == "1"}
    cfg2 = {r["config_key"]: r["config_value"] for r in d["store_configs"] if r["store_id"] == "2"}
    p0 = {
        "inventory.lead_time_days", "inventory.default_horizon_days",
        "inventory.slow_moving.lookback_days", "inventory.slow_moving.max_units",
        "health.weights", "health.core_dimensions", "health.optional_dimensions",
        "anomaly.baseline_mode", "anomaly.sales_drop_threshold",
    }
    assert p0 <= set(cfg1)
    assert "inventory.lead_time_days" not in cfg2
    assert "anomaly.sales_drop_threshold" not in cfg2

    weights = json.loads(cfg1["health.weights"])
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    core = json.loads(cfg1["health.core_dimensions"])
    assert sorted(core) == ["feedback", "inventory", "margin", "return", "sales"]


def test_role_coverage(master):
    sku_roles = master["data"]["sku_roles"]
    by_role = {}
    for r in sku_roles:
        by_role.setdefault(r["role_id"], []).append(r)
    for role in ROLE_CATEGORY:
        assert len(by_role.get(role, [])) >= 1, f"role {role} 无 SKU"
    assert len(by_role.get("R_NORMAL", [])) >= 3
    assert len(by_role.get("R_HOT", [])) >= 3
    codes = {r["sku_code"] for r in sku_roles}
    assert "SKU_01_STOCKOUT_01" in codes
    assert "SKU_01_NORMAL_01" in codes


def test_conflict_product(master):
    d = master["data"]
    sku = next(r for r in d["product_skus"] if r["sku_code"] == CONFLICT_SKU_CODE)
    assert sku["store_id"] == "1"
    attrs = json.loads(sku["attributes"])
    assert attrs.get("product_type") == CONFLICT_TAG
    prod = next(p for p in d["products"] if p["id"] == sku["product_id"])
    cat = next(c for c in d["product_categories"] if c["id"] == prod["category_id"])
    assert cat["name"] == "服装/服饰"
    role_row = next(r for r in master["data"]["sku_roles"] if r["sku_code"] == CONFLICT_SKU_CODE)
    assert role_row["conflict_test"] == "true"


def test_apparel_intimate_product(master):
    d = master["data"]
    sku = next(r for r in d["product_skus"] if r["sku_code"] == INTIMATE_SKU_CODE)
    assert sku["store_id"] == "1"
    attrs = json.loads(sku["attributes"])
    assert attrs.get("product_type") == INTIMATE_TAG
    prod = next(p for p in d["products"] if p["id"] == sku["product_id"])
    cat = next(c for c in d["product_categories"] if c["id"] == prod["category_id"])
    assert cat["name"] == "服装/服饰"
    # 非 conflict：与冲突测试产品不重叠
    role_row = next(r for r in master["data"]["sku_roles"] if r["sku_code"] == INTIMATE_SKU_CODE)
    assert role_row["conflict_test"] == "false"


def test_role_not_in_business_columns(master):
    # 红线：canonical product_skus 不得有 role / risk 列（S2 §6）
    assert "role" not in master["data"]["product_skus"][0]
    assert "risk_level" not in master["data"]["product_skus"][0]

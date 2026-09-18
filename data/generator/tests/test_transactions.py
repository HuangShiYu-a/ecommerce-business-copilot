"""P3 / S3.2 交易主链门禁测试：7 表 / 无 Movement / 时间序 / §12A / 角色叙事 / conflict 订单 / 库存。"""
import csv
from datetime import date, datetime
from pathlib import Path

import pytest

from data.generator.config import load_config
from data.generator.generate import generate
from data.generator.transactions import TRANS_TABLES

VALID_SALES = {"PROCESSING", "SHIPPED", "COMPLETED"}
AS_OF = date(2026, 9, 17)


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture()
def tx(tmp_path):
    cfg = load_config("dev")
    generate(cfg, output_root=tmp_path)
    canonical = tmp_path / "dev" / "canonical"
    data = {t: _read_csv(canonical / f"{t}.csv") for t in TRANS_TABLES}
    data["product_skus"] = _read_csv(canonical / "product_skus.csv")
    data["sku_roles"] = _read_csv(tmp_path / "dev" / "sku_roles.csv")
    return {"canonical": canonical, "data": data}


def test_trans_tables_created(tx):
    for t in TRANS_TABLES:
        assert (tx["canonical"] / f"{t}.csv").exists()
    assert len(tx["data"]["orders"]) > 500


def test_no_movements(tx):
    assert not (tx["canonical"] / "inventory_movements.csv").exists()


def test_time_order_consistency(tx):
    for o in tx["data"]["orders"]:
        if o["status"] != "COMPLETED":
            continue
        ordered = datetime.fromisoformat(o["ordered_at"])
        paid = datetime.fromisoformat(o["paid_at"])
        shipped = datetime.fromisoformat(o["shipped_at"])
        delivered = datetime.fromisoformat(o["delivered_at"])
        if not o["signed_at"]:
            # 已送达未签收（SC-CS08-003 缺签收边界）：签收/完成空
            assert delivered >= shipped
            assert o["signed_at"] == "" and o["completed_at"] == ""
            continue
        signed = datetime.fromisoformat(o["signed_at"])
        assert ordered <= paid <= shipped <= delivered <= signed, o


def test_valid_sales_status_and_excluded(tx):
    statuses = {o["status"] for o in tx["data"]["orders"]}
    assert statuses <= VALID_SALES | {"CANCELLED", "PENDING_PAYMENT"}
    n_valid = sum(1 for o in tx["data"]["orders"] if o["status"] in VALID_SALES)
    assert n_valid > 500
    assert any(o["status"] == "CANCELLED" for o in tx["data"]["orders"])
    assert any(o["status"] == "PENDING_PAYMENT" for o in tx["data"]["orders"])


def test_role_narrative_distinguishable(tx):
    valid_order_ids = {int(o["id"]) for o in tx["data"]["orders"] if o["status"] in VALID_SALES}
    sku_id_to_code = {int(s["id"]): s["sku_code"] for s in tx["data"]["product_skus"]}
    units = {}
    for it in tx["data"]["order_items"]:
        if int(it["order_id"]) not in valid_order_ids:
            continue
        code = sku_id_to_code[int(it["sku_id"])]
        units[code] = units.get(code, 0) + int(it["quantity"])
    role_of = {r["sku_code"]: r["role_id"] for r in tx["data"]["sku_roles"]}

    def avg_units(role):
        codes = [c for c, r in role_of.items() if r == role]
        vals = [units.get(c, 0) for c in codes]
        return sum(vals) / len(vals) if vals else 0.0

    assert avg_units("R_HOT") > avg_units("R_NORMAL") > avg_units("R_SLOW")
    assert avg_units("R_STOCKOUT") > 0

    # 库存叙事：R_STOCKOUT 低可用、R_SLOW 高可用
    inv = {int(r["sku_id"]): int(r["available_qty"]) for r in tx["data"]["inventory"]}
    stockout = [inv[int(s["id"])] for s in tx["data"]["product_skus"]
                if role_of.get(s["sku_code"]) == "R_STOCKOUT"]
    slow = [inv[int(s["id"])] for s in tx["data"]["product_skus"]
            if role_of.get(s["sku_code"]) == "R_SLOW"]
    assert max(stockout) <= 3
    assert min(slow) >= 100


def test_conflict_order(tx):
    co = [o for o in tx["data"]["orders"] if "CS0807" in o["order_no"]]
    assert len(co) == 1
    o = co[0]
    assert o["status"] == "COMPLETED"
    signed = datetime.fromisoformat(o["signed_at"]).date()
    assert (AS_OF - signed).days == 10

    sku_id_to_code = {int(s["id"]): s["sku_code"] for s in tx["data"]["product_skus"]}
    item = next(it for it in tx["data"]["order_items"] if it["order_id"] == o["id"])
    assert sku_id_to_code[int(item["sku_id"])] == "SKU_01_CONFLICT_01"


def test_inventory_nonnegative_and_fk(tx):
    for r in tx["data"]["inventory"]:
        assert int(r["available_qty"]) >= 0
        assert int(r["reserved_qty"]) >= 0
    # inventory 的 sku_id 必须存在
    sku_ids = {int(s["id"]) for s in tx["data"]["product_skus"]}
    for r in tx["data"]["inventory"]:
        assert int(r["sku_id"]) in sku_ids

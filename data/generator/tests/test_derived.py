"""P4 / S3.3 派生事实门禁测试：5 表 / quantity≤购买 / 反馈≥送达 / 价格史现价一致+as_of 前 / R_PRICE_DROP 近 7-14 天。"""
import csv
from datetime import date, datetime
from pathlib import Path

import pytest

from data.generator.config import load_config
from data.generator.derived import DERIVED_TABLES
from data.generator.generate import generate

AS_OF = date(2026, 9, 17)
VALID_RETURN = {"APPROVED", "PROCESSING", "COMPLETED"}


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture()
def dv(tmp_path):
    cfg = load_config("dev")
    generate(cfg, output_root=tmp_path)
    canonical = tmp_path / "dev" / "canonical"
    data = {t: _read_csv(canonical / f"{t}.csv") for t in DERIVED_TABLES}
    data["order_items"] = _read_csv(canonical / "order_items.csv")
    data["orders"] = _read_csv(canonical / "orders.csv")
    data["product_skus"] = _read_csv(canonical / "product_skus.csv")
    data["sku_roles"] = _read_csv(tmp_path / "dev" / "sku_roles.csv")
    return {"canonical": canonical, "data": data}


def test_derived_tables_created(dv):
    for t in DERIVED_TABLES:
        assert (dv["canonical"] / f"{t}.csv").exists()
    assert len(dv["data"]["after_sales_requests"]) > 0
    assert len(dv["data"]["customer_feedback"]) > 0
    assert len(dv["data"]["price_history"]) > 0


def test_after_sales_quantity_le_order(dv):
    item_qty = {int(it["id"]): int(it["quantity"]) for it in dv["data"]["order_items"]}
    for r in dv["data"]["after_sales_requests"]:
        assert r["type"] == "RETURN"
        assert int(r["quantity"]) <= item_qty[int(r["order_item_id"])]
        # 有效退货集内状态合法
        assert r["status"] in VALID_RETURN | {"REJECTED", "CANCELLED", "PENDING"}
    # 有有效退货（支撑退货率）
    assert any(r["status"] in VALID_RETURN for r in dv["data"]["after_sales_requests"])


def test_after_sales_and_feedback_after_delivery(dv):
    order_delivered = {int(o["id"]): o["delivered_at"] for o in dv["data"]["orders"]}
    for r in dv["data"]["after_sales_requests"]:
        created = datetime.fromisoformat(r["created_at"])
        delivered = datetime.fromisoformat(order_delivered[int(r["order_id"])])
        assert created >= delivered
    for f in dv["data"]["customer_feedback"]:
        created = datetime.fromisoformat(f["created_at"])
        delivered = datetime.fromisoformat(order_delivered[int(f["order_id"])])
        assert created >= delivered


def test_price_history_consistency(dv):
    sku_price = {int(s["id"]): float(s["selling_price"]) for s in dv["data"]["product_skus"]}
    sku_ids = set(sku_price)
    for r in dv["data"]["price_history"]:
        sid = int(r["sku_id"])
        assert sid in sku_ids
        assert abs(float(r["new_price"]) - sku_price[sid]) < 1e-6   # 最新价 = 现价
        assert float(r["old_price"]) > float(r["new_price"])
        assert datetime.fromisoformat(r["effective_at"]).date() < AS_OF


def test_price_drop_role_has_recent_history(dv):
    role_of = {r["sku_code"]: r["role_id"] for r in dv["data"]["sku_roles"]}
    sku_code_by_id = {int(s["id"]): s["sku_code"] for s in dv["data"]["product_skus"]}
    # 找一个 R_PRICE_DROP SKU，其价格史 effective_at 在 as_of 前 7-14 天
    target = next(c for c, r in role_of.items() if r == "R_PRICE_DROP")
    sid = next(sid for sid, code in sku_code_by_id.items() if code == target)
    recs = [r for r in dv["data"]["price_history"] if int(r["sku_id"]) == sid]
    assert recs
    days = (AS_OF - datetime.fromisoformat(recs[0]["effective_at"]).date()).days
    assert 7 <= days <= 14


def test_campaigns_link_promo_products(dv):
    role_of = {r["sku_code"]: r["role_id"] for r in dv["data"]["sku_roles"]}
    skus = dv["data"]["product_skus"]
    promo_pids = {int(s["product_id"]) for s in skus
                  if role_of.get(s["sku_code"], "") in ("R_PRICE_DROP", "R_ANOMALY_DROP")}
    if not dv["data"]["campaigns"]:
        return
    cp_pids = {int(r["product_id"]) for r in dv["data"]["campaign_products"]}
    assert cp_pids <= promo_pids
    assert cp_pids


def test_no_service_tickets_or_audit(dv):
    assert not (dv["canonical"] / "service_tickets.csv").exists()
    assert not (dv["canonical"] / "audit_logs.csv").exists()

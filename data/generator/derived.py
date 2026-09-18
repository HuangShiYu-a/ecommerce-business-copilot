"""S3.3 派生事实生成（P4）。

AfterSales（有效退货集、quantity≤购买、≥送达）→ CustomerFeedback（≥送达、关联商品）
→ PriceHistory（仅 SKU、最新 new_price=现价、effective_at 在 as_of 前）
→ Campaigns/CampaignProducts（少量，挂 R_PRICE_DROP / R_ANOMALY_DROP）。

不预置 service_tickets / audit_logs（Action 运行时产物，S3.4 前补）。
读取 master + transactions 输出；写出 canonical 表。
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .config import GeneratorConfig
from .master import _write_csv
from .transactions import _read_csv

DERIVED_TABLES = [
    "after_sales_requests",
    "customer_feedback",
    "price_history",
    "campaigns",
    "campaign_products",
]

RETURN_REASONS = ["七日无理由", "质量问题", "不想要", "尺码不符", "错发"]
RETURN_STATUS = ["COMPLETED", "APPROVED", "PROCESSING", "REJECTED", "CANCELLED", "PENDING"]
VALID_RETURN = {"APPROVED", "PROCESSING", "COMPLETED"}
RETURN_STATUS_WEIGHTS = [55, 20, 10, 7, 5, 3]

POSITIVE_TEXT = ["商品很好", "物流快", "包装完好", "值得回购"]
NEGATIVE_TEXT = ["质量一般", "物流太慢", "和描述不符", "包装破损"]
NEUTRAL_TEXT = ["还行", "中规中矩"]


def generate_derived(cfg: GeneratorConfig, canonical_dir: Path, output_root: Path) -> list[dict]:
    rng = random.Random(cfg.dataset.seed)
    as_of = date.fromisoformat(cfg.dataset.as_of_date)
    as_of_dt = datetime.combine(as_of, time(0, 0))

    orders = _read_csv(canonical_dir / "orders.csv")
    order_items = _read_csv(canonical_dir / "order_items.csv")
    skus = _read_csv(canonical_dir / "product_skus.csv")
    staff = _read_csv(canonical_dir / "staff_users.csv")
    products = _read_csv(canonical_dir / "products.csv")
    sku_roles = _read_csv(output_root / cfg.profile.name / "sku_roles.csv")

    role_of = {r["sku_code"]: r["role_id"] for r in sku_roles}
    sku_by_id = {int(s["id"]): s for s in skus}
    item_by_order: dict[int, list[dict]] = {}
    for it in order_items:
        item_by_order.setdefault(int(it["order_id"]), []).append(it)

    after_sales = _gen_after_sales(orders, item_by_order, sku_by_id, role_of, staff, as_of_dt, rng)
    feedback = _gen_feedback(orders, item_by_order, sku_by_id, role_of, as_of_dt, rng)
    price_history = _gen_price_history(skus, role_of, as_of_dt, rng)
    campaigns, campaign_products = _gen_campaigns(skus, products, role_of, as_of_dt, rng)

    specs = {
        "after_sales_requests": (
            ["id", "store_id", "request_no", "order_id", "order_item_id", "customer_id",
             "type", "quantity", "reason", "description", "status", "idempotency_key",
             "requested_by", "approver_id", "approved_at", "created_at", "updated_at"],
            after_sales,
        ),
        "customer_feedback": (
            ["id", "store_id", "customer_id", "order_id", "product_id", "type", "category",
             "sentiment", "rating", "content", "created_at"],
            feedback,
        ),
        "price_history": (
            ["id", "store_id", "sku_id", "old_price", "new_price", "change_reason",
             "effective_at", "created_at"],
            price_history,
        ),
        "campaigns": (
            ["id", "store_id", "campaign_code", "name", "type", "status",
             "start_time", "end_time", "budget", "description", "created_at"],
            campaigns,
        ),
        "campaign_products": (
            ["id", "campaign_id", "product_id", "discount_rate", "promotion_price", "created_at"],
            campaign_products,
        ),
    }

    tables = []
    for name in DERIVED_TABLES:
        headers, rows = specs[name]
        _write_csv(canonical_dir / f"{name}.csv", headers, rows)
        tables.append({"table": name, "rows": len(rows)})
    return tables


def _gen_after_sales(orders, item_by_order, sku_by_id, role_of, staff, as_of_dt, rng) -> list[dict]:
    cs_by_store, appr_by_store = {}, {}
    for s in staff:
        store = int(s["store_id"])
        if s["role"] == "customer_service":
            cs_by_store.setdefault(store, s)
        if "APPR" in s["username"]:
            appr_by_store.setdefault(store, s)

    rows = []
    for o in orders:
        if o["status"] != "COMPLETED" or "CS0807" in o["order_no"]:
            continue
        items = item_by_order.get(int(o["id"]), [])
        if not items:
            continue
        it = items[0]
        sku = sku_by_id[int(it["sku_id"])]
        role = role_of.get(sku["sku_code"], "R_NORMAL")
        prob = 0.4 if role == "R_RETURN_HIGH" else (0.15 if role == "R_HEALTH_FULL" else 0.04)
        if rng.random() >= prob:
            continue

        store_id = int(o["store_id"])
        delivered = datetime.fromisoformat(o["delivered_at"])
        qty = rng.randint(1, int(it["quantity"]))          # ≤ 原行可退数量
        status = rng.choices(RETURN_STATUS, weights=RETURN_STATUS_WEIGHTS)[0]
        created = delivered + timedelta(days=rng.randint(1, 5))
        if created > as_of_dt:
            created = as_of_dt - timedelta(hours=1)
        if created < delivered:
            created = delivered                    # delivered 已非常接近 as_of
        approved_at = created + timedelta(hours=rng.randint(1, 48)) if status in VALID_RETURN else ""
        created_s = created.isoformat(timespec="seconds")
        rows.append({
            "id": len(rows) + 1, "store_id": store_id,
            "request_no": f"ASR{store_id:02d}{len(rows) + 1:07d}",
            "order_id": int(o["id"]), "order_item_id": int(it["id"]),
            "customer_id": int(o["customer_id"]), "type": "RETURN", "quantity": qty,
            "reason": rng.choice(RETURN_REASONS), "description": "",
            "status": status,
            "idempotency_key": f"ASR_{store_id:02d}_{len(rows) + 1:06d}",
            "requested_by": int(cs_by_store.get(store_id, staff[0])["id"]),
            "approver_id": int(appr_by_store.get(store_id, staff[0])["id"]) if approved_at else "",
            "approved_at": approved_at.isoformat(timespec="seconds") if approved_at else "",
            "created_at": created_s, "updated_at": created_s,
        })
    return rows


def _gen_feedback(orders, item_by_order, sku_by_id, role_of, as_of_dt, rng) -> list[dict]:
    rows = []
    for o in orders:
        if o["status"] != "COMPLETED" or "CS0807" in o["order_no"]:
            continue
        items = item_by_order.get(int(o["id"]), [])
        if not items:
            continue
        it = items[0]
        sku = sku_by_id[int(it["sku_id"])]
        role = role_of.get(sku["sku_code"], "R_NORMAL")
        prob = 0.5 if role == "R_RETURN_HIGH" else (0.3 if role == "R_HEALTH_FULL" else 0.15)
        if rng.random() >= prob:
            continue

        delivered = datetime.fromisoformat(o["delivered_at"])
        created = delivered + timedelta(days=rng.randint(1, 4))
        if created > as_of_dt:
            created = as_of_dt - timedelta(hours=1)
        if created < delivered:
            created = delivered

        r = rng.random()
        if role == "R_RETURN_HIGH":
            sentiment = "NEGATIVE" if r < 0.5 else ("NEUTRAL" if r < 0.7 else "POSITIVE")
        else:
            sentiment = "POSITIVE" if r < 0.6 else ("NEUTRAL" if r < 0.85 else "NEGATIVE")
        ftype = "COMPLAINT" if (sentiment == "NEGATIVE" and role == "R_RETURN_HIGH") else "REVIEW"
        rating = ""
        if ftype == "REVIEW":
            rating = 5 if sentiment == "POSITIVE" else (3 if sentiment == "NEUTRAL" else 1)
        content = rng.choice(POSITIVE_TEXT if sentiment == "POSITIVE"
                             else (NEGATIVE_TEXT if sentiment == "NEGATIVE" else NEUTRAL_TEXT))
        category = ("LOGISTICS" if sentiment == "NEGATIVE" and rng.random() < 0.3
                    else "PRODUCT_QUALITY")
        rows.append({
            "id": len(rows) + 1, "store_id": int(o["store_id"]),
            "customer_id": int(o["customer_id"]), "order_id": int(o["id"]),
            "product_id": int(it["product_id"]),
            "type": ftype, "category": category, "sentiment": sentiment,
            "rating": rating, "content": content,
            "created_at": created.isoformat(timespec="seconds"),
        })
    return rows


def _gen_price_history(skus, role_of, as_of_dt, rng) -> list[dict]:
    rows = []
    for s in skus:
        role = role_of.get(s["sku_code"], "R_NORMAL")
        selling = float(s["selling_price"])
        if role in ("R_PRICE_DROP", "R_ANOMALY_DROP"):
            old = round(selling * rng.uniform(1.15, 1.3), 2)
            days = rng.randint(7, 14)
            reason = "促销调价"
        else:
            if rng.random() >= 0.15:
                continue
            old = round(selling * rng.uniform(1.05, 1.25), 2)
            days = rng.randint(10, 60)
            reason = "常规调价"
        effective = as_of_dt - timedelta(days=days)
        effective_s = effective.isoformat(timespec="seconds")
        rows.append({
            "id": len(rows) + 1, "store_id": int(s["store_id"]), "sku_id": int(s["id"]),
            "old_price": old, "new_price": selling, "change_reason": reason,
            "effective_at": effective_s, "created_at": effective_s,
        })
    return rows


def _gen_campaigns(skus, products, role_of, as_of_dt, rng) -> tuple[list[dict], list[dict]]:
    prod_by_id = {int(p["id"]): p for p in products}
    promo = []
    for s in skus:
        if role_of.get(s["sku_code"], "") in ("R_PRICE_DROP", "R_ANOMALY_DROP"):
            pid = int(s["product_id"])
            if pid not in promo:
                promo.append(pid)
    if not promo:
        return [], []

    campaigns, cp_rows = [], []
    for i in range(min(3, len(promo))):
        pid = promo[i]
        store_id = int(prod_by_id[pid]["store_id"])
        cid = len(campaigns) + 1
        start = as_of_dt - timedelta(days=rng.randint(15, 25))
        end = as_of_dt - timedelta(days=rng.randint(3, 8))
        start_s = start.isoformat(timespec="seconds")
        campaigns.append({
            "id": cid, "store_id": store_id,
            "campaign_code": f"CMP_{store_id:02d}_{cid:02d}",
            "name": f"限时促销{cid}", "type": "PRICE_PROMOTION", "status": "ENDED",
            "start_time": start_s, "end_time": end.isoformat(timespec="seconds"),
            "budget": rng.randint(5000, 20000), "description": "",
            "created_at": start_s,
        })
        rate = round(rng.uniform(0.75, 0.9), 4)
        skus_of_prod = [s for s in skus if int(s["product_id"]) == pid]
        base = float(skus_of_prod[0]["selling_price"]) if skus_of_prod else 0.0
        cp_rows.append({
            "id": len(cp_rows) + 1, "campaign_id": cid, "product_id": pid,
            "discount_rate": rate, "promotion_price": round(base * rate, 2),
            "created_at": start_s,
        })
    return campaigns, cp_rows

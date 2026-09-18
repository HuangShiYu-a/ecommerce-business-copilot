"""S3.2 交易主链生成（P3）。

Customer/Address → Order/Item（90 天 §12A、角色驱动销量、时间序一致）
→ Shipment/Event（CS-06 三构造：NORMAL / ANOMALY / UNDETERMINED）
→ Inventory 快照（策略 B：按角色叙事反推，不生成 Movement）。

读取 master 输出（canonical CSVs + sku_roles.csv）；写出 7 张 canonical 交易表。
DB 列对齐 Database §13；时间戳用 Asia/Shanghai 逻辑的本地 ISO（无 tz），导入时解释。
"""
from __future__ import annotations

import csv
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .config import GeneratorConfig, load_yaml
from .master import RULES_DIR, _write_csv

TRANS_TABLES = [
    "customers",
    "customer_addresses",
    "orders",
    "order_items",
    "shipments",
    "shipment_events",
    "inventory",
]

CARRIERS = ["顺丰", "中通", "圆通", "韵达"]
NAME_1 = ["林", "陈", "李", "张", "王", "黄", "周", "刘", "杨", "吴"]
NAME_2 = ["一", "二", "三", "五", "六", "七", "八", "九"]

# 角色 → 可用库存区间（叙事：销量高+库存低 → R_STOCKOUT 低；R_SLOW/R_OVERSTOCK 高）
INV_CLASS = {
    "R_STOCKOUT": (0, 3),
    "R_NORMAL": (20, 80),
    "R_SLOW": (100, 300),
    "R_SLOW_HEALTHY": (10, 30),
    "R_OVERSTOCK": (400, 1000),
    "R_RETURN_HIGH": (30, 90),
    "R_PRICE_DROP": (40, 120),
    "R_ANOMALY_DROP": (40, 120),
    "R_SPARSE_SALES": (10, 50),
    "R_HEALTH_FULL": (40, 120),
    "R_HEALTH_CORE_MISS": (40, 120),
    "R_BASELINE": (40, 120),
    "R_HOT": (80, 200),
}

EVENT_NORMAL = ["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _ts(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def generate_transactions(cfg: GeneratorConfig, canonical_dir: Path, output_root: Path) -> list[dict]:
    """读取 master 输出，生成交易数据并写 canonical CSV；返回表清单。"""
    rng = random.Random(cfg.dataset.seed)
    params = cfg.profile.params

    stores = _read_csv(canonical_dir / "stores.csv")
    skus = _read_csv(canonical_dir / "product_skus.csv")
    warehouses = _read_csv(canonical_dir / "warehouses.csv")
    sku_roles = _read_csv(output_root / cfg.profile.name / "sku_roles.csv")
    roles_def = load_yaml(RULES_DIR / "roles.yaml")["roles"]

    as_of = date.fromisoformat(cfg.dataset.as_of_date)
    as_of_dt = datetime.combine(as_of, time(0, 0))

    role_of = {r["sku_code"]: r["role_id"] for r in sku_roles}
    conflict_codes = {r["sku_code"] for r in sku_roles if r["conflict_test"] == "true"}

    n_customers = params.get("customers_per_store") or 100
    target_orders = params.get("orders_total_approx") or 2500

    customers, addresses = _gen_customers(stores, n_customers, rng)
    orders, order_items = _gen_orders(
        stores, customers, addresses, skus, role_of, roles_def,
        target_orders, as_of_dt, conflict_codes, rng,
    )
    shipments, events = _gen_shipments(orders, rng)
    inventory = _gen_inventory(stores, skus, warehouses, role_of, roles_def, as_of, rng)

    specs = {
        "customers": (
            ["id", "store_id", "customer_code", "name", "phone", "email", "level", "status"],
            customers,
        ),
        "customer_addresses": (
            ["id", "store_id", "customer_id", "contact_name", "phone", "province", "city",
             "district", "detail_address", "is_default"],
            addresses,
        ),
        "orders": (
            ["id", "store_id", "order_no", "customer_id", "status", "payment_status",
             "shipping_status", "total_amount", "paid_amount",
             "shipping_contact_name", "shipping_phone", "shipping_province",
             "shipping_city", "shipping_district", "shipping_detail",
             "ordered_at", "paid_at", "promised_ship_at", "promised_delivery_at",
             "shipped_at", "delivered_at", "signed_at", "completed_at", "cancelled_at"],
            orders,
        ),
        "order_items": (
            ["id", "store_id", "order_id", "product_id", "sku_id", "quantity",
             "unit_price", "discount_amount", "line_amount"],
            order_items,
        ),
        "shipments": (
            ["id", "store_id", "order_id", "tracking_no", "carrier", "status",
             "shipped_at", "estimated_delivery_at"],
            shipments,
        ),
        "shipment_events": (
            ["id", "shipment_id", "event_type", "description", "location",
             "event_time", "created_at"],
            events,
        ),
        "inventory": (
            ["id", "store_id", "warehouse_id", "sku_id", "available_qty",
             "reserved_qty", "safety_stock", "reorder_point", "updated_at"],
            inventory,
        ),
    }

    tables = []
    for name in TRANS_TABLES:
        headers, rows = specs[name]
        _write_csv(canonical_dir / f"{name}.csv", headers, rows)
        tables.append({"table": name, "rows": len(rows)})
    return tables


def _gen_customers(stores: list[dict], n_per_store: int, rng) -> tuple[list[dict], list[dict]]:
    customers, addresses = [], []
    for st in stores:
        sid = int(st["id"])
        for i in range(n_per_store):
            cid = len(customers) + 1
            level = "VIP" if rng.random() < 0.1 else "NORMAL"
            customers.append({
                "id": cid, "store_id": sid, "customer_code": f"CST_{sid:02d}_{i + 1:03d}",
                "name": f"{rng.choice(NAME_1)}{rng.choice(NAME_2)}",
                "phone": f"138{rng.randint(10000000, 99999999)}",
                "email": f"user{cid}@example.com", "level": level, "status": "ACTIVE",
            })
            addresses.append({
                "id": len(addresses) + 1, "store_id": sid, "customer_id": cid,
                "contact_name": customers[-1]["name"], "phone": customers[-1]["phone"],
                "province": "浙江省", "city": "杭州市", "district": "西湖区",
                "detail_address": f"模拟路{i + 1}号", "is_default": "true",
            })
    return customers, addresses


def _rand_between(rng, lo: datetime, hi: datetime) -> datetime:
    """[lo, hi] 均匀随机时间点。"""
    if hi <= lo:
        return lo
    return lo + timedelta(seconds=rng.randint(0, int((hi - lo).total_seconds())))


def _gen_orders(stores, customers, addresses, skus, role_of, roles_def,
                target, as_of_dt, conflict_codes, rng):
    addr_by_customer = {int(a["customer_id"]): a for a in addresses}
    cust_by_store: dict[int, list[dict]] = {}
    for c in customers:
        cust_by_store.setdefault(int(c["store_id"]), []).append(c)

    # 每 SKU 订单预算（按角色销量权重；target 为有效销售单量目标）
    weighted = []
    for s in skus:
        role = role_of.get(s["sku_code"], "R_NORMAL")
        sales = roles_def[role]["sales"]
        w = (sales["daily_units_min"] + sales["daily_units_max"]) / 2.0 * sales["window_days"]
        if role == "R_SPARSE_SALES":
            w = 0.05
        weighted.append((s, role, w))
    total_w = sum(w for _, _, w in weighted)

    orders: list[dict] = []
    order_items: list[dict] = []
    oid = oiid = seq = 0

    def emit(store_id, customer, sku, qty, ordered_dt, rng,
             construction=None, forced_status=None, forced_signed_at=None, special_no=None):
        nonlocal oid, oiid, seq
        oid += 1
        oiid += 1
        seq += 1
        order_no = special_no or f"ORD_{store_id:02d}_{seq:06d}"
        age = (as_of_dt - ordered_dt).total_seconds() / 86400

        status = forced_status
        if status is None:
            if age <= 2:
                status = "PROCESSING"
            elif age <= 5:
                status = "SHIPPED"
            else:
                status = "COMPLETED"

        paid = ordered_dt + timedelta(minutes=rng.randint(10, 120))
        p_ship = ordered_dt + timedelta(days=rng.randint(1, 2))
        shipped = (paid + timedelta(hours=rng.randint(12, 48))
                   if status in ("SHIPPED", "COMPLETED") else None)
        cancelled_at = None

        if status == "CANCELLED":
            cancelled_at = paid + timedelta(days=rng.randint(1, 3))
            p_deliver = delivered = signed = completed = None
            ship_status, pay_status = "", ("REFUNDED" if rng.random() < 0.5 else "PAID")
        elif status == "PENDING_PAYMENT":
            paid = p_ship = shipped = p_deliver = delivered = signed = completed = None
            ship_status, pay_status = "UNSHIPPED", "UNPAID"
        else:
            if status in ("SHIPPED", "COMPLETED"):
                if construction == "delay":
                    p_deliver = shipped + timedelta(days=1)
                    delivered = (shipped + timedelta(days=rng.randint(4, 6))
                                 if status == "COMPLETED" else None)
                elif construction == "missing_promised":
                    p_deliver = None
                    delivered = (shipped + timedelta(days=rng.randint(1, 3))
                                 if status == "COMPLETED" else None)
                else:
                    p_deliver = shipped + timedelta(days=rng.randint(1, 3))
                    delivered = (shipped + timedelta(days=rng.randint(1, 3))
                                 if status == "COMPLETED" else None)
                signed = (delivered + timedelta(hours=rng.randint(0, 20))
                          if delivered is not None else None)
                completed = signed
                if forced_signed_at is not None:
                    signed = forced_signed_at
                    delivered = forced_signed_at
                    completed = signed
                elif signed is not None and signed > as_of_dt:
                    # 签收不得晚于分析日：整链前移（保持 delivered ≤ signed）
                    overshoot = signed - as_of_dt
                    delivered -= overshoot
                    signed = as_of_dt
                    completed = signed
                # 少量「已送达未签收」：支撑 SC-CS08-003（缺签收 → undetermined）；排除 conflict 订单
                if (status == "COMPLETED" and forced_signed_at is None
                        and rng.random() < 0.03):
                    signed = None
                    completed = None
                ship_status = "DELIVERED" if status == "COMPLETED" else "SHIPPED"
                pay_status = "PAID"
            else:  # PROCESSING：已支付、未发货
                p_deliver = delivered = signed = completed = None
                ship_status, pay_status = "UNSHIPPED", "PAID"

        addr = addr_by_customer[int(customer["id"])]
        unit_price = float(sku["selling_price"])
        line_amount = round(qty * unit_price, 2)

        order_row = {
            "id": oid, "store_id": store_id, "order_no": order_no, "customer_id": int(customer["id"]),
            "status": status, "payment_status": pay_status, "shipping_status": ship_status,
            "total_amount": line_amount,
            "paid_amount": line_amount if pay_status == "PAID" else "",
            "shipping_contact_name": addr["contact_name"], "shipping_phone": addr["phone"],
            "shipping_province": addr["province"], "shipping_city": addr["city"],
            "shipping_district": addr["district"], "shipping_detail": addr["detail_address"],
            "ordered_at": _ts(ordered_dt),
            "paid_at": _ts(paid) if paid else "",
            "promised_ship_at": _ts(p_ship) if p_ship else "",
            "promised_delivery_at": _ts(p_deliver) if p_deliver else "",
            "shipped_at": _ts(shipped) if shipped else "",
            "delivered_at": _ts(delivered) if delivered else "",
            "signed_at": _ts(signed) if signed else "",
            "completed_at": _ts(completed) if completed else "",
            "cancelled_at": _ts(cancelled_at) if cancelled_at else "",
            "construction": construction or "",
        }
        item_row = {
            "id": oiid, "store_id": store_id, "order_id": oid,
            "product_id": int(sku["product_id"]), "sku_id": int(sku["id"]),
            "quantity": qty, "unit_price": unit_price,
            "discount_amount": 0, "line_amount": line_amount,
        }
        orders.append(order_row)
        order_items.append(item_row)

    # 有效销售单（角色权重分配；按 pattern 分布下单日期）
    for s, role, w in weighted:
        n = max(1, int(round(target * w / total_w)))
        if role == "R_SPARSE_SALES":
            n = rng.randint(2, 4)
        sales = roles_def[role]["sales"]
        window = sales["window_days"]
        pattern = sales.get("pattern", "steady")
        start = as_of_dt - timedelta(days=window)
        latest = as_of_dt - timedelta(days=1)

        if pattern == "spike_then_drop":
            # R_ANOMALY_DROP：前段正常、近 7 天骤降（SC-OP08-001 ANOMALY；wow 对比需近 7 天明显低于前 7 天）
            cut = as_of_dt - timedelta(days=7)
            n_early = int(n * 0.88)
            dates = [_rand_between(rng, start, cut) for _ in range(n_early)]
            dates += [_rand_between(rng, cut, latest) for _ in range(n - n_early)]
        elif pattern == "drop_after":
            # R_PRICE_DROP：降价（前 7–14 天）后近 7 天销量明显下降（SC-OP08-004 ANOMALY + 价格证据）。
            # 切点必须在第 7 天（WoW 对比：近 7 天 vs 前 7 天），且分离度要强（92/8）以抗随机方差
            cut = as_of_dt - timedelta(days=7)
            n_early = int(n * 0.92)
            dates = [_rand_between(rng, start, cut) for _ in range(n_early)]
            dates += [_rand_between(rng, cut, latest) for _ in range(n - n_early)]
        else:
            dates = [_rand_between(rng, start, latest) for _ in range(n)]

        for ordered in dates:
            qty = rng.randint(1, 2)
            roll = rng.random()
            construction = "delay" if roll < 0.08 else ("missing_promised" if roll < 0.11 else None)
            store_id = int(s["store_id"])
            customer = rng.choice(cust_by_store[store_id])
            emit(store_id, customer, s, qty, ordered, rng, construction=construction)

    # 无效单：CANCELLED（5%）与 PENDING_PAYMENT（少量）
    for _ in range(int(target * 0.05)):
        s, role, w = weighted[rng.randrange(len(weighted))]
        store_id = int(s["store_id"])
        ordered = as_of_dt - timedelta(days=rng.randint(2, 60))
        emit(store_id, rng.choice(cust_by_store[store_id]), s, rng.randint(1, 2), ordered, rng,
             forced_status="CANCELLED")
    for _ in range(10):
        s, role, w = weighted[rng.randrange(len(weighted))]
        store_id = int(s["store_id"])
        ordered = as_of_dt - timedelta(minutes=rng.randint(30, 600))
        emit(store_id, rng.choice(cust_by_store[store_id]), s, rng.randint(1, 2), ordered, rng,
             forced_status="PENDING_PAYMENT")

    # SC-CS08-007 conflict 订单：apparel conflict 产品，signed_at = as_of − 10 天
    for s in skus:
        if s["sku_code"] in conflict_codes:
            csku = s
            break
    else:
        csku = None
    if csku is not None:
        store_id = int(csku["store_id"])
        customer = rng.choice(cust_by_store[store_id])
        emit(store_id, customer, csku, 1, as_of_dt - timedelta(days=12), rng,
             forced_status="COMPLETED", forced_signed_at=as_of_dt - timedelta(days=10),
             special_no=f"ORD_{store_id:02d}_CS0807_001")

    return orders, order_items


def _gen_shipments(orders: list[dict], rng) -> tuple[list[dict], list[dict]]:
    shipments, events = [], []
    for o in orders:
        if o["status"] not in ("SHIPPED", "COMPLETED"):
            continue
        sid = int(o["id"])
        ship_id = len(shipments) + 1
        shipped_at = datetime.fromisoformat(o["shipped_at"])
        construction = o.get("construction", "")
        status = o["status"]
        ship_status = "DELIVERED" if status == "COMPLETED" else "IN_TRANSIT"

        if construction == "missing_promised":
            seq_events = [("PICKED_UP", shipped_at), ("IN_TRANSIT", shipped_at + timedelta(hours=6))]
            if status == "COMPLETED":
                seq_events.append(("DELIVERED", datetime.fromisoformat(o["delivered_at"])))
        elif construction == "delay":
            seq_events = [
                ("PICKED_UP", shipped_at),
                ("IN_TRANSIT", shipped_at + timedelta(hours=6)),
                ("STALLED", shipped_at + timedelta(days=1)),
            ]
            if status == "COMPLETED":
                seq_events.append(("DELIVERED", datetime.fromisoformat(o["delivered_at"])))
        else:
            seq_events = [
                ("PICKED_UP", shipped_at),
                ("IN_TRANSIT", shipped_at + timedelta(hours=6)),
                ("OUT_FOR_DELIVERY", shipped_at + timedelta(days=1)),
            ]
            if status == "COMPLETED":
                seq_events.append(("DELIVERED", datetime.fromisoformat(o["delivered_at"])))

        shipments.append({
            "id": ship_id, "store_id": int(o["store_id"]), "order_id": sid,
            "tracking_no": f"TRK_{int(o['store_id']):02d}{ship_id:07d}",
            "carrier": rng.choice(CARRIERS), "status": ship_status,
            "shipped_at": _ts(shipped_at),
            "estimated_delivery_at": _ts(shipped_at + timedelta(days=rng.randint(1, 3))),
        })
        for etype, etime in seq_events:
            events.append({
                "id": len(events) + 1, "shipment_id": ship_id, "event_type": etype,
                "description": etype, "location": rng.choice(["杭州", "上海", "广州", "北京"]),
                "event_time": _ts(etime), "created_at": _ts(etime),
            })
    return shipments, events


def _gen_inventory(stores, skus, warehouses, role_of, roles_def, as_of, rng) -> list[dict]:
    wh_by_store = {}
    for w in warehouses:
        wh_by_store.setdefault(int(w["store_id"]), w)
    rows = []
    for s in skus:
        store_id = int(s["store_id"])
        role = role_of.get(s["sku_code"], "R_NORMAL")
        lo, hi = INV_CLASS.get(role, (20, 80))
        avail = rng.randint(lo, hi)
        safety = int(roles_def[role]["inventory"]["safety_stock"])
        rows.append({
            "id": len(rows) + 1, "store_id": store_id,
            "warehouse_id": int(wh_by_store[store_id]["id"]),
            "sku_id": int(s["id"]),
            "available_qty": avail, "reserved_qty": rng.randint(0, 5),
            "safety_stock": safety, "reorder_point": safety * 2,
            "updated_at": as_of.isoformat(),
        })
    return rows

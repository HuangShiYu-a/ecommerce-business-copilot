"""慢销候选筛选（T-A-04 mode=slow_moving，OP-03，WF-OP03 F.3）。

slow_moving = 低动销候选筛选视角，不是正式滞销风险等级。
阈值来自 StoreConfig（slow_moving.lookback_days / max_units），非 LLM。
候选 = 窗口内有效销量 ≤ max_units 的 SKU；可单 SKU 校验或类目扫描。
category 为类目名称片段（如「美妆」），匹配 product_categories.name。
"""
from __future__ import annotations

from ..db import query


def _config(conn, store_id: int, key: str, default):
    row = query(conn, "SELECT config_value FROM store_configs WHERE store_id=%s AND config_key=%s",
                (store_id, key))
    return row[0]["config_value"] if row else default


def slow_moving_candidates(conn, store_id: int, as_of: str,
                           category: str | None = None,
                           sku_code: str | None = None) -> dict:
    lookback = int(_config(conn, store_id, "inventory.slow_moving.lookback_days", 30) or 30)
    max_units = int(_config(conn, store_id, "inventory.slow_moving.max_units", 15) or 15)

    sql = """
        SELECT s.sku_code, COALESCE(SUM(oi.quantity),0) AS units,
               inv.available_qty
        FROM product_skus s
        LEFT JOIN products p ON p.id = s.product_id
        LEFT JOIN inventory inv ON inv.sku_id = s.id AND inv.store_id = s.store_id
        LEFT JOIN order_items oi ON oi.sku_id = s.id
        LEFT JOIN orders o ON o.id = oi.order_id
              AND o.store_id = s.store_id
              AND o.status IN ('PAID','PROCESSING','SHIPPED','COMPLETED')
              AND o.ordered_at >= (%s::date - make_interval(days => %s))
        WHERE s.store_id = %s
    """
    params: list = [as_of, lookback, store_id]
    if category:
        sql += (" AND p.category_id IN "
                "(SELECT id FROM product_categories WHERE store_id=%s AND name LIKE %s)")
        params += [store_id, f"%{category}%"]
    if sku_code:
        sql += " AND s.sku_code = %s"
        params.append(sku_code)
    sql += " GROUP BY s.sku_code, inv.available_qty"

    rows = query(conn, sql, tuple(params))
    candidates = [
        {"sku_code": r["sku_code"], "units": r["units"] or 0,
         "available_qty": r["available_qty"] or 0}
        for r in rows if (r["units"] or 0) <= max_units
    ]
    return {"candidates": candidates, "lookback_days": lookback, "max_units": max_units}

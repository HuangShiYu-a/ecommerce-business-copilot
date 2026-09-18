"""Inventory 计算（T-A-07 / T-R-01 共用，单一口径，禁止第二套公式）。

口径：
- 有效销售状态：PAID/PROCESSING/SHIPPED/COMPLETED（DB §12A）
- 分析时钟：as_of（S2 §0），非真实 now()
- avg_daily_sales = Σunits(窗口) / window_days（historical estimate）
- 补货触发：available <= safety_stock + avg×lead_time
- recommended_quantity = max(0, ceil(avg×(lead_time+horizon) + safety - available))
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from ..db import query_one

VALID_SALES = ("PAID", "PROCESSING", "SHIPPED", "COMPLETED")

# 有效销售点（不同订单数）下限：低于则视为「销量窗不足」（R_SPARSE_SALES 语义；
# 生成数据中稀疏≈3、正常≈10、爆款≈29，取 4 区分）
MIN_SALE_POINTS = 4


def resolve_sku(conn, store_id: int, sku_id: int | None = None, sku_code: str | None = None) -> dict | None:
    """store 域内解析 SKU（隔离）。"""
    if sku_id is not None:
        return query_one(conn, "SELECT * FROM product_skus WHERE id=%s AND store_id=%s", (sku_id, store_id))
    if sku_code:
        return query_one(conn, "SELECT * FROM product_skus WHERE sku_code=%s AND store_id=%s", (sku_code, store_id))
    return None


def config_value(conn, store_id: int, key: str):
    row = query_one(conn, "SELECT config_value FROM store_configs WHERE store_id=%s AND config_key=%s",
                    (store_id, key))
    return row["config_value"] if row else None  # jsonb 已注册为 Python 对象


def config_int(conn, store_id: int, key: str) -> int | None:
    v = config_value(conn, store_id, key)
    return int(v) if v is not None else None


def sales_summary(conn, sku_id: int, store_id: int, window_days: int, as_of: str) -> dict:
    """窗口内有效订单的 units 与销售点（不同订单数）计数（§12A 状态 + as_of 时钟）。"""
    row = query_one(conn, """
        SELECT COALESCE(SUM(oi.quantity), 0) AS units,
               COUNT(DISTINCT o.id) AS orders
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.sku_id = %s AND o.store_id = %s
          AND o.status IN %s
          AND o.ordered_at >= (%s::date - make_interval(days => %s))
    """, (sku_id, store_id, VALID_SALES, as_of, window_days))
    return {"units": row["units"] or 0, "orders": row["orders"] or 0}


def avg_daily_sales(conn, sku_id: int, store_id: int, window_days: int, as_of: str) -> float:
    """近 window_days 天有效订单 units / window_days（§12A 状态 + as_of 时钟）。"""
    return sales_summary(conn, sku_id, store_id, window_days, as_of)["units"] / window_days


def inventory_row(conn, sku_id: int, store_id: int) -> dict | None:
    return query_one(conn, """
        SELECT available_qty, safety_stock, reorder_point
        FROM inventory WHERE sku_id=%s AND store_id=%s""", (sku_id, store_id))


def restock_recommendation(conn, sku: dict, store_id: int, as_of: str,
                           horizon_days: int | None = None) -> dict:
    """返回补货建议或 {'undetermined': reason} / {'error': code}。"""
    inv = inventory_row(conn, sku["id"], store_id)
    if inv is None:
        return {"error": "NOT_FOUND"}

    lead_time = config_int(conn, store_id, "inventory.lead_time_days")
    if lead_time is None:
        return {"undetermined": "MISSING_LEAD_TIME_CONFIG"}

    horizon = horizon_days or (config_int(conn, store_id, "inventory.default_horizon_days") or 14)
    summary = sales_summary(conn, sku["id"], store_id, horizon, as_of)
    avg = summary["units"] / horizon
    if summary["orders"] < MIN_SALE_POINTS or avg <= 0:
        return {"undetermined": "MISSING_SALES_WINDOW"}

    available = inv["available_qty"]
    safety = inv["safety_stock"]
    need_restock = available <= safety + avg * lead_time
    target = avg * (lead_time + horizon) + safety
    recommended = max(0, math.ceil(target - available))
    days = available / avg
    return {
        "recommended_quantity": recommended,
        "avg_daily_sales_est": round(avg, 4),
        "days_until_stockout": round(days, 2),
        "estimated_stockout_date": (date.fromisoformat(as_of) + timedelta(days=days)).isoformat(),
        "need_restock": need_restock,
        "method": "historical_sales_estimate",
    }


def stockout_analysis(conn, sku: dict, store_id: int, as_of: str,
                      forecast_days: int | None = None) -> dict:
    """缺货风险单 SKU 分析（T-A-07）。"""
    inv = inventory_row(conn, sku["id"], store_id)
    if inv is None:
        return {"error": "NOT_FOUND"}
    horizon = forecast_days or (config_int(conn, store_id, "inventory.default_horizon_days") or 14)
    summary = sales_summary(conn, sku["id"], store_id, horizon, as_of)
    avg = summary["units"] / horizon
    if summary["orders"] < MIN_SALE_POINTS or avg <= 0:
        return {"undetermined": "MISSING_SALES_WINDOW"}
    available = inv["available_qty"]
    days = available / avg if avg > 0 else None
    return {
        "available_qty": available,
        "avg_daily_sales_est": round(avg, 4),
        "days_until_stockout": round(days, 2) if days is not None else None,
        "estimated_stockout_date": (date.fromisoformat(as_of) + timedelta(days=days)).isoformat()
        if days is not None else None,
        "forecast_days": horizon,
        "risk_level": "HIGH" if (days is not None and days <= horizon) else "NORMAL",
    }

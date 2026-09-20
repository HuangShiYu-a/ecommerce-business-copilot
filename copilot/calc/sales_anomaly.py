"""销售异常判定（T-A-06，OP-08，WF-OP08 E.3）。

baseline_policy 仅作策略标识；真实阈值从 StoreConfig 解析（禁止用户口头百分比覆盖）。
WoW 基线：近 7 天 vs 前 7 天销量；drop_ratio ≥ threshold → ANOMALY。
价格证据：price_history 近 7 天最低价 < 前 14 天最低价 → 降价证据。
"""
from __future__ import annotations

from ..db import query, query_one


def _sales_between(conn, sku_id: int, store_id: int, lo: str, hi: str) -> int:
    row = query_one(conn, """
        SELECT COALESCE(SUM(oi.quantity),0) AS units FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.sku_id=%s AND o.store_id=%s AND o.status IN ('PAID','PROCESSING','SHIPPED','COMPLETED')
          AND o.ordered_at >= %s::date AND o.ordered_at < %s::date""",
        (sku_id, store_id, lo, hi))
    return row["units"] or 0


def _price_drop_evidence(conn, sku_id: int, store_id: int, as_of: str) -> dict | None:
    rows = query(conn, """
        SELECT new_price, old_price FROM price_history
        WHERE sku_id=%s AND store_id=%s AND effective_at >= (%s::date - interval '14 days')
        ORDER BY effective_at DESC LIMIT 1""", (sku_id, store_id, as_of))
    if not rows:
        return None
    r = rows[0]
    return {"dropped": float(r["new_price"]) < float(r["old_price"])}


def sales_anomaly(conn, sku: dict, store_id: int, as_of: str,
                  baseline_policy: str | None = None) -> dict:
    threshold = None
    try:
        threshold = float(query_one(conn, """
            SELECT config_value FROM store_configs
            WHERE store_id=%s AND config_key='anomaly.sales_drop_threshold'""",
            (store_id,))["config_value"])
    except (TypeError, KeyError):
        threshold = None
    if threshold is None:
        return {"undetermined": "MISSING_ANOMALY_CONFIG"}

    import datetime
    as_d = datetime.date.fromisoformat(as_of)
    recent = _sales_between(conn, sku["id"], store_id,
                            (as_d - datetime.timedelta(days=7)).isoformat(), as_of)
    prev = _sales_between(conn, sku["id"], store_id,
                          (as_d - datetime.timedelta(days=14)).isoformat(),
                          (as_d - datetime.timedelta(days=7)).isoformat())
    drop = (1 - recent / prev) if prev > 0 else 0.0
    is_anomaly = drop >= threshold
    price_ev = _price_drop_evidence(conn, sku["id"], store_id, as_of)
    causes = []
    if is_anomaly:
        causes = ["价格调整后销量下滑"] if (price_ev and price_ev["dropped"]) else ["近 7 天销量骤降"]
    return {
        "is_anomaly": is_anomaly,
        "anomaly_basis": "wow_drop",
        "baseline_policy": baseline_policy or "store_default",
        "recent_7d_units": recent,
        "prev_7d_units": prev,
        "drop_ratio": round(drop, 4),
        "threshold": threshold,
        "evidence": [{"type": "wow_drop", "recent_7d": recent, "prev_7d": prev, "drop_ratio": round(drop, 4)}]
                   + ([{"type": "price_drop"}] if price_ev and price_ev["dropped"] else []),
        "possible_causes": causes,
    }

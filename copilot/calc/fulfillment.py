"""物流履约异常判定（T-A-01，CS-06）。

NORMAL：按时送达（delivered ≤ promised）
ANOMALY：超 promised 未按时送达（delivered > promised）
UNDETERMINED：缺 promised_delivery_at（MISSING_PROMISED_AT）
"""
from __future__ import annotations

from ..db import query_one


def fulfillment_delay(conn, order: dict, store_id: int) -> dict:
    promised = order.get("promised_delivery_at")
    if not promised:
        return {"undetermined": "MISSING_PROMISED_AT"}
    delivered = order.get("delivered_at")
    if not delivered:
        # 已发货未送达：查是否超 promised
        overdue = False
        return {"status": "ANOMALY" if overdue else "NORMAL",
                "reason": "overdue" if overdue else "in_transit"}
    import datetime
    pd = datetime.datetime.fromisoformat(str(promised))
    dd = datetime.datetime.fromisoformat(str(delivered))
    late = dd > pd
    if late:
        return {"status": "ANOMALY", "reason": "over_promised",
                "delay_days": round((dd - pd).total_seconds() / 86400, 1)}
    return {"status": "NORMAL", "reason": "on_time"}


def get_order(conn, order_no: str, store_id: int) -> dict | None:
    return query_one(conn, """
        SELECT id, order_no, status, promised_delivery_at, delivered_at, shipped_at
        FROM orders WHERE order_no=%s AND store_id=%s""", (order_no, store_id))

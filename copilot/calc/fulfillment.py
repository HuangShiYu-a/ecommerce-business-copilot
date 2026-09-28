"""物流履约异常判定（T-A-01，CS-06）。

NORMAL：按时送达（delivered ≤ promised），或在途未超承诺日（as_of 时点）
ANOMALY：超 promised 未按时送达（delivered > promised），或在途超承诺日（overdue_in_transit）
UNDETERMINED：缺 promised_delivery_at（MISSING_PROMISED_AT）
"""
from __future__ import annotations

import datetime

from ..db import query_one


def fulfillment_delay(conn, order: dict, store_id: int, as_of: str | None = None) -> dict:
    promised = order.get("promised_delivery_at")
    if not promised:
        return {"undetermined": "MISSING_PROMISED_AT"}
    delivered = order.get("delivered_at")
    if not delivered:
        # H2：在途未送达——承诺日已过分析时钟 as_of → 在途超期 ANOMALY（原恒 NORMAL/in_transit）
        from ..config import AS_OF_DATE
        a = datetime.date.fromisoformat(as_of or AS_OF_DATE)
        pd = datetime.datetime.fromisoformat(str(promised)).date()
        overdue = pd < a
        if overdue:
            return {"status": "ANOMALY", "reason": "overdue_in_transit",
                    "overdue_days": (a - pd).days}
        return {"status": "NORMAL", "reason": "in_transit"}
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

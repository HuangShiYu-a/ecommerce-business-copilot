"""T-Q-05 get_shipping_status：物流状态查询（Query，只读）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..db import query, query_one
from ..tool import INVALID_INPUT, NOT_FOUND, Tool, err, ok, register_tool


@register_tool
class GetShippingStatus(Tool):
    tool_id = "T-Q-05"
    name = "get_shipping_status"
    category = "Query"
    description = "按订单号查询物流状态与最新轨迹事件"
    risk = "LOW"
    read_write = "read"
    allowed_roles = ("customer_service", "operations")

    class Input(BaseModel):
        order_no: str = Field(description="订单号")

    input_model = Input

    def run(self, ctx, order_no=None, **kw):
        if not order_no:
            return err(INVALID_INPUT, "需 order_no")
        order = query_one(self.conn, "SELECT id, order_no, status FROM orders WHERE order_no=%s AND store_id=%s",
                          (order_no, ctx.store_id))
        if order is None:
            return err(NOT_FOUND, "订单不存在")
        ship = query_one(self.conn, """
            SELECT id, carrier, status, shipped_at, estimated_delivery_at
            FROM shipments WHERE order_id=%s AND store_id=%s""", (order["id"], ctx.store_id))
        events = []
        if ship:
            events = query(self.conn, """
                SELECT event_type, location, event_time FROM shipment_events
                WHERE shipment_id=%s ORDER BY event_time DESC LIMIT 3""", (ship["id"],))
        return ok({
            "order_no": order_no, "order_status": order["status"],
            "shipping": ship, "latest_events": events,
        })

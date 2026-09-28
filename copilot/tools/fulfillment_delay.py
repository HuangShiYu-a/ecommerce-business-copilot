"""T-A-01 analyze_fulfillment_delay：物流履约异常判定（Analysis，只读）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..calc.fulfillment import fulfillment_delay, get_order
from ..tool import DATA_UNAVAILABLE, INVALID_INPUT, NOT_FOUND, Tool, err, ok, register_tool


@register_tool
class AnalyzeFulfillmentDelay(Tool):
    tool_id = "T-A-01"
    name = "analyze_fulfillment_delay"
    category = "Analysis"
    description = "按订单号判定物流履约（NORMAL/ANOMALY/UNDETERMINED）：超 promised 未按时送达 → ANOMALY"
    risk = "LOW"
    read_write = "read"
    allowed_roles = ("customer_service", "operations")

    class Input(BaseModel):
        order_no: str = Field(description="订单号，如 ORD_01_000002")

    input_model = Input

    def run(self, ctx, order_no=None, **kw):
        if not order_no:
            return err(INVALID_INPUT, "需 order_no")
        order = get_order(self.conn, order_no, ctx.store_id)
        if order is None:
            return err(NOT_FOUND, "订单不存在")
        from ..config import AS_OF_DATE
        result = fulfillment_delay(self.conn, order, ctx.store_id, as_of=AS_OF_DATE)
        if "undetermined" in result:
            return err(DATA_UNAVAILABLE, result["undetermined"])
        result.update(order_no=order_no)
        return ok(result)

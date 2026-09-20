"""T-Q-04 get_order：订单详情查询（Query，CS-08 支撑）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..calc.orders import get_order_detail
from ..tool import INVALID_INPUT, NOT_FOUND, Tool, err, ok, register_tool


@register_tool
class GetOrder(Tool):
    tool_id = "T-Q-04"
    name = "get_order"
    category = "Query"
    description = "按订单号查询订单详情（状态/关键时间/明细行/商品类目）"
    risk = "LOW"
    read_write = "read"
    allowed_roles = ("customer_service", "operations")

    class Input(BaseModel):
        order_no: str = Field(description="订单号")

    input_model = Input

    def run(self, ctx, order_no=None, **kw):
        if not order_no:
            return err(INVALID_INPUT, "需 order_no")
        order = get_order_detail(self.conn, ctx.store_id, order_no=order_no)
        if order is None:
            return err(NOT_FOUND, "订单不存在")
        return ok(order)

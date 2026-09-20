"""T-A-09 check_return_eligibility：退货资格判定（Analysis/Decision，CS-08）。

确定性三态：系统读订单/商品事实 + RAG after_sales 规则消解 → eligible/ineligible/undetermined。
LLM 不产出正式资格结论（WF-CS08-09 §3 / §10）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..calc.orders import get_order_detail
from ..calc.return_policy import existing_return, return_eligibility
from ..config import AS_OF_DATE
from ..rag import resolve_rules
from ..tool import DATA_UNAVAILABLE, FORBIDDEN, INVALID_INPUT, NOT_FOUND, Tool, err, ok, register_tool


@register_tool
class CheckReturnEligibility(Tool):
    tool_id = "T-A-09"
    name = "check_return_eligibility"
    category = "Analysis"
    description = "按订单号判定退货资格（eligible/ineligible/undetermined）：系统读订单事实 + 当前有效退货规则"
    risk = "MEDIUM"
    read_write = "read"
    allowed_roles = ("customer_service", "operations")

    class Input(BaseModel):
        order_no: str = Field(description="订单号，如 ORD_01_000438")
        return_reason: str | None = Field(default=None, description="退货原因（可选）")

    input_model = Input

    def run(self, ctx, order_no=None, return_reason=None, **kw):
        if not order_no:
            return err(INVALID_INPUT, "需 order_no")
        order = get_order_detail(self.conn, ctx.store_id, order_no=order_no)
        if order is None:
            return err(NOT_FOUND, "订单不存在")
        item = (order.get("items") or [{}])[0]
        if not item:
            return err(DATA_UNAVAILABLE, "订单无明细行")

        # 规则 scope：类目 code + SKU 属性标签（CONF-01/02 靠 include_tags 互斥命中）
        from ..calc.return_policy import category_code
        attrs = item.get("attributes") or {}
        tags = [attrs["product_type"]] if isinstance(attrs, dict) and attrs.get("product_type") else []
        scope = {"category_code": category_code(item.get("category_name")), "tags": tags}
        rules = resolve_rules(self.conn, "退货窗口 无理由退货几天", ctx.store_id, scope=scope)

        result = return_eligibility(order, item, AS_OF_DATE, rules)
        existing = existing_return(self.conn, order["id"], ctx.store_id)
        result["existing_return"] = existing
        return ok(result)

"""T-A-05 calculate_product_health：商品健康度（Analysis，只读，确定性）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..calc.inventory import resolve_sku
from ..calc.product_health import product_health
from ..tool import INVALID_INPUT, NOT_FOUND, Tool, err, ok, register_tool


@register_tool
class CalculateProductHealth(Tool):
    tool_id = "T-A-05"
    name = "calculate_product_health"
    category = "Analysis"
    description = "按 SKU 计算商品健康度（五核心维 + 完整度 + 评分/等级），traffic 可选恒缺不降级"
    risk = "LOW"
    read_write = "read"
    allowed_roles = ("operations",)

    class Input(BaseModel):
        sku_code: str | None = Field(default=None, description="SKU 编码")
        sku_id: int | None = None
        window_days: int | None = Field(default=None, description="销量窗口天数（默认 30）")

    input_model = Input

    def run(self, ctx, sku_id=None, sku_code=None, window_days=None, **kw):
        if sku_id is None and not sku_code:
            return err(INVALID_INPUT, "需 sku_id 或 sku_code")
        sku = resolve_sku(self.conn, ctx.store_id, sku_id=sku_id, sku_code=sku_code)
        if sku is None:
            return err(NOT_FOUND, "SKU 不存在")
        from ..config import AS_OF_DATE
        result = product_health(self.conn, sku, ctx.store_id, AS_OF_DATE,
                                window_days=window_days or 30)
        return ok(result)

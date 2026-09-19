"""T-R-01 calculate_restock_recommendation：补货建议（Recommendation，只读，不落库）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..calc.inventory import resolve_sku, restock_recommendation
from ..tool import DATA_UNAVAILABLE, INVALID_INPUT, NOT_FOUND, Tool, err, ok, register_tool


@register_tool
class CalculateRestockRecommendation(Tool):
    tool_id = "T-R-01"
    name = "calculate_restock_recommendation"
    category = "Recommendation"
    description = "按 SKU 计算补货建议量（参数驱动：horizon_days / lead_time_days 可覆盖）"
    risk = "MEDIUM"
    read_write = "read"
    allowed_roles = ("operations",)

    class Input(BaseModel):
        sku_code: str | None = Field(default=None, description="SKU 编码")
        sku_id: int | None = None
        horizon_days: int | None = Field(default=None, description="补货展望天数")
        lead_time_days: int | None = Field(default=None, description="采购周期天数（覆盖 store 配置）")

    input_model = Input

    def run(self, ctx, sku_id=None, sku_code=None, horizon_days=None, lead_time_days=None, **kw):
        if sku_id is None and not sku_code:
            return err(INVALID_INPUT, "需 sku_id 或 sku_code")
        sku = resolve_sku(self.conn, ctx.store_id, sku_id=sku_id, sku_code=sku_code)
        if sku is None:
            return err(NOT_FOUND, "SKU 不存在")
        result = restock_recommendation(self.conn, sku, ctx.store_id, self._as_of(),
                                        horizon_days=horizon_days, lead_time_days=lead_time_days)
        if "undetermined" in result:
            return err(DATA_UNAVAILABLE, result["undetermined"])
        if "error" in result:
            return err(NOT_FOUND, result["error"])
        result.update(sku_id=sku["id"], sku_code=sku["sku_code"])
        return ok(result)

    def _as_of(self):
        from ..config import AS_OF_DATE
        return AS_OF_DATE

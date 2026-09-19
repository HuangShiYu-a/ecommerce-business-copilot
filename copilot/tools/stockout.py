"""T-A-07 analyze_stockout_risk：缺货风险分析（Analysis，只读，确定性）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..calc.inventory import resolve_sku, stockout_analysis
from ..tool import DATA_UNAVAILABLE, INVALID_INPUT, NOT_FOUND, Tool, err, ok, register_tool


@register_tool
class AnalyzeStockoutRisk(Tool):
    tool_id = "T-A-07"
    name = "analyze_stockout_risk"
    category = "Analysis"
    description = "按 SKU 评估缺货风险等级（HIGH/NORMAL），支持 forecast_days 时间窗"
    risk = "LOW"
    read_write = "read"
    allowed_roles = ("operations",)

    class Input(BaseModel):
        sku_code: str | None = Field(default=None, description="SKU 编码")
        sku_id: int | None = None
        forecast_days: int | None = Field(default=None, description="预测窗口天数，如 7/14/30")

    input_model = Input

    def run(self, ctx, sku_id=None, sku_code=None, forecast_days=None, **kw):
        if sku_id is None and not sku_code:
            return err(INVALID_INPUT, "需 sku_id 或 sku_code")
        sku = resolve_sku(self.conn, ctx.store_id, sku_id=sku_id, sku_code=sku_code)
        if sku is None:
            return err(NOT_FOUND, "SKU 不存在")
        result = stockout_analysis(self.conn, sku, ctx.store_id, self._as_of(),
                                   forecast_days=forecast_days)
        if "undetermined" in result:
            return err(DATA_UNAVAILABLE, result["undetermined"])
        if "error" in result:
            return err(NOT_FOUND, result["error"])
        result.update(sku_id=sku["id"], sku_code=sku["sku_code"])
        return ok(result)

    def _as_of(self):
        from ..config import AS_OF_DATE
        return AS_OF_DATE

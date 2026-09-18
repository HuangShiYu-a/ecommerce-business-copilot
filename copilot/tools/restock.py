"""T-R-01 calculate_restock_recommendation：补货建议（Recommendation，只读，不落库）。"""
from __future__ import annotations

from ..calc.inventory import resolve_sku, restock_recommendation
from ..tool import DATA_UNAVAILABLE, INVALID_INPUT, NOT_FOUND, Tool, err, ok, register_tool


@register_tool
class CalculateRestockRecommendation(Tool):
    tool_id = "T-R-01"
    name = "calculate_restock_recommendation"
    category = "Recommendation"
    risk = "MEDIUM"

    def run(self, ctx, sku_id=None, sku_code=None, horizon_days=None, **kw):
        if sku_id is None and not sku_code:
            return err(INVALID_INPUT, "需 sku_id 或 sku_code")
        sku = resolve_sku(self.conn, ctx.store_id, sku_id=sku_id, sku_code=sku_code)
        if sku is None:
            return err(NOT_FOUND, "SKU 不存在")
        result = restock_recommendation(self.conn, sku, ctx.store_id, self._as_of(),
                                        horizon_days=horizon_days)
        if "undetermined" in result:
            return err(DATA_UNAVAILABLE, result["undetermined"])
        if "error" in result:
            return err(NOT_FOUND, result["error"])
        result.update(sku_id=sku["id"], sku_code=sku["sku_code"])
        return ok(result)

    def _as_of(self):
        from ..config import AS_OF_DATE
        return AS_OF_DATE

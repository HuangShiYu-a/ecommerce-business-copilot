"""T-A-06 analyze_sales_anomaly：销售异常判定（Analysis，只读，确定性）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..calc.inventory import resolve_sku
from ..calc.sales_anomaly import sales_anomaly
from ..tool import DATA_UNAVAILABLE, INVALID_INPUT, NOT_FOUND, Tool, err, ok, register_tool


@register_tool
class AnalyzeSalesAnomaly(Tool):
    tool_id = "T-A-06"
    name = "analyze_sales_anomaly"
    category = "Analysis"
    description = "按 SKU 判定销售异常（WoW 近 7 天 vs 前 7 天，阈值来自 StoreConfig），返回 is_anomaly/证据/可能原因"
    risk = "LOW"
    read_write = "read"
    allowed_roles = ("operations",)

    class Input(BaseModel):
        sku_code: str | None = Field(default=None, description="SKU 编码")
        sku_id: int | None = None
        baseline_policy: str | None = Field(default=None, description="基线策略标识（wow/store_default，仅标识不作数值覆盖）")

    input_model = Input

    def run(self, ctx, sku_id=None, sku_code=None, baseline_policy=None, **kw):
        if sku_id is None and not sku_code:
            return err(INVALID_INPUT, "需 sku_id 或 sku_code")
        sku = resolve_sku(self.conn, ctx.store_id, sku_id=sku_id, sku_code=sku_code)
        if sku is None:
            return err(NOT_FOUND, "SKU 不存在")
        from ..config import AS_OF_DATE
        result = sales_anomaly(self.conn, sku, ctx.store_id, AS_OF_DATE, baseline_policy=baseline_policy)
        if "undetermined" in result:
            return err(DATA_UNAVAILABLE, result["undetermined"])
        result.update(sku_id=sku["id"], sku_code=sku["sku_code"])
        return ok(result)

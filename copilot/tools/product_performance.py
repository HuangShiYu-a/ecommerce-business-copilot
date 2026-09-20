"""T-A-04 query_product_performance（mode=slow_moving）：低动销候选筛选（Analysis，只读）。

slow_moving 为候选筛选视角，非正式滞销风险等级（WF-OP03 F.3 语义钉死）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..calc.slow_moving import slow_moving_candidates
from ..tool import DATA_UNAVAILABLE, INVALID_INPUT, Tool, err, ok, register_tool


@register_tool
class QueryProductPerformance(Tool):
    tool_id = "T-A-04"
    name = "query_product_performance"
    category = "Analysis"
    description = "低动销候选筛选（mode=slow_moving）：单 SKU 校验或类目扫描，返回窗口销量 ≤ 阈值的候选清单"
    risk = "LOW"
    read_write = "read"
    allowed_roles = ("operations",)

    class Input(BaseModel):
        sku_code: str | None = Field(default=None, description="单 SKU 校验（可选）")
        category: str | None = Field(default=None, description="类目名称片段，如「美妆」（可选，类目扫描）")
        mode: str = Field(default="slow_moving")

    input_model = Input

    def run(self, ctx, sku_code=None, category=None, mode="slow_moving", **kw):
        if mode != "slow_moving":
            return err(INVALID_INPUT, f"未支持模式: {mode}")
        if not sku_code and not category:
            return err(DATA_UNAVAILABLE, "PERF_QUERY_FAIL")
        from ..config import AS_OF_DATE
        result = slow_moving_candidates(self.conn, ctx.store_id, AS_OF_DATE,
                                        category=category, sku_code=sku_code)
        return ok(result)

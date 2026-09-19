"""T-Q-03 get_inventory：查询库存（Query，只读，store 隔离）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..calc.inventory import resolve_sku
from ..db import query_one
from ..tool import INVALID_INPUT, NOT_FOUND, Tool, err, ok, register_tool


@register_tool
class GetInventory(Tool):
    tool_id = "T-Q-03"
    name = "get_inventory"
    category = "Query"
    description = "按 SKU 查询当前可用库存/安全库存/再订货点（store 隔离）"
    risk = "LOW"
    read_write = "read"
    allowed_roles = ("customer_service", "operations")

    class Input(BaseModel):
        sku_code: str | None = Field(default=None, description="SKU 编码，如 SKU_01_STOCKOUT_01")
        sku_id: int | None = None

    input_model = Input

    def run(self, ctx, sku_id=None, sku_code=None, **kw):
        if sku_id is None and not sku_code:
            return err(INVALID_INPUT, "需 sku_id 或 sku_code")
        sku = resolve_sku(self.conn, ctx.store_id, sku_id=sku_id, sku_code=sku_code)
        if sku is None:
            return err(NOT_FOUND, "SKU 不存在")
        row = query_one(self.conn, """
            SELECT sku.id AS sku_id, sku.sku_code, inv.warehouse_id,
                   inv.available_qty, inv.reserved_qty, inv.safety_stock, inv.reorder_point
            FROM inventory inv JOIN product_skus sku ON sku.id = inv.sku_id
            WHERE inv.store_id = %s AND inv.sku_id = %s""", (ctx.store_id, sku["id"]))
        if row is None:
            return err(NOT_FOUND, "库存不存在")
        return ok(row)

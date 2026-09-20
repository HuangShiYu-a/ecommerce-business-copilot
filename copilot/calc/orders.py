"""订单详情查询（T-Q-04，CS-08 支撑）：订单头 + 明细（含类目/标签）。"""
from __future__ import annotations

from ..db import query, query_one


def get_order_detail(conn, store_id: int, order_no: str | None = None,
                     order_id: int | None = None) -> dict | None:
    """按 order_no 或 id 在 store 域内取订单头 + 明细（含商品类目名、SKU 属性标签）。"""
    if order_no:
        order = query_one(conn, "SELECT * FROM orders WHERE order_no=%s AND store_id=%s",
                          (order_no, store_id))
    elif order_id is not None:
        order = query_one(conn, "SELECT * FROM orders WHERE id=%s AND store_id=%s",
                          (order_id, store_id))
    else:
        return None
    if order is None:
        return None
    items = query(conn, """
        SELECT oi.id, oi.product_id, oi.sku_id, oi.quantity, oi.unit_price, oi.line_amount,
               p.name AS product_name, p.category_id, c.name AS category_name,
               s.sku_code, s.attributes
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        LEFT JOIN product_categories c ON c.id = p.category_id
        JOIN product_skus s ON s.id = oi.sku_id
        WHERE oi.order_id=%s AND oi.store_id=%s""", (order["id"], store_id))
    order["items"] = items
    return order

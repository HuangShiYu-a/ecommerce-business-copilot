"""T-X-01 create_return_request：创建退货申请（Action，HIGH，需审批 + 审计 + 幂等）。

审批通过后才允许建单（WF-CS08-09 §7 Approval / §11）。
- 无 approval → APPROVAL_REQUIRED
- 资格未过 / 超可退数量 → PRECONDITION_FAILED
- 缺 item_id/quantity 或非法 → VALIDATION_ERROR
- 重复 request_id → 幂等返回已有单
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel, Field

from ..db import query_one
from ..tool import (APPROVAL_REQUIRED, FORBIDDEN, INVALID_INPUT, NOT_FOUND,
                    PRECONDITION_FAILED, Tool, err, ok, register_tool)


@register_tool
class CreateReturnRequest(Tool):
    tool_id = "T-X-01"
    name = "create_return_request"
    category = "Action"
    description = "审批通过后创建退货申请（需 approval + quantity ≤ 可退数量；幂等）"
    risk = "HIGH"
    read_write = "write"
    requires_approval = True
    idempotent = True
    allowed_roles = ("customer_service",)

    class Approval(BaseModel):
        approver_id: int
        approved_at: str
        decision: str
        comment: str | None = None

    class Input(BaseModel):
        order_id: int = Field(description="订单 id")
        item_id: int = Field(description="订单明细行 id（order_items.id）")
        quantity: int = Field(description="退货数量（>0 且 ≤ 该行可退数量）")
        reason: str = Field(description="退货原因")
        request_id: str = Field(description="幂等键（重复调用返回同一单）")
        approval: Approval = Field(description="审批元数据（decision 必须 approved）")

    input_model = Input

    def run(self, ctx, order_id=None, item_id=None, quantity=None, reason=None,
            request_id=None, approval=None, **kw):
        if approval is None:
            return err(APPROVAL_REQUIRED, "退货申请需审批通过后才可创建")
        if not (approval.get("decision") == "approved" and approval.get("approver_id")):
            return err(APPROVAL_REQUIRED, "审批 decision 必须为 approved 且含 approver_id")
        if not item_id or not quantity or int(quantity) <= 0:
            return err(INVALID_INPUT, "需 item_id 且 quantity > 0")

        order = query_one(self.conn, "SELECT * FROM orders WHERE id=%s AND store_id=%s",
                          (order_id, ctx.store_id))
        if order is None:
            return err(NOT_FOUND, "订单不存在")
        item = query_one(self.conn, "SELECT * FROM order_items WHERE id=%s AND store_id=%s",
                         (item_id, ctx.store_id))
        if item is None:
            return err(NOT_FOUND, "订单明细不存在")

        # 幂等：同一 request_id 已存在 → 返回已有单（须在可退数量校验前，重复提交返回原单）
        dup = query_one(self.conn, "SELECT * FROM after_sales_requests WHERE store_id=%s AND idempotency_key=%s",
                        (ctx.store_id, request_id))
        if dup:
            return ok({"return_request_id": dup["id"], "status": dup["status"],
                       "created_at": str(dup["created_at"]), "idempotent": True})

        returned = query_one(self.conn, """
            SELECT COALESCE(SUM(quantity),0) AS q FROM after_sales_requests
            WHERE order_item_id=%s AND store_id=%s""", (item_id, ctx.store_id))["q"]
        returnable = int(item["quantity"]) - int(returned)
        if int(quantity) > returnable:
            return err(PRECONDITION_FAILED, f"可退数量不足（可退 {returnable}，申请 {quantity}）")

        from ..config import AS_OF_DATE
        next_id = query_one(self.conn, "SELECT COALESCE(MAX(id),0)+1 AS n FROM after_sales_requests")["n"]
        request_no = f"ASR{ctx.store_id:02d}{next_id:09d}"
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO after_sales_requests
                    (id, store_id, request_no, order_id, order_item_id, customer_id,
                     type, quantity, reason, status, idempotency_key, requested_by,
                     approver_id, approved_at, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,'RETURN',%s,%s,'APPROVED',%s,%s,%s,%s,%s,%s)
            """, (next_id, ctx.store_id, request_no, order_id, item_id, order["customer_id"],
                  int(quantity), reason, request_id, ctx.user_id,
                  int(approval["approver_id"]), approval.get("approved_at") or AS_OF_DATE,
                  AS_OF_DATE, AS_OF_DATE))
            cur.execute("""
                INSERT INTO audit_logs (id, store_id, actor_id, approver_id, action,
                    resource_type, resource_id, payload, result, request_id, created_at)
                VALUES (%s,%s,%s,%s,'CREATE_RETURN_REQUEST','after_sales_requests',%s,
                        %s::jsonb,'SUCCESS',%s,%s)
            """, (next_id + 1, ctx.store_id, ctx.user_id, int(approval["approver_id"]),
                  next_id, '{"quantity":%d,"order_id":%d}' % (int(quantity), order_id),
                  request_id, AS_OF_DATE))
        self.conn.commit()
        return ok({"return_request_id": next_id, "status": "APPROVED", "created_at": AS_OF_DATE,
                   "request_no": request_no})

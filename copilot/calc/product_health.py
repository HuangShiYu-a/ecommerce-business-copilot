"""商品健康度计算（T-A-05，OP-07，KD-OP-01 口径）。

五核心维：sales / inventory / margin / returns / feedback；traffic 可选恒缺。
- margin 由 cost_price 判断（KD-OP-01：毛利 = 售价 − 成本价；无成本价则维度缺失）
- data_completeness = 核心维齐全度（缺 traffic 不降级）
- 健康分计算不得依赖 LLM/RAG（WF-OP07 D.3 钉死）
"""
from __future__ import annotations

from ..db import query_one

CORE_DIMS = ("sales", "inventory", "margin", "returns", "feedback")
OPTIONAL_DIMS = ("traffic",)


def product_health(conn, sku: dict, store_id: int, as_of: str, window_days: int = 30) -> dict:
    present: dict[str, bool] = {}
    # sales：窗口内有有效销售
    row = query_one(conn, """
        SELECT COALESCE(SUM(oi.quantity),0) AS units FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE oi.sku_id=%s AND o.store_id=%s AND o.status IN ('PAID','PROCESSING','SHIPPED','COMPLETED')
          AND o.ordered_at >= (%s::date - make_interval(days => %s))""",
        (sku["id"], store_id, as_of, window_days))
    present["sales"] = (row["units"] or 0) > 0
    # inventory：有库存行
    present["inventory"] = query_one(
        conn, "SELECT 1 FROM inventory WHERE sku_id=%s AND store_id=%s", (sku["id"], store_id)) is not None
    # margin：有成本价（KD-OP-01 口径）
    present["margin"] = sku.get("cost_price") not in (None, 0, "")
    # returns：该 sku 有成功售后申请（L4：只算成功态，REJECTED/CANCELLED/PENDING 不计）
    present["returns"] = query_one(conn, """
        SELECT 1 FROM after_sales_requests ar
        JOIN order_items oi ON oi.id = ar.order_item_id
        WHERE oi.sku_id=%s AND ar.store_id=%s
          AND ar.status IN ('APPROVED','COMPLETED','PROCESSING')""", (sku["id"], store_id)) is not None
    # feedback：该 sku 商品有反馈（经 product_id）
    present["feedback"] = query_one(conn, """
        SELECT 1 FROM customer_feedback WHERE product_id=%s AND store_id=%s""",
        (sku["product_id"], store_id)) is not None

    missing_core = [d for d in CORE_DIMS if not present[d]]
    core_present = [d for d in CORE_DIMS if present[d]]
    completeness = round(len(core_present) / len(CORE_DIMS), 2)

    if missing_core:
        if "margin" in missing_core:
            summary = "缺核心维（无 cost → margin 缺），完整度降级"
        else:
            summary = f"缺核心维（{'、'.join(missing_core)} 缺失），完整度降级"
        level = "attention"
        risk_factors = missing_core
    else:
        summary = "五核心齐，仅缺可选 traffic；核心完整度 high。可选维缺失已标注、核心未降级"
        level = "good"
        risk_factors = []

    score = round(completeness * 100, 1)
    return {
        "sku_id": sku["id"],
        "sku_code": sku["sku_code"],
        "score": score,
        "level": level,
        "dimensions": {d: "present" if present.get(d) else "missing" for d in CORE_DIMS + OPTIONAL_DIMS},
        "data_completeness": {"present": core_present, "missing": missing_core, "ratio": completeness},
        "risk_factors": risk_factors,
        "summary": summary,
        "basis": "store_config + domain",
    }

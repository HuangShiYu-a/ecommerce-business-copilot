"""退货资格判定（T-A-09，CS-08，WF-CS08-09 §4/§5）。

三态：eligible / ineligible / undetermined（确定性，LLM 不参与）。
- 类目映射：product_categories.name（中文）→ RAG 规则 code（AS-01/02 类目键）
- 不可退：customized/fresh 法定；beauty 平台补充（音像/贴身需 tag，V1 不判）
- 窗口：自签收次日起 N 日（RAG resolved 的 return_window；RULE_CONFLICT → undetermined）
- 事实不足：无 signed_at → MISSING_SIGNED_AT（≠ ineligible）
"""
from __future__ import annotations

import datetime
import re

from ..db import query_one

CATEGORY_CODE = {
    "定制类": "customized", "食品/生鲜": "fresh", "数码/电子": "electronics",
    "美妆/个护": "beauty", "服装/服饰": "apparel", "家居/家纺": "home",
    "图书/音像": "books", "母婴/玩具": "toys",
}
NON_RETURNABLE = {"customized", "fresh", "beauty"}   # 法定 + 平台补充（V1 主口径）
_WINDOW_RE = re.compile(r"(\d+)\s*日")


def category_code(category_name: str) -> str | None:
    return CATEGORY_CODE.get(category_name)


def _window_days(value: str | None) -> int | None:
    if not value:
        return None
    m = _WINDOW_RE.search(value)
    return int(m.group(1)) if m else None


def return_eligibility(order: dict, item: dict, as_of: str, rules: dict) -> dict:
    """资格三态。rules = resolve_rules() 结果（含 resolved/status）。

    返回 {decision, reason_code, explanation, rule_sources, missing_facts, facts_used}。
    """
    # R5 规则冲突 → undetermined（SC-CS08-007）
    if rules.get("status") == "RULE_CONFLICT":
        return {
            "decision": "undetermined", "reason_code": "RULE_CONFLICT",
            "explanation": "退货窗口规则存在冲突，无法判定", "missing_facts": [],
            "facts_used": {"order_status": order.get("status")},
        }

    code = category_code(item.get("category_name") or "")
    facts = {"order_status": order.get("status"), "product_category": code,
             "delivered_or_signed_at": order.get("signed_at") or order.get("delivered_at")}
    # 不可退类目
    if code in NON_RETURNABLE:
        return {"decision": "ineligible", "reason_code": "NON_RETURNABLE_CATEGORY",
                "explanation": f"类目 {item.get('category_name')} 不支持无理由退货",
                "rule_sources": [], "missing_facts": [], "facts_used": facts}

    # 窗口规则（RAG resolved）
    window = _window_days(rules.get("resolved", {}).get("return_window"))
    if window is None:
        return {"decision": "undetermined", "reason_code": "MISSING_RETURN_RULE",
                "explanation": "未取得当前有效退货窗口规则", "missing_facts": ["return_window"],
                "facts_used": facts}

    # 签收事实
    signed = order.get("signed_at")
    if not signed:
        return {"decision": "undetermined", "reason_code": "MISSING_SIGNED_AT",
                "explanation": "已送达但缺少签收时间，无法计算退货窗口",
                "missing_facts": ["signed_at"], "facts_used": facts}

    # 自签收次日起算
    s = datetime.datetime.fromisoformat(str(signed)).date()
    a = datetime.date.fromisoformat(as_of)
    days_since = (a - s).days
    within = days_since <= window
    return {
        "decision": "eligible" if within else "ineligible",
        "reason_code": "WITHIN_RETURN_WINDOW" if within else "RETURN_WINDOW_EXPIRED",
        "explanation": f"签收 {s}（as_of {a}），次日起第 {days_since} 天，窗口 {window} 日，"
                       f"{'在窗口内' if within else '已超窗口'}",
        "missing_facts": [],
        "facts_used": facts,
    }


def existing_return(conn, order_id: int, store_id: int) -> dict | None:
    """已存在成功的售后申请（SC-CS08-006 对照：幂等/防重复）。"""
    return query_one(conn, """
        SELECT id, request_no, status FROM after_sales_requests
        WHERE order_id=%s AND store_id=%s AND status IN ('COMPLETED','APPROVED','PROCESSING')
        ORDER BY id LIMIT 1""", (order_id, store_id))

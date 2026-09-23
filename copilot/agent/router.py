"""规则路由（dryrun / 兜底，Spec-1 §8.4）。

DEPRECATED：仅 AGENT_BACKEND=legacy 回退使用；新架构（ReAct）见 copilot/agent/react.py。
四类角色：① 实体/模式预处理器 ② dryrun 路由器 ③ LLM 失败回退 ④ 硬约束校验。
**规则不抢在 LLM 前决定意图**（live 模式 LLM 主）；本模块在 LLM_MODE=dryrun
或 LLM 失败时提供确定性路由，支撑离线评测与降级。
"""
from __future__ import annotations

import re

from .schemas import RouterResult

SKU_RE = re.compile(r"SKU_\d+_[A-Z0-9_]+")
ORDER_RE = re.compile(r"ORD_\d+_\d+")
HORIZON_RE = re.compile(r"(?:未来|最近|往后|看)\s*(\d+)\s*天")      # 时间窗 → horizon_days
LEAD_RE = re.compile(r"(?:采购周期|到货周期|lead\s*time)[^0-9]{0,6}(\d+)\s*天")  # 采购周期 → lead_time_days

# 意图 → 关键词（按优先级从高到低判定；语义歧义交给 live 的 LLM）
INTENT_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("return_eligibility", ("退货", "退吗", "能不能退", "可退", "售后", "退款")),
    ("restock_recommendation", ("补货", "补仓", "采购", "建议补", "要补")),
    ("stockout_risk", ("缺货", "断货", "会不会卖完", "风险", "够不够卖")),
    ("fulfillment_delay", ("物流异常", "延误", "超时未送达", "没送到")),
    ("shipping_status", ("物流", "快递", "送到", "到哪", "发货", "配送")),
    ("order_query", ("订单", "ORD_")),
    ("sales_anomaly", ("异常", "骤降", "下滑", "异动", "跌", "暴涨")),
    ("slow_moving", ("慢销", "滞销", "卖不动")),
    ("product_health", ("健康度", "健康", "完整度")),
    ("knowledge_query", ("规则", "政策", "规定", "知识")),
    ("inventory_query", ("库存", "剩余", "还有多少", "存量")),
]


CATEGORY_FRAGMENTS = ["美妆", "服装", "家居", "母婴", "食品", "生鲜", "数码", "电子",
                      "图书", "定制", "个护", "家纺", "服饰", "玩具", "音像"]


def extract_entities(message: str) -> dict:
    """实体/模式预抽取：SKU / 订单号 / 时间窗 / 采购周期 / 类目。"""
    entities: dict = {}
    m = SKU_RE.search(message)
    if m:
        entities["sku_code"] = m.group(0)
    m = ORDER_RE.search(message)
    if m:
        entities["order_no"] = m.group(0)
    m = HORIZON_RE.search(message)
    if m:
        entities["horizon_days"] = int(m.group(1))
    m = LEAD_RE.search(message)
    if m:
        entities["lead_time_days"] = int(m.group(1))
    for frag in CATEGORY_FRAGMENTS:
        if frag in message:
            entities["category"] = frag
            break
    return entities


def rule_intent(message: str) -> str:
    """关键词判定意图；无匹配 → out_of_scope。"""
    for intent, keywords in INTENT_KEYWORDS:
        if any(k in message for k in keywords):
            return intent
    return "out_of_scope"


def normalize_entities(entities: dict) -> dict:
    """实体键归一化（LLM 输出的键名可能与工具 Schema 不一致，Spec-1 §10.3）。

    别名 → 规范键；数值字段强转 int。
    """
    aliases = {
        "sku_id": "sku_code", "sku": "sku_code",
        "order_id": "order_no", "order": "order_no",
        "horizon": "horizon_days", "forecast_days": "horizon_days", "window": "horizon_days",
        "lead_time": "lead_time_days", "leadtime": "lead_time_days",
    }
    numeric = {"horizon_days", "lead_time_days"}
    out: dict = {}
    for k, v in (entities or {}).items():
        key = aliases.get(k, k)
        if key in numeric and not isinstance(v, int):
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
        out[key] = v
    return out


# 意图 → 所属角色场景（方向 A：角色自动判定的规则兜底；LLM live 输出优先）
_CS_INTENTS = {"return_eligibility", "shipping_status", "order_query", "fulfillment_delay",
               "knowledge_query"}
_OPS_INTENTS = {"stockout_risk", "restock_recommendation", "inventory_query",
                "sales_anomaly", "slow_moving", "product_health"}


def rule_role(intent: str) -> str | None:
    """按意图判定角色场景；无法判定 → None。"""
    if intent in _CS_INTENTS:
        return "customer_service"
    if intent in _OPS_INTENTS:
        return "operations"
    return None


def route_rules(message: str) -> RouterResult:
    """dryrun 确定性路由：intent + entities + missing_slots。"""
    entities = extract_entities(message)
    intent = rule_intent(message)

    # 槽位依赖：缺必需槽位 → missing_slots（Spec-1 §9.1）
    missing: list[str] = []
    if intent in ("order_query", "shipping_status", "fulfillment_delay", "return_eligibility") \
            and "order_no" not in entities:
        missing.append("order_no")
    if intent == "slow_moving":
        # 慢销：单 SKU 校验或类目扫描二选一
        if "sku_code" not in entities and "category" not in entities:
            missing.append("sku_code")
    elif intent in ("inventory_query", "stockout_risk", "restock_recommendation",
                    "sales_anomaly", "product_health"):
        if "sku_code" not in entities:
            missing.append("sku_code")

    return RouterResult(intent=intent, entities=entities, missing_slots=missing,
                        role=rule_role(intent))

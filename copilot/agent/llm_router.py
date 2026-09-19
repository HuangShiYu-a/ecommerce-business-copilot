"""LLM Router（Spec-1 §8.1）：一次 bind_tools 结构化调用 → RouterResult。

live 模式主路由；dryrun 用 router.route_rules（确定性）。
意图枚举显式进 tool schema（spike ① 验证：枚举被 schema 约束，非自由标签）。
"""
from __future__ import annotations

from ..llm import get_llm
from .registry import INTENTS
from .schemas import RouterResult

_ROUTER_TOOL = {
    "type": "function",
    "function": {
        "name": "route_intent",
        "description": "解析用户意图并抽取实体槽位（从固定意图枚举中选取）",
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": INTENTS,
                           "description": "从枚举中选一个最匹配的意图"},
                "entities": {"type": "object",
                             "description": "从消息中抽取的实体，如 sku_code / order_no / horizon_days"},
                "missing_slots": {"type": "array", "items": {"type": "string"},
                                  "description": "该意图必需但消息中缺失的槽位"},
                "low_confidence": {"type": "boolean",
                                   "description": "意图判断是否低置信（歧义时 true）"},
            },
            "required": ["intent", "entities", "missing_slots"],
        },
    },
}


def llm_route(message: str, conversation: list[dict] | None = None) -> RouterResult:
    """live LLM 结构化路由（带最近对话上下文，支持多轮续问）；
    失败/无 tool_call → 回退规则路由（Spec-1 §8.4）。"""
    from .router import route_rules

    llm = get_llm().bind_tools([_ROUTER_TOOL], tool_choice="required")
    msgs: list[tuple[str, str]] = [
        ("system", "你是意图解析器。从固定枚举中选最匹配的意图，抽取实体槽位。"
                   "entities 字段用英文键（sku_code/order_no/horizon_days/lead_time_days），值用消息原文。"
                   "若用户消息是承接上一轮任务的续问（如「未来 7 天呢」「采购周期 3 天呢」），"
                   "结合上下文选与上轮一致的意图。"),
    ]
    if conversation:
        for turn in conversation[-6:]:
            msgs.append((turn.get("role", "user"), turn.get("content", "")))
    msgs.append(("user", message))
    try:
        resp = llm.invoke(msgs)
        if resp.tool_calls:
            args = resp.tool_calls[0]["args"]
            return RouterResult(**args)
    except Exception:
        pass
    return route_rules(message)

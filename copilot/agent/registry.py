"""Intent Registry（Spec-1 §8.3）：确定性 intent → 执行路径映射。

LLM 只出语义（intent/entities/missing_slots），执行路径由本 Registry 决定，
不依赖 LLM 输出 workflow（消除「选错 workflow 再纠错」的冗余环节）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PathKind = Literal["direct", "workflow", "none"]


@dataclass(frozen=True)
class ExecutionPath:
    kind: PathKind
    target: str | None = None   # direct → tool_id；workflow → workflow id；none → None


# 意图枚举（Spec-1 §8.6 初版）
INTENTS = [
    "inventory_query",
    "stockout_risk",
    "restock_recommendation",
    "order_query",
    "shipping_status",
    "return_eligibility",
    "sales_anomaly",
    "slow_moving",
    "product_health",
    "knowledge_query",
    "out_of_scope",
]

# 确定性映射（Spec-1 §8.3）
REGISTRY: dict[str, ExecutionPath] = {
    "inventory_query": ExecutionPath("direct", "T-Q-03"),
    "stockout_risk": ExecutionPath("workflow", "OP-04"),
    "restock_recommendation": ExecutionPath("workflow", "OP-05"),
    "order_query": ExecutionPath("direct", "T-Q-04"),
    "shipping_status": ExecutionPath("direct", "T-Q-05"),
    "return_eligibility": ExecutionPath("workflow", "CS-08"),
    "sales_anomaly": ExecutionPath("workflow", "OP-08"),
    "slow_moving": ExecutionPath("workflow", "OP-03"),
    "product_health": ExecutionPath("workflow", "OP-07"),
    "knowledge_query": ExecutionPath("direct", "T-K-01"),
    "out_of_scope": ExecutionPath("none"),
}


def resolve(intent: str) -> ExecutionPath | None:
    """按 intent 解析执行路径；未知 intent 返回 None（应被 guardrail 拦下）。"""
    return REGISTRY.get(intent)


def is_known(intent: str) -> bool:
    return intent in REGISTRY

"""用户上下文：store_id 隔离 + 角色（Tool 隐含入参）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserContext:
    user_id: int
    role: str                       # customer_service / operations
    store_id: int                   # 1=STORE_01, 2=STORE_02
    permissions: frozenset = field(default_factory=frozenset)


def ops_ctx(store_id: int) -> UserContext:
    return UserContext(user_id=1, role="operations", store_id=store_id)

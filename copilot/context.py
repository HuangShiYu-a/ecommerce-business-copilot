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


def session_ctx(session: dict) -> UserContext:
    """从会话构造 UserContext（V1 单用户 demo，替代硬编码 ops_ctx）。

    角色取 Workspace Mode（UNSET/CUSTOMER_SERVICE/OPERATIONS）或兼容旧 role；
    未设置时回退 operations（与 legacy ops_ctx 一致）。UNSET 的目录过滤由 toolkit 承担，
    ctx 本身只携带 store/user 供工具执行与审计。
    """
    return UserContext(
        user_id=int(session.get("user_id") or 1),
        role=session.get("workspace_mode") or session.get("role") or "operations",
        store_id=int(session.get("store_id") or 1),
    )


def mode_to_role(mode: str | None) -> str:
    """Workspace Mode（大写）→ 小写角色（customer_service/operations）；UNSET/未知回退 operations。

    消除大写 workspace_mode 与工具 allowed_roles（小写）的大小写冲突（审查发现 1）。
    """
    m = (mode or "").lower()
    return m if m in ("customer_service", "operations") else "operations"

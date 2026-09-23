"""ReAct 图工厂（Phase 6/W6）：按 Workspace Mode 缓存图，共享 checkpointer。

- 共享 PostgresSaver（同 thread 跨模式可读同一 checkpoint → capability 重跑/重启续跑）
- AGENT_BACKEND=legacy 时由调用方走 legacy 图（本工厂只管 ReAct）
- 缓存 key = workspace_mode（UNSET/CUSTOMER_SERVICE/OPERATIONS），3 实例
"""
from __future__ import annotations

from .react import _default_checkpointer, build_react_graph


class ReactGraphFactory:
    """按 workspace_mode 惰性构建并缓存 ReAct 图，共享一个 checkpointer。"""

    def __init__(self, checkpointer=None):
        self._checkpointer = checkpointer or _default_checkpointer()
        self._graphs: dict[str, object] = {}

    def get(self, mode: str):
        """取某模式（UNSET/CUSTOMER_SERVICE/OPERATIONS）的 ReAct 图，惰性构建并缓存。"""
        mode = mode or "UNSET"
        if mode not in self._graphs:
            self._graphs[mode] = build_react_graph(
                model=None, mode=mode, checkpointer=self._checkpointer)
        return self._graphs[mode]

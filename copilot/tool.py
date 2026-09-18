"""Tool 壳：统一接口 + 注册表 + 结果信封 + 标准错误语义（Tool Contract V1.1）。

- Tool 子类实现 run(ctx, **params) -> ToolResult
- @register_tool 注册到 TOOLS[tool_id]
- run_tool 负责连接生命周期与异常兜底（→ DEPENDENCY_ERROR）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .context import UserContext
from .db import connect

# ---- 标准失败语义（Tool Contract §失败）----
INVALID_INPUT = "INVALID_INPUT"
NOT_FOUND = "NOT_FOUND"
FORBIDDEN = "FORBIDDEN"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
RULE_CONFLICT = "RULE_CONFLICT"
PRECONDITION_FAILED = "PRECONDITION_FAILED"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
DEPENDENCY_ERROR = "DEPENDENCY_ERROR"


@dataclass
class ToolResult:
    ok: bool
    data: dict = field(default_factory=dict)
    error_code: str | None = None
    error_detail: str | None = None
    request_id: str | None = None


def ok(data: dict | None = None, request_id: str | None = None) -> ToolResult:
    return ToolResult(ok=True, data=data or {}, request_id=request_id)


def err(code: str, detail: str | None = None, request_id: str | None = None) -> ToolResult:
    return ToolResult(ok=False, error_code=code, error_detail=detail, request_id=request_id)


TOOLS: dict[str, type["Tool"]] = {}


def register_tool(cls: type["Tool"]) -> type["Tool"]:
    TOOLS[cls.tool_id] = cls
    return cls


class Tool:
    tool_id: str = ""
    name: str = ""
    category: str = ""          # Query / Analysis / Knowledge / Recommendation / Action
    risk: str = "LOW"
    requires_approval: bool = False
    idempotent: bool = True

    def __init__(self, conn):
        self.conn = conn

    def run(self, ctx: UserContext, **params) -> ToolResult:
        raise NotImplementedError


def run_tool(tool_id: str, ctx: UserContext, conn=None, **params) -> ToolResult:
    """按 tool_id 调用；未传入 conn 则自建并关闭；异常兜底为 DEPENDENCY_ERROR。"""
    if not TOOLS:
        from . import tools  # noqa: F401  首次调用触发工具注册
    cls = TOOLS.get(tool_id)
    if cls is None:
        return err(NOT_FOUND, f"未知 tool {tool_id}")
    own = conn is None
    if own:
        conn = connect()
    try:
        return cls(conn).run(ctx, **params)
    except Exception as exc:  # 工具内部异常 → 标准错误语义
        return err(DEPENDENCY_ERROR, str(exc))
    finally:
        if own:
            conn.close()

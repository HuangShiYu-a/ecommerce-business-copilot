"""Tool 壳：统一接口 + 注册表 + 结果信封 + 标准错误语义（Tool Contract V1.1）。

- Tool 子类实现 run(ctx, **params) -> ToolResult
- @register_tool 注册到 TOOLS[tool_id]
- run_tool 负责连接生命周期与异常兜底（→ DEPENDENCY_ERROR）
- 跨 store 引用守卫（ISO）：ORD_x_/SKU_x_ 前缀编码门店，引用店 ≠ ctx 店 → FORBIDDEN
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

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
    description: str = ""       # 给 LLM 看的工具说明（Effective Tool Catalog）
    risk: str = "LOW"
    requires_approval: bool = False
    idempotent: bool = True
    read_write: str = "read"    # read | write（写操作需审批/审计）
    allowed_roles: tuple = ()   # 允许角色（空 = 所有角色；Spec-1 §4.2）
    input_model: type[BaseModel] | None = None   # 参数 Schema（D2：Pydantic）
    output_model: type[BaseModel] | None = None

    def __init__(self, conn):
        self.conn = conn

    def run(self, ctx: UserContext, **params) -> ToolResult:
        raise NotImplementedError

    def input_schema(self) -> dict:
        return self.input_model.model_json_schema() if self.input_model else {}

    def output_schema(self) -> dict:
        return self.output_model.model_json_schema() if self.output_model else {}

    @classmethod
    def allows(cls, role: str) -> bool:
        return (not cls.allowed_roles) or role in cls.allowed_roles


# ---- 跨 store 数据隔离（ISO，B5）----

_STORE_PREFIX_RE = re.compile(r"^(?:ORD|SKU)_(\d+)_")


def reference_store(identifier: str) -> int | None:
    """从标识符前缀解析所属店：ORD_02_* / SKU_02_* → 2；无法解析 → None。"""
    m = _STORE_PREFIX_RE.match(identifier or "")
    return int(m.group(1)) if m else None


def cross_store_param(store_id: int, params: dict) -> str | None:
    """扫描参数中的门店引用，找到引用店 ≠ 上下文的参数名；无 → None。

    仅按字符串前缀判定（ORD_x_/SKU_x_）；int 型 order_id/item_id 无法解析前缀，
    不在此拦截——由工具内部 SQL `WHERE ... store_id=ctx.store_id` 兜底（跨店 int id
    → NOT_FOUND，无越权；workflow 写路径已先经 get_order_detail(ctx.store_id) 确认归属本店）。
    """
    for k, v in params.items():
        if isinstance(v, str):
            owned = reference_store(v)
            if owned is not None and owned != store_id:
                return k
    return None


def cross_store_info(store_id: int, params: dict) -> tuple[str, int] | None:
    """跨店拦截信息：返回 (参数名, 引用店号)；无跨店 → None。供 FORBIDDEN 引导用。"""
    for k, v in params.items():
        if isinstance(v, str):
            owned = reference_store(v)
            if owned is not None and owned != store_id:
                return k, owned
    return None


def run_tool(tool_id: str, ctx: UserContext, conn=None, **params) -> ToolResult:
    """按 tool_id 调用；未传入 conn 则自建并关闭；异常兜底为 DEPENDENCY_ERROR。

    跨 store 引用（方向 A）：读工具（read_write=read）放开——按引用店替换 ctx 执行，
    结果标注 source_store；写工具（read_write=write）对字符串前缀跨店引用返回 FORBIDDEN
    （跨店写越权）。注：int 型 order_id/item_id 不走前缀检测，由工具 SQL store_id 过滤兜底
    （→ NOT_FOUND），语义差异见 cross_store_param。
    """
    if not TOOLS:
        from . import tools  # noqa: F401  首次调用触发工具注册
    cls = TOOLS.get(tool_id)
    if cls is None:
        return err(NOT_FOUND, f"未知 tool {tool_id}")
    owned = cross_store_info(ctx.store_id, params)
    if owned:
        param, target_store = owned
        if cls.read_write == "write":
            return err(FORBIDDEN,
                       f"参数 {param} 引用了门店{target_store}的数据（当前上下文门店{ctx.store_id}），"
                       f"跨店写操作被拒绝（写操作仅限当前会话门店）。")
        # 读工具跨店放开：用目标店重建 ctx 执行（SQL 侧 store_id 过滤自然命中目标店）
        import dataclasses
        target_ctx = dataclasses.replace(ctx, store_id=target_store)
        own = conn is None
        if own:
            conn = connect()
        try:
            res = cls(conn).run(target_ctx, **params)
            if res.ok and isinstance(res.data, dict):
                res.data = {**res.data, "source_store": target_store}
            return res
        except Exception as exc:
            return err(DEPENDENCY_ERROR, str(exc))
        finally:
            if own:
                conn.close()
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


def effective_catalog(role: str | None = None) -> list[dict]:
    """Effective Tool Catalog（Spec-1 §8.7）：按角色过滤后的工具元数据。

    DEPRECATED（审查发现 5）：ReAct 新架构用 toolkit._catalog_classes / build_toolkit；
    legacy 运行时不用本函数（走 registry）。仅测试引用，保留供参考。

    LLM 只见权限内工具，靠过滤而非靠模型自觉不调用。
    """
    if not TOOLS:
        from . import tools  # noqa: F401
    out = []
    for tool_id in sorted(TOOLS):
        cls = TOOLS[tool_id]
        if role is not None and not cls.allows(role):
            continue
        t = cls(None)
        out.append({
            "tool_id": t.tool_id,
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "read_write": t.read_write,
            "requires_approval": t.requires_approval,
            "input_schema": t.input_schema(),
        })
    return out

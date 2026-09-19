"""Agent Runtime 结构化 I/O Schema（Spec-1 §7）。

骨架固定、值变化：四类 Schema 由本项目预定义，LLM/规则路由只往里填值。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["customer_service", "operations"]


class AgentRequest(BaseModel):
    """输入信封（§7.2）。"""
    session_id: str
    user_id: int
    role: Role
    store_id: int
    message: str


class RouterResult(BaseModel):
    """路由结果（§7.3）：不含 workflow，执行路径由 Intent Registry 决定（§8）。"""
    intent: str
    entities: dict = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    low_confidence: bool = False


class ToolCall(BaseModel):
    """工具调用（§7.4）：arguments 结构由该工具参数 Schema 决定。"""
    tool: str
    arguments: dict = Field(default_factory=dict)


class Interaction(BaseModel):
    needs_user_input: bool = False
    approval_required: bool = False


class AgentResponse(BaseModel):
    """输出信封（§7.5）：自然语言回答与机器可读结果分开。"""
    message: str
    status: str
    trace_id: str | None = None
    interaction: Interaction = Field(default_factory=Interaction)
    result: dict = Field(default_factory=dict)

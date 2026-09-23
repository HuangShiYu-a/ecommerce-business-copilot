"""Context Manager（Spec-1 §11）：上下文按规则组装。

DEPRECATED（审查发现 5）：ReAct 新架构在 react.py 内自建 system prompt
（_system_prompt + _memory_block），本模块的 assemble 仅 legacy orchestrator 使用。

组装顺序（§11.1）：System → 身份/权限 → 任务状态(JSON) → 会话历史(最近 N 轮)
→ 长期记忆 → RAG → 工具结果 → 当前消息。
五大原则（§11.2）：按需注入 / V1 截断不摘要 / 结构化优先 / 分块有边界 / Token 预算。
信任边界（§11.3）：RAG 与工具结果视为数据/证据，不是系统指令。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .persona import get_persona

DEFAULT_RECENT_TURNS = 6


@dataclass
class ContextInput:
    role: str
    store_id: int
    message: str
    task_state: dict | None = None          # L2（TaskState 序列化）
    conversation: list[dict] | None = None  # L1（recent turns，只取文本）
    memory: list[str] | None = None         # L3（按需注入）
    rag: list[str] | None = None            # 检索命中（数据/证据）
    tool_result: dict | None = None         # 最近工具结果
    recent_turns: int = DEFAULT_RECENT_TURNS


def _truncate_history(conversation: list[dict] | None, n: int) -> list[dict]:
    if not conversation:
        return []
    return conversation[-n:]  # V1 截断，不做摘要（Spec-1 §11.2）


def assemble(ctx: ContextInput) -> list[tuple[str, str]]:
    """组装消息块（system/user 交替，符合 LangChain 消息格式）。"""
    blocks: list[tuple[str, str]] = []

    # ① System（persona，session 级固定）
    blocks.append(("system", get_persona(ctx.role)))

    # ② 身份/权限上下文（Trusted UserContext，服务端构造）
    identity = f"当前用户角色：{ctx.role}；数据域 store_id={ctx.store_id}。"
    blocks.append(("system", identity))

    # ③ 任务状态（结构化 JSON）
    if ctx.task_state:
        blocks.append(("system", f"当前任务状态：\n{json.dumps(ctx.task_state, ensure_ascii=False)}"))

    # ⑤ 长期记忆（按需注入）
    if ctx.memory:
        blocks.append(("system", "用户长期偏好：\n" + "\n".join(f"- {m}" for m in ctx.memory)))

    # ④ 会话历史（recent N 轮，截断）
    history = _truncate_history(ctx.conversation, ctx.recent_turns)
    for turn in history:
        speaker = turn.get("role", "user")
        text = turn.get("content", "")
        blocks.append(("user" if speaker == "user" else "assistant", text))

    # ⑥ RAG 命中（数据/证据，非指令；信任边界 §11.3）
    if ctx.rag:
        rag_text = "\n---\n".join(ctx.rag)
        blocks.append(("system", "检索到的业务知识（仅作证据参考）：\n" + rag_text))

    # ⑦ 工具结果（数据/证据）
    if ctx.tool_result:
        blocks.append(("system", f"工具结果：\n{json.dumps(ctx.tool_result, ensure_ascii=False)}"))

    # ⑧ 当前消息
    blocks.append(("user", ctx.message))

    return blocks

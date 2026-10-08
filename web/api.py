"""UI 桥接层：唯一调用 run_agent_react / run_agent / runtime.store / checkpointer 的地方。

app.py（纯 UI）不直接碰后端；一切取数/发送经本模块。
支持双后端：ReAct（默认，ReactGraphFactory + run_agent_react）与 legacy（AGENT_BACKEND=legacy，
build_runtime_graph + run_agent，回退用）。
"""
from __future__ import annotations

import os
import uuid

from copilot.agent.orchestrator import run_agent
from copilot.agent.react import run_agent_react
from copilot.db import connect, query


def is_legacy() -> bool:
    return os.getenv("AGENT_BACKEND") == "legacy"


def list_sessions(user_id: int) -> list[dict]:
    """runtime.session 按 updated_at 倒序；含徽章字段（role/store，role 即 workspace_mode）。"""
    conn = connect()
    try:
        return query(conn, """
            SELECT session_id, title, role, store_id, status, updated_at
            FROM runtime.session
            WHERE user_id=%s AND status='active'
            ORDER BY updated_at DESC""", (user_id,))
    finally:
        conn.close()   # P1-4：修复连接泄漏（此前 query(connect(), ...) 不 close）


def new_session() -> str:
    """生成 session_id（= thread_id，1:1）；首次发送由 run_agent_react→_persist_session 写入。"""
    return uuid.uuid4().hex


def _msg_to_turn(m) -> dict | None:
    """ReAct messages（BaseMessage）→ [{role, content}]；系统/工具消息跳过。"""
    role = getattr(m, "type", "")
    if role in ("system", "tool"):
        return None
    return {"role": "user" if role == "human" else "assistant",
            "content": str(getattr(m, "content", ""))}


def load_conversation(graph, thread_id: str) -> list[dict]:
    """读回某会话的消息 [{role, content}]；legacy 用 conversation 字段，ReAct 映射 messages。"""
    try:
        values = graph.get_state({"configurable": {"thread_id": thread_id}}).values
        if "conversation" in values:                      # legacy
            return list(values.get("conversation", []))
        return [t for t in (_msg_to_turn(m) for m in values.get("messages", [])) if t]
    except Exception:
        return []


def capability_pending(graph, thread_id: str) -> dict | None:
    """读 AgentState.execution_context.capability_pending（供 UI 渲染能力切换按钮/文本确认）。"""
    from copilot.agent.react import read_capability_pending
    return read_capability_pending(graph, thread_id)


def send(runtime, thread_id: str, session: dict, message: str,
         resume: dict | None = None, capability_replay: bool = False) -> dict:
    """发送一轮。runtime 为 ReactGraphFactory（默认）或 legacy graph（AGENT_BACKEND=legacy）。"""
    try:
        if is_legacy():
            from copilot.context import mode_to_role
            sess = dict(session)
            sess["role"] = mode_to_role(session.get("workspace_mode") or session.get("role"))
            out = run_agent(runtime, thread_id, sess, message)
        else:
            # P1：文本动作解析（能力切换 / 审批确认，用户打字而非点按钮）
            if resume is None and not capability_replay and message:
                from copilot.agent.react import _MODE_LABEL, resolve_text_action
                session, resume, capability_replay, new_pending = resolve_text_action(
                    runtime.get(session.get("workspace_mode") or "UNSET"),
                    thread_id, session, message)
                if new_pending:
                    # 会话一致性（option b+ ⑥）：web 路径同样经 runtime/store 落库（含 token），
                    # 覆盖"首轮即切换命令"的极端场景（该轮不调 run_agent_react，_persist_session 不执行）
                    from copilot.runtime.store import create_session
                    create_session(session.get("session_id"), thread_id,
                                   int(session.get("user_id") or 1),
                                   session.get("workspace_mode") or "UNSET",
                                   int(session.get("store_id") or 1))
                    # 方案 B：切换请求已置 pending → 返回 capability_required 风格响应（不调图）
                    label = _MODE_LABEL.get(new_pending["domain"], new_pending["domain"])
                    return {
                        "message": f"已申请切换到{label}模式，请确认（回复「确认」或点击切换）。",
                        "status": "capability_required",
                        "needs_user_input": True,
                        "approval_required": False,
                        "capability_required": True,
                        "capability_pending": new_pending,
                        "result": {"capability_pending": new_pending},
                        "role": session.get("workspace_mode") or None,
                        "store_id": session.get("store_id"),
                    }
            graph = runtime.get(session.get("workspace_mode") or "UNSET")
            out = run_agent_react(graph, thread_id, session, message,
                                  capability_replay=capability_replay, resume=resume)
        resp = out.get("response", {})
        result = resp.get("result") or {}
        return {
            "message": resp.get("message", ""),
            "status": resp.get("status", "error"),
            "needs_user_input": bool(resp.get("needs_user_input")),
            "approval_required": bool(resp.get("approval_required")),
            "capability_required": resp.get("status") == "capability_required",
            "capability_pending": result.get("capability_pending"),
            "result": result,
            "role": resp.get("role"),
            "store_id": resp.get("store_id"),
        }
    except Exception as exc:
        return {"message": f"处理失败，请重试：{exc}", "status": "error",
                "needs_user_input": False, "approval_required": False,
                "capability_required": False, "capability_pending": None,
                "result": None, "role": None, "store_id": None}

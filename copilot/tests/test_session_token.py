"""P0-1/P0-2 option b+ 测试：会话凭证（session_token）+ 服务端 store/user 锁定。

- resolve_api_session：懒创建（首轮声明）/ token 校验 / 服务端 user-store / 无 token 接管
- api.app：/api/session 落库并返回 token；/api/agent 错 token → 403（不触发 LLM）
- workflow interrupt 携带 operator_user_id（发起者）
依赖：Docker PG(5434) + dev 数据已导入；本文件只写 runtime.session 测试行并自清理。
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi import HTTPException

os.environ.setdefault("LLM_MODE", "dryrun")

from langchain_core.messages import AIMessage

from copilot.db import connect
from copilot.runtime.store import create_session, get_session, resolve_api_session
from copilot.tests.fake_llm import ScriptedFakeModel, tool_call


def _sid(prefix: str = "p2") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture(autouse=True)
def _cleanup_test_sessions():
    yield
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM runtime.session WHERE session_id LIKE 'p2-%'")
        conn.commit()
    finally:
        conn.close()


# ---- resolve_api_session ----

def test_resolve_unknown_creates_with_declared_user_store():
    sid = _sid()
    ctx, err = resolve_api_session(sid, None, declared_user=1, declared_store=2, role="OPERATIONS")
    assert err is None
    assert ctx["user_id"] == 1 and ctx["store_id"] == 2
    assert ctx["session_token"]
    row = get_session(sid)
    assert row["session_token"] == ctx["session_token"]
    assert row["store_id"] == 2


def test_resolve_existing_requires_matching_token():
    sid = _sid()
    token = create_session(sid, sid, 1, "UNSET", 1)
    # 匹配 token → user/store 以服务端为准（请求体声明被忽略）
    ctx, err = resolve_api_session(sid, token, declared_user=99, declared_store=99, role="UNSET")
    assert err is None
    assert ctx["user_id"] == 1 and ctx["store_id"] == 1
    # 错 token → 拒绝
    ctx, err = resolve_api_session(sid, "wrong-token", declared_user=1, declared_store=1, role="UNSET")
    assert ctx is None and err == "会话凭证无效"
    # 缺 token → 拒绝
    ctx, err = resolve_api_session(sid, None, declared_user=1, declared_store=1, role="UNSET")
    assert ctx is None and err == "会话凭证无效"


def test_resolve_tokenless_session_adopts():
    sid = _sid()
    create_session(sid, sid, 1, "UNSET", 1)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE runtime.session SET session_token=NULL WHERE session_id=%s", (sid,))
        conn.commit()
    finally:
        conn.close()
    ctx, err = resolve_api_session(sid, None, declared_user=1, declared_store=1, role="UNSET")
    assert err is None and ctx["session_token"]
    assert get_session(sid)["session_token"] == ctx["session_token"]


# ---- api.app 层（不触发 LLM：/api/session 纯落库；/api/agent 403 在解析层拦截）----

def test_api_create_session_returns_token():
    from copilot.api.app import AgentResponse, SessionRequest, create_session
    req = SessionRequest(user_id=1, workspace_mode="UNSET", store_id=1)
    resp = create_session(req)
    assert isinstance(resp, AgentResponse)
    assert resp.session_id and resp.session_token
    assert get_session(resp.session_id)["session_token"] == resp.session_token


def test_api_agent_wrong_token_raises_403():
    from copilot.api.app import AgentRequest, agent
    sid = _sid()
    create_session(sid, sid, 1, "UNSET", 1)
    req = AgentRequest(session_id=sid, session_token="bad", message="你好")
    with pytest.raises(HTTPException) as ei:
        agent(req)
    assert ei.value.status_code == 403


# ---- workflow interrupt 携带发起者 ----

def test_workflow_interrupt_carries_operator_user_id():
    from copilot.agent.react import build_react_graph, run_agent_react
    model = ScriptedFakeModel(script=[
        AIMessage(content="", tool_calls=[
            tool_call("cs08_return_workflow", {"order_no": "ORD_01_000438"})]),
        AIMessage(content="完成"),
    ])
    g = build_react_graph(model=model, mode="CUSTOMER_SERVICE", checkpointer=None)
    sid = _sid("p2op")
    sess = {"session_id": sid, "user_id": 1, "workspace_mode": "CUSTOMER_SERVICE", "store_id": 1}
    out = run_agent_react(g, sid, sess, "ORD_01_000438 申请退货")
    resp = out["response"]
    assert resp["status"] == "approval_required"
    assert resp["result"]["operator_user_id"] == 1

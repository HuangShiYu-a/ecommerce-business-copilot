"""FastAPI 工作台（Phase 6）：ReAct 运行时（默认）或 legacy（AGENT_BACKEND=legacy）。

- GET  /            静态页（copilot/api/static/）
- POST /api/agent   一轮对话（ReAct run_agent_react：workspace_mode / resume / capability_replay）
- POST /api/session 创建会话（服务端落库并签发 session_token）

session_id 即 LangGraph thread_id（一个 Session = 一个 Thread）。
审批确认：前端发 resume={"decision":"approved|rejected"}；能力切换：capability_replay=true。
会话凭证（P0-1/P0-2 option b+，demo 边界）：
- 既有会话的每次 /api/agent 必须携带匹配 session_token，否则 403（审批/续答需持有会话凭证）；
- store_id/user_id 以服务端会话记录为准（请求体忽略；首轮为客户端声明的信任引导）；
- 每个响应回传 session_token（首轮 approval_required 也能拿到 token 供 resume）。
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agent.orchestrator import build_runtime_graph, run_agent
from ..agent.react import run_agent_react

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="E-commerce Business Copilot", version="0.3.0")

LEGACY = os.getenv("AGENT_BACKEND") == "legacy"
if LEGACY:
    RUNTIME = build_runtime_graph()
else:
    from ..agent.graph_factory import ReactGraphFactory
    RUNTIME = ReactGraphFactory()


class AgentRequest(BaseModel):
    session_id: str
    session_token: str | None = None        # 会话凭证（既有会话必须携带）
    user_id: int = Field(default=1, ge=1)   # 仅首轮（懒创建）作为声明；既有会话以服务端为准
    workspace_mode: str = "UNSET"           # UNSET / CUSTOMER_SERVICE / OPERATIONS
    store_id: int = Field(default=1, ge=1)  # 仅首轮（懒创建）作为声明；既有会话以服务端为准
    message: str = ""
    resume: dict | None = None              # 审批确认/拒绝（{decision: approved|rejected}）
    capability_replay: bool = False         # 能力切换后同 thread 重跑


class SessionRequest(BaseModel):
    user_id: int = Field(default=1, ge=1)
    workspace_mode: str = "UNSET"
    store_id: int = Field(default=1, ge=1)


class AgentResponse(BaseModel):
    session_id: str
    session_token: str | None = None        # 每个响应回传（客户端存储，供后续请求/resume）
    message: str
    status: str
    needs_user_input: bool = False
    approval_required: bool = False
    capability_required: bool = False
    capability_pending: dict | None = None
    result: dict = {}


@app.post("/api/session")
def create_session(req: SessionRequest) -> AgentResponse:
    from ..runtime.store import resolve_api_session
    sid = uuid.uuid4().hex[:12]
    sess_ctx, err = resolve_api_session(sid, None, req.user_id, req.store_id, req.workspace_mode)
    return AgentResponse(
        session_id=sid,
        session_token=sess_ctx["session_token"] if sess_ctx else None,
        message="会话已创建。请提问（如：SKU_01_STOCKOUT_01 缺货风险怎么样）",
        status="active",
    )


@app.post("/api/agent")
def agent(req: AgentRequest) -> AgentResponse:
    from ..runtime.store import resolve_api_session
    sess_ctx, err = resolve_api_session(req.session_id, req.session_token,
                                        req.user_id, req.store_id, req.workspace_mode)
    if err:
        raise HTTPException(status_code=403, detail=err)
    session = {"session_id": req.session_id, "user_id": sess_ctx["user_id"],
               "workspace_mode": req.workspace_mode, "store_id": sess_ctx["store_id"]}
    token = sess_ctx["session_token"]
    try:
        if LEGACY:
            from ..context import mode_to_role
            sess = dict(session)
            sess["role"] = mode_to_role(req.workspace_mode)
            result = run_agent(RUNTIME, req.session_id, sess, req.message)
        else:
            graph = RUNTIME.get(req.workspace_mode)
            resume, capability_replay = req.resume, req.capability_replay
            # P1：文本动作解析（能力切换 / 审批确认，用户打字而非点按钮）
            if resume is None and not capability_replay and req.message:
                from ..agent.react import _MODE_LABEL, resolve_text_action
                session, resume, capability_replay, new_pending = resolve_text_action(
                    graph, req.session_id, session, req.message)
                if new_pending:
                    # 方案 B：切换请求已置 pending → 返回 capability_required 风格响应（不调图）
                    label = _MODE_LABEL.get(new_pending["domain"], new_pending["domain"])
                    return AgentResponse(
                        session_id=req.session_id,
                        session_token=token,
                        message=f"已申请切换到{label}模式，请确认（回复「确认」或点击切换）。",
                        status="capability_required",
                        needs_user_input=True,
                        capability_required=True,
                        capability_pending=new_pending,
                        result={"capability_pending": new_pending},
                    )
                if capability_replay:
                    graph = RUNTIME.get(session["workspace_mode"])
            result = run_agent_react(graph, req.session_id, session, req.message,
                                     capability_replay=capability_replay, resume=resume)
        resp = result["response"]
        result_ = resp.get("result") or {}
        return AgentResponse(
            session_id=req.session_id,
            session_token=token,
            message=resp.get("message", ""),
            status=resp.get("status", "error"),
            needs_user_input=bool(resp.get("needs_user_input")),
            approval_required=bool(resp.get("approval_required")),
            capability_required=resp.get("status") == "capability_required",
            capability_pending=result_.get("capability_pending"),
            result=result_,
        )
    except HTTPException:
        raise    # 403 等 HTTP 错误放行（不由通用兜底吞掉）
    except Exception as exc:
        # P1-2：执行异常 → 结构化 error 响应（防 500；与 web/api.py 兜底语义一致）
        return AgentResponse(session_id=req.session_id, session_token=token,
                             message=f"处理失败，请重试：{exc}", status="error",
                             needs_user_input=False)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("copilot.api.app:app", host="127.0.0.1", port=8000, reload=True)

"""FastAPI 工作台（Phase 6）：ReAct 运行时（默认）或 legacy（AGENT_BACKEND=legacy）。

- GET  /            静态页（copilot/api/static/）
- POST /api/agent   一轮对话（ReAct run_agent_react：workspace_mode / resume / capability_replay）
- POST /api/session 创建会话

session_id 即 LangGraph thread_id（一个 Session = 一个 Thread）。
审批确认：前端发 resume={"decision":"approved|rejected"}；能力切换：capability_replay=true。
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import FastAPI
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
    user_id: int = Field(default=1, ge=1)
    workspace_mode: str = "UNSET"          # UNSET / CUSTOMER_SERVICE / OPERATIONS
    store_id: int = Field(default=1, ge=1)
    message: str = ""
    resume: dict | None = None             # 审批确认/拒绝（{decision: approved|rejected}）
    capability_replay: bool = False        # 能力切换后同 thread 重跑


class SessionRequest(BaseModel):
    user_id: int = Field(default=1, ge=1)
    workspace_mode: str = "UNSET"
    store_id: int = Field(default=1, ge=1)


class AgentResponse(BaseModel):
    session_id: str
    message: str
    status: str
    needs_user_input: bool = False
    approval_required: bool = False
    capability_required: bool = False
    capability_pending: dict | None = None
    result: dict = {}


@app.post("/api/session")
def create_session(req: SessionRequest) -> AgentResponse:
    sid = uuid.uuid4().hex[:12]
    return AgentResponse(session_id=sid, message="会话已创建。请提问（如：SKU_01_STOCKOUT_01 缺货风险怎么样）",
                         status="active")


@app.post("/api/agent")
def agent(req: AgentRequest) -> AgentResponse:
    session = {"session_id": req.session_id, "user_id": req.user_id,
               "workspace_mode": req.workspace_mode, "store_id": req.store_id}
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
            from ..agent.react import resolve_text_action
            session, resume, capability_replay = resolve_text_action(
                graph, req.session_id, session, req.message)
            if capability_replay:
                graph = RUNTIME.get(session["workspace_mode"])
        result = run_agent_react(graph, req.session_id, session, req.message,
                                 capability_replay=capability_replay, resume=resume)
    resp = result["response"]
    result_ = resp.get("result") or {}
    return AgentResponse(
        session_id=req.session_id,
        message=resp.get("message", ""),
        status=resp.get("status", "error"),
        needs_user_input=bool(resp.get("needs_user_input")),
        approval_required=bool(resp.get("approval_required")),
        capability_required=resp.get("status") == "capability_required",
        capability_pending=result_.get("capability_pending"),
        result=result_,
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("copilot.api.app:app", host="127.0.0.1", port=8000, reload=True)

"""FastAPI 工作台（S4.4 → Agent Runtime V2）。

- GET  /            静态页（copilot/api/static/）
- POST /api/agent   一轮对话（Runtime orchestrator 驱动，含多轮/HITL/参数驱动）
- POST /api/session 创建会话（选角色+store → 返回 session_id）

session_id 即 LangGraph thread_id（Spec-1 §6：一个 Session = 一个 Thread）。
confirm 由前端发送「确认/拒绝」文本，经 pending_check 处理（Spec-1 §3.1）。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agent.orchestrator import build_runtime_graph, run_agent
from ..agent.schemas import Role

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="E-commerce Business Copilot", version="0.2.0")

GRAPH = build_runtime_graph()


class AgentRequest(BaseModel):
    session_id: str
    user_id: int = Field(default=1, ge=1)
    role: Role = "operations"
    store_id: int = Field(default=1, ge=1)
    message: str


class SessionRequest(BaseModel):
    user_id: int = Field(default=1, ge=1)
    role: Role = "operations"
    store_id: int = Field(default=1, ge=1)


class AgentResponse(BaseModel):
    session_id: str
    message: str
    status: str
    needs_user_input: bool = False
    approval_required: bool = False
    result: dict = {}


@app.post("/api/session")
def create_session(req: SessionRequest) -> AgentResponse:
    sid = uuid.uuid4().hex[:12]
    return AgentResponse(session_id=sid, message="会话已创建。请提问（如：SKU_01_STOCKOUT_01 库存多少）",
                         status="active")


@app.post("/api/agent")
def agent(req: AgentRequest) -> AgentResponse:
    session = {"session_id": req.session_id, "user_id": req.user_id,
               "role": req.role, "store_id": req.store_id}
    result = run_agent(GRAPH, req.session_id, session, req.message)
    resp = result["response"]
    return AgentResponse(
        session_id=req.session_id,
        message=resp.get("message", ""),
        status=resp.get("status", "error"),
        needs_user_input=resp.get("needs_user_input", False),
        approval_required=resp.get("approval_required", False),
        result=resp.get("result", {}),
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("copilot.api.app:app", host="127.0.0.1", port=8000, reload=True)

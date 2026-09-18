"""FastAPI 工作台（S4.4）。

- GET  /             静态页（copilot/api/static/）
- POST /api/agent    起一条 OP-05 工作流；HAS_RECO 时停在人工确认（interrupt）
- POST /api/confirm  人类确认结果（accepted/rejected）→ resume 工作流

线程模型：单进程内用 InMemorySaver 保活；thread_id 由本模块生成并返回，
确认时回传。LLM 默认读 .env（DEEPSEEK_API_KEY）；LLM_MODE=dryrun 可离线跑。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from ..agent.op05 import Op05State, build_graph

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="E-commerce Business Copilot", version="0.1.0")

_SAVER = InMemorySaver()
GRAPH = build_graph(_SAVER)


class AgentRequest(BaseModel):
    message: str
    store_id: int = Field(default=1, ge=1)


class ConfirmRequest(BaseModel):
    thread_id: str
    decision: Literal["accepted", "rejected"]


class AgentResponse(BaseModel):
    request_id: str
    route_status: str
    message: str
    tool_result: dict = {}
    confirm_needed: bool = False
    thread_id: str | None = None


def _to_response(thread_id: str, state: dict) -> AgentResponse:
    if "__interrupt__" in state:
        return AgentResponse(
            request_id=state.get("request_id", ""),
            route_status="WAITING_CONFIRMATION",
            message=state.get("explanation", ""),
            tool_result=state.get("tool_result", {}),
            confirm_needed=True,
            thread_id=thread_id,
        )
    return AgentResponse(
        request_id=state.get("request_id", ""),
        route_status=state.get("route_status", "ERROR"),
        message=state.get("final_message") or state.get("explanation", ""),
        tool_result=state.get("tool_result", {}),
        confirm_needed=False,
        thread_id=thread_id,
    )


@app.post("/api/agent")
def agent(req: AgentRequest) -> AgentResponse:
    request_id = uuid.uuid4().hex[:12]
    thread_id = uuid.uuid4().hex[:12]
    state = GRAPH.invoke(
        {"request_id": request_id, "store_id": req.store_id, "message": req.message},
        config={"configurable": {"thread_id": thread_id}},
    )
    return _to_response(thread_id, state)


@app.post("/api/confirm")
def confirm(req: ConfirmRequest) -> AgentResponse:
    state = GRAPH.invoke(
        Command(resume=req.decision),
        config={"configurable": {"thread_id": req.thread_id}},
    )
    return _to_response(req.thread_id, state)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("copilot.api.app:app", host="127.0.0.1", port=8000, reload=True)

"""Trace Adapter（Spec-1 §13）：Domain Trace Event 生成与消费。

事件枚举（§13.2）：intent_detected / tool_called / tool_completed /
knowledge_retrieved / human_requested / human_confirmed / step_completed /
step_failed / final_response。
原则（§13.3）：不暴露 LLM 原始思考；内部事件 → 用户安全事件由 UI 侧呈现。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

TRACE_EVENTS = (
    "intent_detected", "tool_called", "tool_completed", "knowledge_retrieved",
    "human_requested", "human_confirmed", "step_completed", "step_failed",
    "final_response",
)


@dataclass
class TraceEvent:
    type: str
    run_id: str
    step: str
    status: str = "success"
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class Trace:
    """单次 Run 的事件收集器。"""

    def __init__(self, run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.events: list[TraceEvent] = []

    def emit(self, type_: str, step: str, status: str = "success", payload: dict | None = None):
        if type_ not in TRACE_EVENTS:
            raise ValueError(f"未知 trace 事件: {type_}")
        self.events.append(TraceEvent(type=type_, run_id=self.run_id, step=step,
                                      status=status, payload=payload or {}))

    def to_list(self) -> list[dict]:
        return [
            {"type": e.type, "run_id": e.run_id, "step": e.step,
             "status": e.status, "payload": e.payload, "timestamp": e.timestamp}
            for e in self.events
        ]

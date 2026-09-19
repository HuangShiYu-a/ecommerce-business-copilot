"""Agent Runtime State（Spec-1 §5）：task 5 态状态机 + AgentRuntimeState 分区。

- task 状态机（§5.4）：running / waiting_user_input / completed / terminated / failed
  interrupted 不单列：HITL→waiting_user_input，错误→failed。
- 状态机是「继续」恢复判定、UI 显示、评测断言的依据。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

# ---- task 状态机（5 态）----
RUNNING = "running"
WAITING_USER_INPUT = "waiting_user_input"
COMPLETED = "completed"
TERMINATED = "terminated"
FAILED = "failed"

TASK_STATES = (RUNNING, WAITING_USER_INPUT, COMPLETED, TERMINATED, FAILED)


@dataclass
class TaskState:
    """L2 任务状态（§5.1）：正在执行什么 / 已拿到什么 / 缺什么 / 执行到哪。"""
    intent: str | None = None
    slots: dict = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    status: str = RUNNING
    current_step: str | None = None

    def is_waiting(self) -> bool:
        return self.status == WAITING_USER_INPUT

    def is_resumable(self) -> bool:
        """「继续」可恢复：HITL/缺槽（waiting_user_input）或可恢复失败。"""
        return self.status in (WAITING_USER_INPUT, FAILED)

    def is_terminal(self) -> bool:
        return self.status in (COMPLETED, TERMINATED)


class AgentRuntimeState(TypedDict, total=False):
    """AgentRuntimeState 分区（§5.2）。"""
    session: dict            # session_id / user_id / role / store_id
    conversation: dict       # messages(L1) / summary(预留)
    routing: dict            # intent / low_confidence
    task: dict               # L2（TaskState 序列化）
    context: dict            # role_prompt / memory(L3) / retrieved_knowledge
    execution: dict          # run_id / trace / error

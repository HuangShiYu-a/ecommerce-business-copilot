"""NiceGUI workbench（Phase 6）：ReAct 运行时 + Workspace Mode + capability/审批交互。

- Workspace Mode（UNSET/客服/运营）：顶栏下拉，手动切换
- capability 切换：capability_required → 一键切换到目标模式并自动重跑（D10=a+/D12）
- 审批确认：approval_required → 确认/拒绝按钮（resume）
- 会话侧栏 + 历史（ReAct messages 映射）
- 加载态（busy 防重入）
纯 UI 层：取数/发送一律经 web.api。
"""
from __future__ import annotations

from nicegui import ui

from . import api

USER_ID = 1  # V1 单用户硬编码（无登录）

ROLE_LABEL = {"customer_service": "客服", "operations": "运营",
              "CUSTOMER_SERVICE": "客服", "OPERATIONS": "运营", "UNSET": "未锁定"}


def _label(mode: str) -> str:
    return ROLE_LABEL.get(mode, mode)


class Workbench:
    def __init__(self, runtime):
        self.runtime = runtime
        self.workspace_mode: str = "UNSET"
        self.store_id: int = 1
        self.session_id: str | None = None
        self.thread_id: str | None = None
        self.pending_capability: dict | None = None   # {domain, original_message}
        self.busy: bool = False
        self._mode_select: ui.select | None = None
        self._session_list: ui.column | None = None
        self._chat_area: ui.column | None = None
        self._msg_input: ui.input | None = None
        self._cap_btn: ui.button | None = None
        self._confirm_row: ui.row | None = None
        self._status: ui.label | None = None
        self._build()

    # ---- 布局 ----
    def _build(self):
        with ui.header().classes("items-center"):
            ui.label("E-commerce Copilot").classes("text-xl font-bold")
            ui.space()
            with ui.row().classes("items-center gap-2"):
                self._mode_select = ui.select(
                    ["UNSET", "CUSTOMER_SERVICE", "OPERATIONS"], value="UNSET",
                    label="模式", on_change=self._on_mode_change).props("dense outlined")
                ui.button("＋ 新建对话", on_click=self._new_session)

        with ui.left_drawer(value=True).classes("w-72 p-3"):
            ui.label("会话历史").classes("text-sm text-grey-7")
            self._session_list = ui.column().classes("w-full gap-1")
            self._status = ui.label().classes("mt-3 text-xs text-grey-6")

        with ui.column().classes("grow p-4"):
            self._chat_area = ui.column().classes("grow overflow-auto")
            self._cap_btn = ui.button("", on_click=self._switch_capability)
            self._cap_btn.set_visibility(False)
            with ui.row() as self._confirm_row:
                ui.button("确认", on_click=lambda: self._resume("approved")).props("color=positive")
                ui.button("拒绝", on_click=lambda: self._resume("rejected")).props("color=negative")
            self._confirm_row.set_visibility(False)
            with ui.row().classes("w-full items-center gap-2"):
                self._msg_input = ui.input(
                    placeholder="请输入问题…").props("outlined dense").classes("grow")
                self._msg_input.on("keydown.enter", lambda: self._send())
                ui.button("发送", on_click=lambda: self._send())

        self._refresh_sessions()

    # ---- 会话 ----
    def _refresh_sessions(self):
        if self._session_list is None:
            return
        self._session_list.clear()
        for s in api.list_sessions(USER_ID):
            mode = s.get("role") or "UNSET"
            title = s.get("title") or "新对话"
            sid = s["session_id"]
            with self._session_list:
                card = ui.card().classes("w-full p-2 cursor-pointer")
                with card:
                    ui.label(title).classes("text-sm")
                    ui.label(f"[{_label(mode)}·门店{s.get('store_id')}]").classes("text-xs text-grey-6")
            card.on("click", lambda sid=sid: self._switch_session(sid))
        self._status.set_text(
            f"模式：{_label(self.workspace_mode)} · 门店{self.store_id}"
            + (" · 处理中…" if self.busy else ""))

    def _switch_session(self, session_id: str):
        self.session_id = session_id
        self.thread_id = session_id
        self.pending_capability = None
        self._cap_btn.set_visibility(False)
        self._confirm_row.set_visibility(False)
        self._chat_area.clear()
        if self.runtime is not None:
            from copilot.agent.graph_factory import ReactGraphFactory
            if isinstance(self.runtime, ReactGraphFactory):
                # ReAct：读该会话实际模式（runtime.session.role 即 workspace_mode）
                for s in api.list_sessions(USER_ID):
                    if s["session_id"] == session_id:
                        self.workspace_mode = s.get("role") or "UNSET"
                        self._mode_select.value = self.workspace_mode
                        break
                graph = self.runtime.get(self.workspace_mode)
            else:
                graph = self.runtime
            for m in api.load_conversation(graph, session_id):
                self._add_bubble(m["role"], m["content"])
        self._refresh_sessions()
        self._msg_input.set_value("")

    def _new_session(self):
        self.session_id = None
        self.thread_id = None
        self.pending_capability = None
        self.workspace_mode = "UNSET"
        self._mode_select.value = "UNSET"
        self._chat_area.clear()
        self._cap_btn.set_visibility(False)
        self._confirm_row.set_visibility(False)
        self._msg_input.set_value("")
        self._refresh_sessions()

    # ---- 消息 ----
    def _add_bubble(self, role: str, content: str):
        align = "items-end justify-end" if role == "user" else "items-start"
        bg = "bg-blue-50" if role == "user" else "bg-grey-2"
        with self._chat_area, ui.row().classes(f"w-full {align}"):
            ui.label(content).classes(f"max-w-[75%] p-3 rounded-xl whitespace-pre-wrap {bg}")

    def _switch_capability(self):
        if not self.pending_capability:
            return
        self.workspace_mode = self.pending_capability.get("domain", "OPERATIONS")
        self._mode_select.value = self.workspace_mode
        self.pending_capability = None
        self._cap_btn.set_visibility(False)
        self._send(capability_replay=True)   # 同一 thread 重跑原请求（D12，不追加用户消息）

    def _resume(self, decision: str):
        if self.session_id is None:
            return
        self._confirm_row.set_visibility(False)
        session = {"session_id": self.session_id, "user_id": USER_ID,
                   "workspace_mode": self.workspace_mode, "store_id": self.store_id}
        resp = api.send(self.runtime, self.thread_id, session, "",
                        resume={"decision": decision})
        self._handle_resp(resp)

    def _send(self, capability_replay: bool = False):
        msg = (self._msg_input.value or "").strip()
        if not capability_replay and not msg:
            return
        if self.busy:
            return
        if self.session_id is None:
            self.session_id = api.new_session()
            self.thread_id = self.session_id
        if not capability_replay:
            self._add_bubble("user", msg)
        self.busy = True
        self._refresh_sessions()
        session = {"session_id": self.session_id, "user_id": USER_ID,
                   "workspace_mode": self.workspace_mode, "store_id": self.store_id}
        resp = api.send(self.runtime, self.thread_id, session, msg,
                        capability_replay=capability_replay)
        self.busy = False
        self._msg_input.set_value("")
        self._handle_resp(resp)

    def _handle_resp(self, resp: dict):
        self._cap_btn.set_visibility(False)
        self._confirm_row.set_visibility(False)
        msg = resp.get("message", "")
        if resp.get("capability_required") and resp.get("capability_pending"):
            self.pending_capability = resp["capability_pending"]
            domain = self.pending_capability.get("domain", "OPERATIONS")
            self._add_bubble("assistant", msg)
            self._cap_btn.text = f"切换到{_label(domain)}模式并继续"
            self._cap_btn.set_visibility(True)
        elif resp.get("approval_required"):
            self._add_bubble("assistant", msg)
            self._confirm_row.set_visibility(True)
        else:
            self._add_bubble("assistant", msg)
        if resp.get("role"):
            self.workspace_mode = resp["role"]
            self._mode_select.value = self.workspace_mode
        self._refresh_sessions()

    def _on_mode_change(self, e):
        self.workspace_mode = e.value
        self.pending_capability = None
        self._cap_btn.set_visibility(False)
        self._refresh_sessions()


def build_page(runtime) -> Workbench:
    return Workbench(runtime)

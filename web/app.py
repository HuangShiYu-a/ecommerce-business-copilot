"""NiceGUI workbench（Phase 6）：ReAct 运行时 + Workspace Mode + capability/审批交互。

- Workspace Mode（UNSET/客服/运营）：顶栏下拉，手动切换
- capability 切换：capability_required → 一键切换到目标模式并自动重跑（D10=a+/D12）
- 审批确认：approval_required → 确认/拒绝按钮（resume）
- 会话侧栏 + 历史（ReAct messages 映射）
- 加载态（busy 防重入）
纯 UI 层：取数/发送一律经 web.api。
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from . import api

USER_ID = 1  # V1 单用户硬编码（无登录）

ROLE_LABEL = {"customer_service": "客服", "operations": "运营",
              "CUSTOMER_SERVICE": "客服", "OPERATIONS": "运营", "UNSET": "未锁定"}

# I2：空会话引导文案（E1 §3.4 示例问题，按当前模式过滤）
WELCOME_SUGGESTIONS = {
    "UNSET": ["ORD_01_000002 物流到哪了", "订单退货政策是什么"],
    "CUSTOMER_SERVICE": ["ORD_01_000438 可以退货吗", "ORD_01_000002 物流有没有延误",
                         "订单退货政策是什么"],
    "OPERATIONS": ["SKU_01_STOCKOUT_01 缺货风险怎么样", "SKU_01_NORMAL_01 需要补货吗",
                   "SKU_01_ANOMALY_DROP_01 销售有没有异常", "SKU_01_SLOW_01 是不是慢销"],
}


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
        self._cap_banner: ui.row | None = None
        self._confirm_row: ui.row | None = None
        self._status: ui.label | None = None
        self._welcome: ui.column | None = None
        self._welcome_input: ui.textarea | None = None   # E4：空态居中输入框
        self._welcome_suggestions: ui.column | None = None
        self._input_row: ui.row | None = None   # E4：底部输入行（空态时隐藏，与居中输入互斥）
        self._build()

    # ---- 布局 ----
    def _build(self):
        # 第一批 R1：视口锁高、禁 body 滚动 → 消息区内部滚动、输入区固定底部。
        # header/drawer 为 fixed（不占文档流），q-page-container 已让出头部空间（padding-top）。
        ui.query("body").style("height: 100vh; overflow: hidden")
        ui.query(".q-page-container").classes("h-screen")
        ui.query(".q-page").classes("h-full")
        ui.query(".nicegui-content").classes("h-full")

        with ui.header().classes("items-center"):
            ui.label("E-commerce Copilot").classes("text-xl font-bold")
            ui.space()
            with ui.row().classes("items-center gap-2"):
                self._mode_select = ui.select(
                    {"UNSET": "未锁定", "CUSTOMER_SERVICE": "客服", "OPERATIONS": "运营"},
                    value="UNSET", label="模式",
                    on_change=self._on_mode_change).props("dense outlined")
                ui.button("＋ 新建对话", on_click=self._new_session)

        with ui.left_drawer(value=True).classes("w-72 p-3"):
            ui.label("会话历史").classes("text-sm text-grey-7")
            self._session_list = ui.column().classes("w-full gap-1")
            self._status = ui.label().classes("mt-3 text-xs text-grey-6")

        with ui.column().classes("h-full flex flex-col overflow-hidden p-4"):
            # 第一批 R3+第二批 E2（方案A）：普通 overflow 列 + flex-col-reverse + 气泡前插
            # → 纯 CSS 通道自动贴底（最新在底部、初始/切会话/新消息均显示最新）。
            # 不用 ui.scroll_area：其内容绝对定位使 column-reverse 失效，且本架构 run_method/JS 不投递。
            self._chat_area = ui.column().classes(
                "flex-1 min-h-0 w-full overflow-y-auto flex-col-reverse")
            self._welcome = ui.column().classes("flex-1 min-h-0 w-full items-center justify-center gap-2")
            with self._welcome:
                # 第三批 E4：空态居中输入框（与底部输入互斥，session 激活后随 welcome 隐藏）
                with ui.row().classes("w-full max-w-md items-center gap-2"):
                    self._welcome_input = ui.textarea(
                        placeholder="请输入问题…（Enter 发送 / Shift+Enter 换行）"
                    ).props('outlined dense autogrow input-style="max-height: 10rem; overflow-y: auto"').classes("grow w-full")
                    self._welcome_input.on("keydown", self._on_input_keydown)
                    ui.button("发送", on_click=lambda: self._send())
                # E4：建议区独立容器（每次 _render_welcome 重建，不触碰输入框）
                self._welcome_suggestions = ui.column().classes("w-full max-w-md gap-1")
            self._welcome.set_visibility(False)
            with ui.row().classes("flex-none items-center gap-2") as self._cap_banner:
                self._cap_banner.set_visibility(False)
                ui.label("待切换：").classes("text-sm text-grey-7")
                self._cap_btn = ui.button("", on_click=self._switch_capability)
                ui.label("（或输入确认切换）").classes("text-xs text-grey-6")
            with ui.row().classes("flex-none") as self._confirm_row:
                ui.button("确认", on_click=lambda: self._resume("approved")).props("color=positive")
                ui.button("拒绝", on_click=lambda: self._resume("rejected")).props("color=negative")
            self._confirm_row.set_visibility(False)
            with ui.row().classes("flex-none w-full items-center gap-2") as self._input_row:
                # 第二批 E3：textarea + autogrow（输入换行增高，上限后内部滚动；Enter 发送 / Shift+Enter 换行）
                self._msg_input = ui.textarea(
                    placeholder="请输入问题…（Enter 发送 / Shift+Enter 换行）"
                ).props('outlined dense autogrow input-style="max-height: 10rem; overflow-y: auto"').classes("grow w-full")
                self._msg_input.on("keydown", self._on_input_keydown)
                ui.button("发送", on_click=lambda: self._send())

        self._refresh_sessions()
        # I4：加载时恢复「最近且有内容」的会话（跳过无 checkpoint 的测试/空行，避免空白观感）
        if self.session_id is None and self.runtime is not None:
            from copilot.context import normalize_mode
            for s in api.list_sessions(USER_ID):
                if api.is_legacy():
                    has = bool(api.load_conversation(self.runtime, s["session_id"]))
                else:
                    mode = normalize_mode(s.get("role") or "UNSET")
                    has = bool(api.load_conversation(self.runtime.get(mode), s["session_id"]))
                if has:
                    self._switch_session(s["session_id"])
                    break
        self._update_welcome()

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
                # I3：当前会话高亮
                active = " border-2 border-blue-500" if sid == self.session_id else ""
                card = ui.card().classes("w-full p-2 cursor-pointer" + active)
                with card:
                    ui.label(title).classes("text-sm")
                    ui.label(f"[{_label(mode)}·门店{s.get('store_id')}]").classes("text-xs text-grey-6")
            card.on("click", lambda sid=sid: self._switch_session(sid))
        self._status.set_text(
            f"模式：{_label(self.workspace_mode)} · 门店{self.store_id}"
            + (" · 处理中…" if self.busy else ""))

    # ---- 欢迎引导（I2：空会话示例问题；E4：居中输入框）----
    def _active_input(self):
        """当前可见的输入框：空态（无会话）用居中输入，会话激活用底部输入。"""
        if self._welcome_input is not None and self.session_id is None:
            return self._welcome_input
        return self._msg_input

    def _clear_inputs(self):
        """新建/切会话时双输入都清空（E4）。"""
        if self._msg_input is not None:
            self._msg_input.set_value("")
        if self._welcome_input is not None:
            self._welcome_input.set_value("")

    def _render_welcome(self):
        if self._welcome_suggestions is None:
            return
        self._welcome_suggestions.clear()
        with self._welcome_suggestions:
            ui.label("试试这些问题：").classes("text-sm text-grey-6")
            for text in WELCOME_SUGGESTIONS.get(self.workspace_mode, WELCOME_SUGGESTIONS["UNSET"]):
                ui.button(text, on_click=lambda t=text: self._send_suggestion(t)) \
                    .props("flat outline dense no-caps").classes("w-full")

    def _update_welcome(self):
        if self._welcome is None or self._chat_area is None:
            return
        show = self.session_id is None   # 无活动会话时才显示引导
        self._welcome.set_visibility(show)
        self._chat_area.set_visibility(not show)
        # E4：底部输入行与居中输入互斥（空态隐藏底部行）
        if self._input_row is not None:
            self._input_row.set_visibility(not show)
        if show:
            self._render_welcome()

    async def _send_suggestion(self, text: str):
        self._active_input().set_value(text)
        await self._send()

    def _switch_session(self, session_id: str):
        self.session_id = session_id
        self.thread_id = session_id
        self.pending_capability = None
        self._cap_banner.set_visibility(False)
        self._confirm_row.set_visibility(False)
        self._chat_area.clear()
        if self.runtime is not None:
            if not api.is_legacy():
                # ReAct：读该会话实际模式（runtime.session.role 即 workspace_mode）
                for s in api.list_sessions(USER_ID):
                    if s["session_id"] == session_id:
                        # P2：session.role 可能是小写 legacy 角色（旧行），归一化回大写
                        # Workspace Mode，避免重开会话落入 UNSET 目录、丢失 CS-08/OP-05
                        from copilot.context import normalize_mode
                        self.workspace_mode = normalize_mode(s.get("role") or "UNSET")
                        self._mode_select.value = self.workspace_mode
                        break
                graph = self.runtime.get(self.workspace_mode)
            else:
                graph = self.runtime
            for m in api.load_conversation(graph, session_id):
                self._add_bubble(m["role"], m["content"])
        self._refresh_sessions()
        self._clear_inputs()
        self._update_welcome()

    def _new_session(self):
        self.session_id = None
        self.thread_id = None
        self.pending_capability = None
        self.workspace_mode = "UNSET"
        self._mode_select.value = "UNSET"
        self._chat_area.clear()
        self._cap_banner.set_visibility(False)
        self._confirm_row.set_visibility(False)
        self._clear_inputs()
        self._refresh_sessions()
        self._update_welcome()

    # ---- 消息 ----
    def _on_input_keydown(self, e):
        """Enter 发送 / Shift+Enter 换行（E3）。"""
        if e.key == "Enter" and not getattr(e.modifiers, "shift", False):
            asyncio.create_task(self._send())

    def _add_bubble(self, role: str, content: str):
        align = "items-end justify-end" if role == "user" else "items-start"
        bg = "bg-blue-50" if role == "user" else "bg-grey-2"
        with self._chat_area:
            with ui.row().classes(f"w-full {align}") as row:
                ui.label(content).classes(f"max-w-[75%] p-3 rounded-xl whitespace-pre-wrap {bg}")
        # E2（方案A）：column-reverse 下最新在底部 → 每气泡前插 DOM 首位
        # （load 倒序 + 新消息贴底，纯 CSS 通道自动贴底）
        row.move(self._chat_area, 0)
        return row   # F6：供"正在分析…"占位气泡后续删除

    async def _switch_capability(self):
        if not self.pending_capability:
            return
        self.workspace_mode = self.pending_capability.get("domain", "OPERATIONS")
        self._mode_select.value = self.workspace_mode
        self.pending_capability = None
        self._cap_banner.set_visibility(False)
        await self._send(capability_replay=True)   # 同一 thread 重跑原请求（D12，不追加用户消息）

    async def _resume(self, decision: str):
        if self.session_id is None:
            return
        self._confirm_row.set_visibility(False)
        session = {"session_id": self.session_id, "user_id": USER_ID,
                   "workspace_mode": self.workspace_mode, "store_id": self.store_id}
        thinking = self._add_bubble("assistant", "正在处理审批…")
        await asyncio.sleep(0.05)   # F6：让占位气泡先渲染
        try:
            resp = await asyncio.to_thread(
                api.send, self.runtime, self.thread_id, session, "",
                resume={"decision": decision})
        finally:
            if thinking is not None:
                try:
                    thinking.delete()
                except Exception:
                    pass
        self._handle_resp(resp)

    async def _send(self, capability_replay: bool = False):
        inp = self._active_input()   # E4：取当前可见输入框（空态居中 / 会话底部）
        msg = (inp.value or "").strip()
        if not capability_replay and not msg:
            return
        if self.busy:
            return
        if self.session_id is None:
            self.session_id = api.new_session()
            self.thread_id = self.session_id
        self._update_welcome()
        if not capability_replay:
            self._add_bubble("user", msg)
        self.busy = True
        self._refresh_sessions()
        thinking = self._add_bubble("assistant", "正在分析…")
        await asyncio.sleep(0.05)   # F6：先渲染"正在分析…"，再执行阻塞的 ReAct 往返
        session = {"session_id": self.session_id, "user_id": USER_ID,
                   "workspace_mode": self.workspace_mode, "store_id": self.store_id}
        try:
            resp = await asyncio.to_thread(
                api.send, self.runtime, self.thread_id, session, msg,
                capability_replay=capability_replay)
        finally:
            self.busy = False
            if thinking is not None:
                try:
                    thinking.delete()
                except Exception:
                    pass
        inp.set_value("")
        self._handle_resp(resp)

    def _handle_resp(self, resp: dict):
        self._cap_banner.set_visibility(False)
        self.pending_capability = None      # F9：默认无待切换，capability_required 时重设
        self._confirm_row.set_visibility(False)
        msg = resp.get("message", "")
        if resp.get("capability_required") and resp.get("capability_pending"):
            self.pending_capability = resp["capability_pending"]
            domain = self.pending_capability.get("domain", "OPERATIONS")
            self._add_bubble("assistant", msg)
            self._cap_btn.text = f"切换到{_label(domain)}模式并继续"
            self._cap_banner.set_visibility(True)
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
        self._cap_banner.set_visibility(False)
        self._refresh_sessions()
        self._update_welcome()


def build_page(runtime) -> Workbench:
    return Workbench(runtime)

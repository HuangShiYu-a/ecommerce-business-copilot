# UI Workbench E1 — 详细设计（V1.0）

> 上游：[E0 结构草图](./ui-workbench-e0-v1.md)  
> 版本：**V1.0**  
> 技术栈：NiceGUI（Python 全栈）；目录 `web/`  
> 依赖：`copilot.agent.orchestrator.run_agent` / `build_runtime_graph`；`copilot.runtime.store`；LangGraph PostgresSaver

---

## 0. E0 决策落定

| 决策点 | 结论 |
|--------|------|
| 角色/门店 | **新建对话时锁定**（每会话固定 role+store_id，左栏显示徽章 `[客服·店1]`）|
| 流式 | V1 整轮显示（`run_agent` 同步返回）；AR-18 流式留 E2 |
| 会话列表 | `updated_at` 倒序平铺 |

---

## 1. 模块划分（web/ 三文件）

```
web/
  app.py     # NiceGUI 页面：布局、组件、事件回调（纯 UI 层，不碰 DB/agent）
  api.py     # 桥接层：唯一调用 run_agent / runtime.store 的地方（UI 通过它取数）
  main.py    # 启动入口：uvicorn.run(app)，加载运行时图 + PostgresSaver
```

职责边界：
- **app.py** 只持有页面状态（当前 session_id、消息列表、role/store 选择值），通过 api.py 获取数据。
- **api.py** 不 import NiceGUI；封装所有后端调用（list/create/load/send）。
- **main.py** 构建一次 `graph`（`build_runtime_graph()`，默认 PostgresSaver），传给 api/app。

---

## 2. api.py — 接口契约

```python
# ---- 会话列表 ----
def list_sessions(user_id: int) -> list[dict]:
    """runtime.session 按 updated_at 倒序；含 role/store_id 徽章字段。"""

# ---- 新建会话 ----
def new_session(user_id: int, role: str, store_id: int) -> str:
    """生成 uuid4 hex 作 session_id + thread_id（1:1）；不落库，
    首次发送时由 run_agent→_persist 的 create_session 写入。"""

# ---- 读取会话消息（切会话时）----
def load_conversation(thread_id: str) -> list[dict]:
    """graph.get_state(thread_id).values['conversation']（[{role, content}]）；
    空会话返回 []。"""

# ---- 发送一轮 ----
def send(graph, thread_id: str, session: dict, message: str) -> dict:
    """封装 run_agent，返回 {message, status, needs_user_input, result}。"""
```

**关键实现点**：
- `list_sessions` 直接 SQL 查询 `runtime.session WHERE user_id=%s AND status='active' ORDER BY updated_at DESC`（store.py 无此函数，api 层补）。
- `thread_id = session_id`（Spec-2 §2 1:1）。
- 会话标题：V1 取首条用户消息前 20 字；无则「新对话」（`runtime.session.title` 目前 `create_session` 可传，UI 首次发送后补写）。

---

## 3. app.py — 页面结构

### 3.1 布局骨架（NiceGUI）

```
ui.page_title("E-commerce Copilot")

with ui.header():
    ui.label("E-commerce Copilot")          # 标题
    ui.button("＋ 新建对话", on_click=new_dialog.open)

with ui.left_drawer(value=True).classes("w-64"):
    ui.label("会话历史")
    sessions_list = ui.list()               # 动态填充
    ui.label("当前上下文").classes("text-xs")
    context_label = ui.label("客服 · 门店1") # 显示当前会话徽章

with ui.column().classes("grow"):
    chat_area = ui.column().classes("grow overflow-auto")   # 消息气泡
    welcome = ui.column()                                    # 空会话引导
    with ui.row().classes("w-full"):
        msg_input = ui.input(placeholder="请输入问题…").props("outlined dense").classes("grow")
        ui.button("发送", on_click=send_msg)
```

### 3.2 状态（app 内存）

```python
state = {
  "user_id": 1,            # V1 单用户硬编码（无登录）
  "role": "customer_service",   # 当前选择（新建时锁定）
  "store_id": 1,
  "session_id": None,      # 当前会话；None = 未开始
  "thread_id": None,
  "messages": [],          # 当前会话消息渲染缓存
}
```

### 3.3 事件流

```
[新建对话] → new_dialog：role/store 选择 → api.new_session → state 重置 → 空主区 + 引导
[切换会话] → api.load_conversation(thread_id) → 渲染气泡 + 更新徽章
[发送]    → 校验非空 → 追加用户气泡 → api.send(...) → 追加助手气泡（response.message）
           → 会话列表刷新（新会话首次发送后出现，updated_at 置顶）
```

### 3.4 引导文案（空会话，8 意图各一条示例）

```
客服：  "ORD_01_000438 可以退货吗"
运营：  "SKU_01_STOCKOUT_01 缺货风险怎么样"
运营：  "SKU_01_NORMAL_01 需要补货吗"
运营：  "SKU_01_ANOMALY_DROP_01 销售有没有异常"
运营：  "SKU_01_SLOW_01 是不是慢销"
客服：  "ORD_01_000002 物流有没有延误"
客服：  "订单退货政策是什么"   ← knowledge_query
任意：  "ORD_01_000002 物流到哪了"  ← shipping_status 直连
```

引导文案按当前 role 过滤（客服意图仅客服可见）。

---

## 4. 数据流（一次对话轮，完整时序）

```
用户在输入框回车 / 点发送
  → send_msg():
      msg = input.value.strip(); 非空才继续
      chat_area.append(用户气泡 msg)
      input.clear()
      if state.session_id is None:          # 首轮
          state.session_id = api.new_session(user_id, role, store_id)  # 仅生成 id
          state.thread_id = state.session_id
      session = {session_id, user_id, role, store_id}
      resp = api.send(graph, thread_id, session, msg)
      chat_area.append(助手气泡 resp.message)
      api.refresh_sessions()                # 更新左栏（新会话出现/置顶）
  → 异常兜底：气泡显示「处理失败，请重试」（api.send 内 try/except → 不崩溃）
```

**权限/跨店边界**：role/store 新建时锁定后不可变 → guardrails、ISO 隔离由 runtime 天然保证，UI 无需处理。

---

## 5. main.py — 启动

```python
import uvicorn
from nicegui import ui, app as nicegui_app
from copilot.agent.orchestrator import build_runtime_graph
from web.app import build_page

graph = build_runtime_graph()          # PostgresSaver（默认 checkpointer）
build_page(graph)
uvicorn.run(nicegui_app, host="127.0.0.1", port=8000)
```

启动：`python web/main.py` → http://127.0.0.1:8000

**注意**：`build_runtime_graph()` 内部 `_default_checkpointer()` 会尝试 PostgresSaver（连 PG），连不上自动回退 InMemorySaver——但 V1 需 PG 在跑（会话历史跨重启要 DB）。

---

## 6. 依赖

`nicegui` 需装入 conda env（`pip install nicegui`，requirements.txt 补充）。其余（langgraph/psycopg/pydantic）已具备。

---

## 7. 边界与错误处理

| 场景 | 行为 |
|------|------|
| 空消息 | 忽略（发送按钮 disabled 或 return）|
| 无会话时发送 | 自动视为新会话（生成 id）|
| LLM/DB 异常 | 气泡显示「处理失败」，左栏不变，可重发 |
| 切到空会话 | 显示引导文案 |
| 同会话连发 | 正常续答（checkpointer 保存 task/conversation）|

---

## 8. 非目标（V1）

登录鉴权、流式打字机、轨迹渐进展示、会话重命名/删除、历史搜索、多用户切换、移动端适配。

---

## 9. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-20 | 详细设计：模块划分 / api 契约 / 页面结构 / 事件流 / 数据流 |

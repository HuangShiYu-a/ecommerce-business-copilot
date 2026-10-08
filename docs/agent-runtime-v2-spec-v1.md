# E-commerce Business Copilot — Agent Runtime V2 Spec

版本：V0.1（起草中） · 状态：逐节确认中 · 日期：2026-09-19

> **架构演进（2026-09-23，方案 B 已落地）**：运行时已从「意图路由 + Intent Registry」演进为
> **ReAct 工具调用式**（`copilot/agent/react.py`：LLM 看工具目录 → 自主调用 → 确定性工具裁定）。
> 本文档 §8（Router/Intent Registry）、§9.2（中断）等描述的是**已被取代的旧设计**；最新契约见
> `docs/agent-plan-b-react-v1.md`（V1.5.2）与 `react.py`。意图路由代码保留为
> `AGENT_BACKEND=legacy` 回退（DEPRECATED）。

**文档定位**：本文件定义 **Agent Runtime / Conversation Layer**（Agent 运行时层）的契约。它位于现有 Business / Tool / RAG / Workflow / DB 冻结契约**之上**，是新增的一层，**不替代、不推翻底层**。

---

## 1. 定位与边界

### 1.1 分层关系

```
              Agent Application V2
                      │
        ┌─────────────┴─────────────┐
        ↓                           ↓
 Agent Runtime Layer          Business Execution Layer
 (本 Spec 定义)               (现有冻结契约约束)
 Intent/Session/Memory           Tool / RAG / Workflow
 Context/Prompt/Router            HITL / Action / Audit
 Trace/Eval
```

- **Agent Runtime Layer**：回答「用户想干什么 / 上一轮说了什么 / 当前任务缺什么参数 / 是什么角色 / 给模型什么上下文 / 模型调用了什么 / 执行到哪一步」。
- **Business Execution Layer**：继续受原冻结契约约束（Workflow Spec R1–R12、Tool Contract、Database、RAG）。

### 1.2 硬边界（突破契约但守住红线）

| # | 边界 | 依据 |
|---|---|---|
| B1 | **正式结论仍由确定性工具裁定**，LLM 只解释不裁定（补货量/资格/风险） | Workflow Spec R4 |
| B2 | **业务分支只看结构化 State**，禁止「LLM 感觉」作分支 | Workflow Spec R5 |
| B3 | **Action 在确认/审批之后**，禁止 LLM 直写 | Workflow Spec R10 |
| B4 | 角色 / store / permission 一律来自 **Trusted UserContext**（服务端构造），不由 LLM 或用户文本决定 | 本 Spec §4 |
| B5 | 跨 store 读放开 + `source_store` 标注；写仅限当前会话门店（方向 A，D7） | Database / Tool Contract + 方案 B D7 |

### 1.3 项目边界（不进入范围）

- Multi-Agent / MCP / A2A / 复杂 Planning / Self-Reflection —— 明确不做
- 模型路由（多模型切换）—— 不做（单一 deepseek-chat）
- 会话历史摘要 / 上下文压缩 —— P2 暂缓（业务对话短，recent turns 足够）
- 长期记忆只记「员工偏好/习惯」，**业务事实一律查 DB，不进入记忆**（见 §5、§14）

### 1.4 架构形态：单 Agent，两层图

```
              Agent Runtime Graph（编排层，常驻）
                      │
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
     Router      Clarifier      Finalizer
        │
     Dispatcher
        │
   ┌────┴────┐
   ↓         ↓
 Direct Tool  Workflow Subgraph（OP-04/05/CS-06/CS-08…，业务执行）
```

- **Runtime Graph**：Pending Task Check → Intent Router → Guardrails → Intent Registry → Dispatcher → 需要时 Clarifier → Workflow Subgraph 或 Direct Tool → Finalizer（组装回答+Trace）。完整图见 §3.1。
- **Workflow Subgraph**：现有各 workflow（OP-05 等）降级为被 Dispatcher 调用的业务执行子图，内部 Conditional Edge 仍只看结构化 State（B2）。
- 两层通过 **WorkflowInput / WorkflowResult 契约**交互（§3.5），Runtime 不把完整 AgentRuntimeState 传给子图。
- 代码结构细节（父子图如何接、state 如何跨层）在**实现阶段（阶段1 Runtime 竖切）**细化，本 Spec 只定边界。

---

## 2. 需求清单（AR）

### 2.1 P0（必须有）

| AR | 需求 | 说明 |
|---|---|---|
| AR-01 | 意图路由 | 一次 LLM 调用同时产出 intent / workflow / entities / missing_slots |
| AR-02 | 结构化 I/O | 四类 Schema：AgentRequest / RouterResult / ToolCall / AgentResponse |
| AR-03 | 多轮对话 | 会话历史 + 任务状态跨 Run 保留（L1 + L2） |
| AR-04 | 会话持久化 | Session/Thread/Run 分层；thread 用 PostgresSaver 持久化 |
| AR-05 | Slot Filling / 最小澄清 | 缺槽位追问一次、继续原任务，不退出 |
| AR-06 | 角色提示词 | 客服 / 运营 persona，session 级生效 |
| AR-07 | Context Engineering | 上下文按规则组装（§10） |
| AR-08 | 工具目录 + Schema | 每个工具暴露 name/description/参数 Schema 给 LLM |
| AR-10 | 执行轨迹 | 结构化 Trace + Domain Event（§12） |
| AR-11 | 校验护栏 | 路由结果 / 参数 / 权限校验（复用 Tool 8 错误码） |
| AR-13 | Agent 评测 | 全链路评测（Eval V2 文档）+ 33 SC 回归门 |
| AR-19 | 任务恢复 / 续答 | 三种中断分类；「继续」从 checkpoint 恢复，不重算正式结果 |
| AR-20 | 路由失败处理 | 错误路由检测、重路由预算、澄清降级、错误结果自愈 |

### 2.2 P1（应该有）

| AR | 需求 | 说明 |
|---|---|---|
| AR-09 | RAG 检索注入 | **设计 P0、实现 P1**：先定义注入接口，实现后置 |
| AR-12 | 可观测 | run_log：run_id/session/intent/tools/结果/error |
| AR-14/15 | 长期记忆 | staff_user_memory 表 + 写入策略（§9） |
| AR-18 | 轨迹渐进显示 | NiceGUI 流式展示执行过程 |

### 2.3 暂缓 / 不做

历史摘要 · 上下文压缩 · **通用重试策略（P2 暂缓；Runtime 保留有界路由恢复，见 §10）** · 模型路由 · MCP / Multi-Agent / A2A / Planning / Reflection

---

## 3. 架构

### 3.1 单 Agent 两层图

```
                        User Input
                            ↓
                 Pending Task Check（有挂起任务？）
                   │                     │
           有（继续）                 无（新任务）
                   │                     ↓
            Slot Fill /           Intent Router（LLM 结构化）
            Confirmation                ↓
                   │               Guardrails（校验）
                   │                     ↓
                   │             Intent Registry（确定性映射）
                   │                     ↓
                   └──────────┬──────────┘
                              ↓
                        Dispatcher
                        /        \
                 Direct Tool   Workflow Subgraph
                               (OP-04/05/CS-06/CS-08…，业务执行)
                              ↓
                       Tool / RAG / HITL
                              ↓
                         Finalizer（AgentResponse + Trace）
```

- **Runtime Graph**（Agent Runtime Layer）：负责编排。Pending Task Check → Router → Guardrails → Intent Registry → Dispatcher → 需要时 Clarifier → 执行 → Finalizer。
- **Workflow Subgraph**（Business Execution Layer）：现有各 workflow 降级为被 Dispatcher 调用的业务执行子图，内部 Conditional Edge 仍只看结构化 State（B2）。
- **Pending Task Check 优先于普通路由**：session 有挂起任务（等待槽位 / 确认）时，输入直接作为 slot-fill / confirmation 继续原任务（§9）；无挂起任务才走完整意图路由。

### 3.2 Runtime Graph 节点职责

| 节点 | 职责 | 输入 → 输出 |
|---|---|---|
| Pending Task Check | 检查是否有挂起任务，优先继续 | input + task.status → 继续 / 新任务 |
| Router | 意图 + 槽位抽取（一次 LLM 调用），**不含 workflow** | message + context → RouterResult |
| Guardrails | 校验 RouterResult（意图合法 / 实体匹配 / 权限）| RouterResult → 通过 / 重路由 / 澄清 |
| Intent Registry | 确定性映射 intent → 执行路径 | RouterResult → Direct Tool 或 Workflow Subgraph |
| Dispatcher | 按 Registry 分发执行 | 执行路径 → 执行 |
| Clarifier | 缺槽位 / 语义歧义时向用户发问并回收 | missing_slots / 歧义 → 问题 → 用户补充 |
| Finalizer | 组装最终回答 + Trace + 落 AgentResponse | 执行结果 → AgentResponse |

### 3.3 执行路径

- **Direct Tool**：意图简单、无需完整 workflow 流程（如 `inventory_query` → 直接 T-Q-03）。
- **Workflow Subgraph**：意图对应业务 workflow（如 `stockout_risk` → OP-04 子图，内部走 N0→…→Nn）。

### 3.4 State 归属（两层分家）

- **AgentRuntimeState** 归 Runtime Graph：session / conversation / routing / task / context / execution（§5）。
- **WorkflowState** 归各 Subgraph：各自业务字段（如 OP-05 的 sku_ids / recommendation / confirmation）。
- 父子图如何接、state 如何跨层传 —— **实现阶段（阶段1 Runtime 竖切）细化**，本 Spec 只定边界。

### 3.5 Runtime ↔ Workflow 接口契约（两层解耦关键）

Runtime **不把完整 AgentRuntimeState 传给子图**，只传最小执行输入，回收结构化结果。

```
WorkflowInput：
{ task_id, user_id, store_id, intent, slots, context_refs }

WorkflowResult：
{ formal_result, status, evidence_refs, next_step, confirmation_required }
```

- `context_refs`：指向会话历史 / 记忆 / RAG 的引用（而非拷贝全文）。
- Workflow Subgraph 内部仍用各自 WorkflowState；与外层只经此契约通信。

---

## 4. 身份与权限

### 4.1 四层概念

| 概念 | 是什么 | 示例 |
|---|---|---|
| 身份 identity | 具体是谁 | user_id（哪个员工）|
| 角色 role | 是哪类人 | 客服 customer_service / 运营 operations |
| store_id | 数据范围：能看哪个店 | STORE_01 / STORE_02 |
| permission | 能做什么操作 | 查订单 / 建退货单 |

### 4.2 权限模型

```
权限 = 角色（允许的工具集） × store_id（作用域）
```

- 角色 → 工具范围映射（初版，随业务扩展）：
  - **客服**：T-Q-01~07（查询）、T-A-09（退货资格）、T-X-01（退货申请）、T-X-02（工单）
  - **运营**：T-Q-03、T-A-02/04/05/06/07（分析）、T-R-01（补货建议）
- store_id 是**独立数据范围维度**，不由角色自动带；会话建立时绑定（首轮客户端声明，option b+），跨店读放开并标注 source_store、跨店写 FORBIDDEN（方向 A / D7，B5）。

### 4.3 身份注入：Trusted UserContext（非真实认证）

- **命名诚实**：V1 不实现真实登录认证，**不称其为 Authentication**。它是 **Trusted UserContext / Demo Identity Context**——由服务端创建并注入 Runtime Context。
- **B4** 依然成立：role / store_id / permission **一律由服务端构造**，不由 LLM 或用户文本决定（用户说"我是管理员"无效）。
- V1 简化：UI 发起会话时选择「角色 + store」→ 服务端构造 `UserContext(user_id, role, store_id, permissions)`，复用现有 `copilot.context.UserContext`。

### 4.4 审批 = 二次确认

- Action 工具（T-X-01 等）标记 `requires_approval` 元数据；执行前必须 HITL 确认（R10）。
- 审批人**默认 = 本人**（二次确认，防误操作）；保留 approval 元数据字段，未来可扩展为管理员审批制。
- 现有 `Tool.requires_approval` / `Tool.risk` 复用。

---

## 5. State 模型

### 5.1 记忆分层（L0–L3）

| 层 | 定义 | 载体 |
|---|---|---|
| L0 当前输入 | 用户这一句话 | 本次 Run 入参 |
| L1 会话历史 | 当前 Session 的对话历史 | AgentRuntimeState.conversation |
| L2 任务状态 | 正在执行什么 / 已拿到什么 / 缺什么 / 执行到哪 | AgentRuntimeState.task |
| L3 长期记忆 | 员工偏好 / 工作习惯 / 历史摘要 | `staff_user_memory` 表（§14）|

**边界铁律**：订单事实 / 库存 / 价格 = 业务事实 = **每次查 DB，不进 Memory**。记忆只记「这个运营偏好 7 天窗口、常用表格」。

### 5.2 AgentRuntimeState 分区

```
AgentRuntimeState
├── session     session_id / user_id / role / store_id / created_at
├── conversation  messages（L1）/ summary（预留字段，V2 启用，见 §2.3）
├── routing     intent / workflow / confidence / route_reason
├── task        slots / missing_slots / status / current_step（L2）
├── context     role_prompt / memory（L3）/ retrieved_knowledge / runtime_context
└── execution   run_id / trace / error
```

### 5.3 WorkflowState（独立）

各 workflow 只关心自己的业务字段，例如 OP-05：`sku_ids / inventory_data / recommendation / confirmation`。不混入 Runtime 编排字段。

### 5.4 task 状态机（5 态）

| 状态 | 含义 | 进入时机 |
|---|---|---|
| `running` | 正在执行 | 收到消息，开始处理 |
| `waiting_user_input` | 等用户输入 | **HITL 确认** 或 **缺槽位澄清** |
| `completed` | 正常结束 | 任务完成 |
| `terminated` | 业务终止 | 订单不存在 / RULE_CONFLICT / 权限拒绝等 |
| `failed` | 异常失败 | LLM 超时 / 工具异常 / 运行时错误 |

- `interrupted` **不单列**：HITL 中断 → `waiting_user_input`；错误中断 → `failed`。
- 状态机是「继续」恢复判定（§9）、UI 显示、评测断言的依据。

---

## 6. Session / Thread / Run

### 6.1 定义

| 概念 | 定义 |
|---|---|
| **Run** | 一次用户输入触发的一次完整执行（request → response）。日志 / Trace 最小单位。 |
| **Session** | 业务概念：一段持续对话，包含多个 Run。UI 的"会话"。 |
| **Thread** | 技术概念：LangGraph 的持久化执行上下文（checkpoint 载体）。 |

### 6.2 映射关系

- **一个 Session = 一个 Thread（一对一）**：同一会话复用同一 thread_id → 多轮记忆与「继续」生效。
- **一次用户输入 = 一个新 Run**：run_id 每次生成，用于 Trace / 日志 / 评测。
- thread_id = checkpoint 的 key；session 元数据存 `session` 表（§14）。

### 6.3 生命周期

```
Session 创建（选角色+store，定 thread_id）
   → Run R001  …  Run R002  …（每次输入一个新 Run）
   → Session 结束（UI 会话列表管理）
```

---

## 7. 结构化 I/O（AR-02）

### 7.1 原则：骨架固定，值变化

四类 Schema 由本项目**预定义**；LLM 每次只是往固定骨架里填不同的值。变化的只有 values，骨架不变（类比：表结构固定、行数据随便填）。

固定骨架三要素：**① 意图枚举清单 ② 每个意图的槽位定义 ③ 每个工具的参数 Schema**。

### 7.2 AgentRequest（输入信封）

```json
{ "session_id": "...", "user_id": "...", "role": "operations",
  "store_id": 1, "message": "..." }
```

### 7.3 RouterResult（路由结果）

```json
{ "intent": "stockout_risk",
  "entities": { "sku_code": "SKU_01_STOCKOUT_01" },
  "missing_slots": [], "low_confidence": false }
```

- `intent` 从枚举取；`entities` 字段由该意图的槽位定义决定；`low_confidence` 为软信号，**不作硬路由依据**（guardrails 校验为准）。
- **不含 `workflow`**：执行路径由 Intent Registry 确定性决定（§8.3），不由 LLM 输出。

### 7.4 ToolCall（工具调用）

```json
{ "tool": "analyze_stockout_risk", "arguments": { "sku_ids": ["SKU_01_STOCKOUT_01"], "horizon_days": 7 } }
```

- `arguments` 的结构由**该工具的参数 Schema** 决定（AR-08 工具目录）。

### 7.5 AgentResponse（输出信封）

```json
{ "message": "...",
  "status": "completed",
  "trace_id": "...",
  "interaction": { "needs_user_input": false, "approval_required": false },
  "result": { /* 结构化业务结果，可选 */ } }
```

- **自然语言回答（message）与机器可读结果（result）分开**。
- `interaction` 驱动 UI 交互（是否等输入 / 是否要确认）；`result` 携带结构化业务结果，供 UI / 评测消费。
- Schema 现在定稿；实现落阶段 1。

---

## 8. Router 与 Intent Registry（AR-01）

### 8.1 Router 职责

Router 只做**语义理解**，不做执行结构决策：

```
一次 LLM 结构化调用 → RouterResult（intent / entities / missing_slots / low_confidence）
```

**不含 workflow**。执行路径由 Intent Registry 确定性决定（§8.3）。

### 8.2 意图路由 vs workflow 路由

| | 意图路由 | workflow 路由 |
|---|---|---|
| 回答 | 用户想干什么（语义层）| 用哪条业务线执行（执行层）|
| 负责方 | Router（LLM）| Intent Registry + Dispatcher（确定性系统）|

分工原则：**LLM 回答「用户想做什么」，系统回答「这个意图怎么执行」**。避免让模型同时决定语义与执行结构（消除「选错 workflow 再纠错」的冗余环节）。

### 8.3 Intent Registry（确定性映射）

```yaml
inventory_query:            direct: T-Q-03
stockout_risk:              workflow: OP-04
restock_recommendation:     workflow: OP-05
order_query:                direct: T-Q-04
shipping_status:            direct: T-Q-05
return_eligibility:         workflow: CS-08
sales_anomaly:              workflow: OP-08
slow_moving:                workflow: OP-03
product_health:             workflow: OP-07
knowledge_query:            direct: T-K-01
out_of_scope:               direct: none（优雅回复）
```

- Dispatcher 查 Registry 得执行路径（direct tool / workflow），**不依赖 LLM 输出 workflow**。
- Registry 是配置 / 代码，随业务扩展。

### 8.4 路由模式（live / dryrun）

| 模式 | 路由 | 兜底 |
|---|---|---|
| **live**（生产）| LLM 结构化路由 → Guardrails | 规则路由（实体预抽取 / LLM 失败回退）|
| **dryrun**（测试 / 评测）| 规则路由（确定性）| 无 LLM 调用 |

- 规则路由承担四类角色：① 实体 / 模式预处理器（order_id / SKU / 单号 / 日期 / 数量 / 明确 yes-no）② dryrun 路由器 ③ LLM 失败回退 ④ 硬约束校验器。
- **规则不抢在 LLM 前决定意图**（避免退回「包含库存二字 → OP-04」的死板模式）；语义判断交给 LLM。

### 8.5 超范围处理

无匹配 intent → `out_of_scope` 优雅回复（"该问题不在我的能力范围"），不崩溃、不猜。

### 8.6 意图清单（初版，随业务扩展）

`inventory_query / stockout_risk / restock_recommendation / order_query / shipping_status / return_eligibility / sales_anomaly / slow_moving / product_health / knowledge_query / out_of_scope`

（`continue` **不再作为普通意图**——由 Pending Task Check 处理，见 §3.1 / §9）

### 8.7 Effective Tool Catalog（按角色过滤）

- LLM 看到的工具目录**不是全部 Tool**，而是经过权限过滤的 **Effective Tool Catalog**。
- 客服 Agent 不应"看见" `calculate_restock_recommendation`；运营 Agent 不应"看见"建退货单工具。靠过滤而非靠模型自觉"不调用"。
- 实现：`Tool.allowed_roles` 元数据 + 角色 → 过滤后目录（见 AR-08 / §4）。

---

## 9. Slot Filling 与任务恢复（AR-05 + AR-19）

### 9.1 Slot Filling

- 每个意图声明 `required_slots`（如 `order_query` 需要 `order_id`）。
- 缺槽位 → **Clarifier 问一个精准问题** → 用户补充 → **同一任务上下文继续，不重开**。
- 这是「Agent」与「一问一答机器人」的关键区别之一。

### 9.2 三种中断分类

| 类型 | 例子 | 「继续」行为 |
|---|---|---|
| **HITL 中断** | 补货确认 | resume 值 → 正常往下走 |
| **错误中断（可恢复）** | LLM 超时 / 工具异常 | 从最后成功 checkpoint 继续，**不重算已完成正式结果** |
| **终止中断（不可恢复）** | 订单不存在 / RULE_CONFLICT | 不可恢复；说明原因，进入新任务 |

### 9.3 「继续」语义

- 模型本身无状态，**连续性由运行时提供**：每次调用前把 (L1 历史 + L2 任务状态 + L3 记忆) 重组喂回。
- 「继续」= 同 session 同 thread 重新 invoke → 从 checkpoint 恢复 → **跳过已完成步骤**。
- 已算出的正式结果（如资格判定）**不重算**——确定性结果可复用。

### 9.4 可恢复点

- LangGraph **每步自动 checkpoint**（免费）；显式业务可恢复点只有两个：
  1. **HITL 确认处**（用户确认 → resume）
  2. **正式结果算出后**（回答被中断时直接续答，不重算）
- 错误中断恢复 = 从**最后一个成功 checkpoint** 继续，只重跑未完成部分。

### 9.5 没给订单号能继续吗

- **task state 里已有**（前面收集过）→ 直接复用，继续。
- **真缺** → 不猜，触发 Slot Filling 问一次，补齐后继续同一任务。

### 9.6 正式结果复用边界

- **同一次 Run 内的中断恢复**：可直接复用已算出的正式结果。
- **跨时间 / HITL 确认后**：业务事实可能变化，**不得无边界复用**。
- **Action 前重验证**：高风险写操作（T-X-01 等 `requires_approval` / `audit_required` 工具）在执行前**必须重新验证关键业务事实**（库存 / 资格 / 当前状态），再走确认与审批（R10）。
- 每个正式结果带 `source_timestamp` / `result_version`，供复用判定。

---

## 10. 路由失败处理（AR-20）

### 10.1 错误分类

| 类型 | 例子 | 后果 |
|---|---|---|
| 误分类（选错 workflow）| 问物流 → 进 OP-05 | T-R-01 拿 order_no 当 sku → NOT_FOUND，答非所问 |
| 实体错配 | 意图对，抽到 sku 而非 order_id | 工具查不到 |
| 语义歧义 | 「帮我查一下这个」| 低置信，须澄清 |
| 矛盾信号 | 消息同时含 sku 与订单号 | 须选或问 |
| 超范围 | 「写首诗」| out_of_scope |
| router 自身失败 | LLM 超时 / 解析失败 | 回退规则路由 → 仍失败 → 请用户重述 |

### 10.2 有界性（为什么路由错误不可怕）

- **绝大多数工具只读**（Query/Analysis/Recommendation）→ 进错 workflow 只是答非所问，**零副作用**，用户一句纠正。
- **Action 有审批**（§4.4）→ 误路由到 Action 也会在确认环节被拦 → **不会错误写库**。

### 10.3 处理机制

1. **执行前校验（guardrail）**：workflow 存在 / 实体类型匹配 / 权限 → 不通过则重路由一次。
2. **workflow 契约声明**：每个 workflow 声明 `required_slots` + 接受实体类型，Dispatcher 执行前比对。
3. **重路由预算**：最多 **1 次**自动重试（带拒绝原因回喂 LLM）→ 超限转 Clarifier 问用户。
4. **错误结果自愈**：已执行的错误只读结果**直接丢弃** → 重路由 → 主动道歉纠正（"抱歉理解错了，你是想问 X 对吗？"）。

### 10.4 分级重试

| 情形 | 谁处理 |
|---|---|
| 自动可纠正（schema 不合规：实体类型 / workflow 不存在）| agent 自动重路由 1 次 |
| 语义歧义（无法自动判定）| 问用户，用户选完继续 |

区分标准：**能靠规则判断的 → 自动；需要人判断的 → 问**。

### 10.5 自动恢复边界（硬规则）

- **可自动恢复**（schema 级，规则可判）：workflow 不存在 / 实体类型不匹配 / 结构化结果非法 / route schema 错误。
- **不可自动猜**（须 Clarifier 问用户）：语义歧义 / 指代不明 / 多意图都可能 / 用户突然改变任务 / 高风险 Action 目标变化。
- **硬规则**：**已执行过的 Action 不允许因误路由而自动逆转**。错误结果自愈（§10.3 第 4 点）**只适用于只读操作**。

---

## 11. Context Engineering（AR-07）

### 11.1 组装块（按顺序喂给 LLM）

```
① System Prompt（角色 + 能力边界，session 级固定）
② 身份 / 权限上下文（role / store）
③ 任务状态（intent / 已有槽位 / 缺什么）→ 紧凑 JSON
④ 会话历史（最近 N 轮，默认 5–8 轮）
⑤ 长期记忆（该用户偏好，按需注入）
⑥ RAG 检索结果（命中知识，按需注入）
⑦ 工具结果（最近一次工具调用输出）
⑧ 当前用户消息
```

### 11.2 五大原则

1. **按需注入，不全塞**——只注入当前任务相关的历史片段
2. **V1 截断**——超过 recent-N 窗口 → 直接截断旧轮（**不生成摘要**；摘要为 V2 预留，见 §2.3）
3. **结构化优于长文本**——task state 用紧凑 JSON
4. **分块有边界**——System 指令 / 数据 / 历史分开放，防 prompt injection
5. **Token 预算**——给每块设上限，超限截断

### 11.3 信任边界

```
System / Developer Instructions    ← 可信指令
Trusted Runtime Context            ← 身份 / 任务 / 记忆（服务端构造）
User Message                       ← 用户输入（不可信）
Retrieved Knowledge / Tool Result  ← 数据 / 证据，不是系统指令
```

- RAG 内容与 Tool Result 视为**数据 / 证据**，不作为新的系统指令（防 prompt injection；知识入库 pgvector 后尤为重要）。

---

## 12. 角色提示词（AR-06）

### 12.1 内容（7 项）

1. **角色定义**：我是谁（客服 / 运营 Copilot）
2. **职责范围**：能做什么（哪些意图 / 功能）
3. **边界规定**：不能做什么（不编造、不裁定正式结论、权限外不查、Action 要确认）
4. **行为准则**：事实→查工具、规则→查知识、不确定→说明
5. **数据域**：当前 store 范围
6. **回复风格**：语言 / 长度 / 格式偏好
7. **审批规则**：哪些操作需确认

### 12.2 双 persona

- **客服 Copilot**：订单 / 物流 / 售后 / 退货资格 / 知识问答
- **运营 Copilot**：库存 / 补货 / 缺货风险 / 销售分析 / 商品健康

### 12.3 生命周期

- **session 级生效**（不是单次问答）：一个 Session 绑定一个角色，整个对话用同一 persona。
- **一个会话一个角色**；切换角色 = 开新 Session（对话内动态切换复杂度高、权限边界模糊，不推荐，留 P2）。

---

## 13. Trace（AR-10）

### 13.1 定义

Trace = 一次 Run 从头到尾的**步骤记录**（可观测性核心），回答：agent 干了什么 / 到哪步出错 / 为什么这么答。

### 13.2 Domain Trace Event（契约）

```json
{ "type": "tool_completed", "run_id": "R001", "step": "stockout_check",
  "tool": "analyze_stockout_risk", "status": "success", "payload": {}, "timestamp": "..." }
```

**事件枚举**：`intent_detected / tool_called / tool_completed / knowledge_retrieved / human_requested / human_confirmed / step_completed / step_failed / final_response`

### 13.3 原则

- **不暴露 LLM 原始思考**（reasoning_content / CoT）——内容不可控、含错误中间态，不适合正式工具。
- **Trace Adapter**：LangGraph 事件流 → Domain Trace Event → UI / 日志。UI 不直接消费 LangGraph 事件（解耦，未来换 UI 不重写 Agent）。

### 13.4 用途

① UI 渐进展示（用户看到 agent 在工作）② 调试定位（错在哪一步）③ 评测断言（是否按预期步骤走）。**业务审计不属于 Trace**——写操作的审计走既有 `audit_logs`（Tool Contract `audit_required` / R10），run_log 只做可观测，不取代审计。

---

## 14. 持久化（AR-04）

### 14.1 Checkpoint

- 用 **LangGraph PostgresSaver** 持久化 thread 状态，**不自建 checkpoint 体系**（避免两套事实来源）。
- 业务事实仍查 PG；thread 状态存 checkpoint 表；session / 记忆 / 日志存本层新增表。

### 14.2 新增表（细节见《Runtime Database Addendum》）

- `session`：会话元数据（session_id / user_id / role / store_id / thread_id / 状态 / 时间）
- `staff_user_memory`：长期记忆（user_id / memory_type / memory_key / memory_value / confidence / source / 时间）
- `run_log`：可观测日志（run_id / session_id / intent / workflow / tools / result / error / latency / token）

### 14.3 长期记忆写入策略（V1）

- **何时写**：仅 Run 正常完成（completed）后触发。
- **谁触发**：Finalizer 后的记忆提取节点（非每轮）。
- **写什么**：仅员工偏好 / 工作习惯（"以后库存分析默认看 7 天"）。
- **高置信才写**：提取结果需显式高置信，否则不写。
- **不写**：业务事实（订单 / 库存 / 价格，一律查 DB）、敏感信息。
- **更新 / 删除**：同 key 覆盖更新；用户可清除。

---

## 15. 评测（AR-13）

### 15.1 全链路评测链

```
input → intent → slot → clarification → workflow → tool → tool_args
      → RAG retrieval → formal result → final answer → trace
```

### 15.2 回归门

**33 SC + 71 现有测试穿过新 Router 必须全 PASS**（不回归）。

### 15.3 negative cases

错误路由测试：误分类 / 实体错配 / 歧义 → 断言期望的纠正行为。

细节见《Agent Evaluation V2》文档。

---

## 附：8 条设计闸门（实现阶段必须守住）

1. Agent Runtime V2 是**新增层**，不随意修改 Frozen Business / Tool / RAG / Workflow。
2. **两层编排**：Runtime Graph + Workflow Subgraph。
3. **Session / Thread / Run** 定义清楚，不混用。
4. Checkpoint 用 **PostgresSaver**，不自建 checkpoint 体系。
5. Structured I/O 明确拆成 **Request / Router / Tool / Response** 四类 Schema。
6. Trace 先定义 **Domain Event 契约**，再适配 LangGraph Streaming。
7. Role / store / permission 全部来自 **Trusted UserContext**（服务端构造），不由 LLM 或用户文本决定。
8. Evaluation 从「Scenario 回归」升级为「**Agent 全链路评测**」。
9. Router 只出语义（intent / entities / missing_slots），**执行路径由 Intent Registry 确定性决定**。
10. 有 pending task 时**优先继续当前任务**，不重新完整意图路由。

---

## 附：AR 索引

| AR | 需求 | 优先级 |
|---|---|---|
| AR-01 | 意图路由 | P0 |
| AR-02 | 结构化 I/O | P0 |
| AR-03 | 多轮对话 | P0 |
| AR-04 | 会话持久化 | P0 |
| AR-05 | Slot Filling | P0 |
| AR-06 | 角色提示词 | P0 |
| AR-07 | Context Engineering | P0 |
| AR-08 | 工具目录 + Schema | P0 |
| AR-09 | RAG 检索注入 | P1 |
| AR-10 | 执行轨迹 | P0 |
| AR-11 | 校验护栏 | P0 |
| AR-12 | 可观测（run_log）| P1 |
| AR-13 | Agent 评测 | P0 |
| AR-14/15 | 长期记忆 | P1 |
| AR-16/17 | 历史摘要 / 上下文压缩 | 暂缓 |
| AR-18 | 轨迹渐进显示 | P1 |
| AR-19 | 任务恢复 / 续答 | P0 |
| AR-20 | 路由失败处理 | P0 |

---

## 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V0.1 | 2026-09-19 | 首版起草：意图路由式 Runtime（§8 Intent Registry、§9.2 非 interrupt HITL）|
| V0.2 | 2026-09-23 | **架构演进标注**：方案 B（ReAct 工具调用式）已落地，§8/§9.2 被取代；新契约见 `react.py` 与 `docs/agent-plan-b-react-v1.md`；意图路由保留为 `AGENT_BACKEND=legacy` 回退 |
| V0.3 | 2026-10-08 | **B5 语义同步（P5）**：跨 store 读取放开 + source_store 标注、写仅限本店（方向 A / D7），对齐实际实现；store 表述改为"会话绑定（首轮声明）+ 数据范围" |

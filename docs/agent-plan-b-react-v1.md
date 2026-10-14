# 方案 B — LLM 居中工具调用式智能体：实现分析与实施规划

> 版本：**V1.5.2（已确认决策，待实施；V1.5.2 采纳 ctx 注入定案 + UNSET 持久化 + UI 状态派生 + 中低项折叠，随后收敛审查）**
> 日期：2026-09-21
> 定位：Agent Runtime 层演进的实施规划文档（**非冻结基线**；不推翻任何 Frozen 契约）
> 上游：`docs/agent-runtime-v2-spec-v1.md`（本方案落地时需同步修订其中两处，见 §10）
> 来源：2026-09-20/21 三轮代码审查 + DeepSeek live 实测 + 两窗口交叉评审，决策均经 Project Owner 拍板

---

## 0. 一句话概括

把现行「**意图闭集 + Registry 固定映射**」的路由式编排，替换为「**LLM 看工具目录 → 自主调用 → 确定性工具产出结论 → LLM 汇总答案**」的 ReAct 智能体；补货/退货等审批流程保留固定 workflow；**R4/R5/R10 三条红线以结构性设计保持**。

---

## 1. 背景与动机

### 1.1 现状架构（路由式）

```
pending_check → router（LLM/规则意图分类，12 枚举闭集）
  → guardrails（角色权限）→ resolver（补槽）→ clarify（缺槽反问）
  → dispatcher → tool_node / workflow_node → finalize（模板 + LLM 润色）
```

- 意图枚举 12 个，`REGISTRY` 确定性映射到单工具或薄 workflow
- LLM 的角色：意图分类器 + 澄清生成器 + 模板润色器

### 1.2 审查发现的核心缺陷（2026-09-21 全量审查）

| # | 缺陷 | 严重度 |
|---|---|---|
| 1 | LLM 被 12 意图框死：无法组合工具、无法多跳推理（「对比两个 SKU 谁该优先补货」直接 out_of_scope）| 高 |
| 2 | 长期记忆**只写不读**（`get_memory` 定义后全仓无调用点）| 高 |
| 3 | 知识问答空转：T-K-01 只回标题列表，LLM 从未基于检索内容生成答案 | 高 |
| 4 | HITL confirm 话术硬编码「补货建议生效」（退货确认也回这句）；confirm 后不真正执行 Action | 高 |
| 5 | `effective_catalog`（Spec §8.7）是运行时死代码，LLM 从未见过工具目录 | 中 |
| 6 | 无摘要的 6 轮截断对话记忆；SC-ISO-001 基线断裂（已修复同步）| 中 |

### 1.3 需求定义（Project Owner 确认）

> 大致是一个「LLM 居中的工具调用式智能体」：LLM 看到 12 个工具的目录和参数，能自主决定"这个问题该调 get_order(order_no=xxx)"；命中补货/退货这类需要审批的多步流程才走固定 workflow；其余问题（知识问答、跨工具组合、闲聊、能力咨询）由 LLM 自由处理。保留 R4/R5 安全红线（正式结论仍来自确定性工具，LLM 不裁定数值）。

---

## 2. 技术可行性验证（实测记录，非推断）

### 2.1 技术栈核实（2026-09-21）

| 前提 | 版本/状态 | 结论 |
|---|---|---|
| langgraph | 1.2.11；`create_react_agent` / `ToolNode` / `PostgresSaver` 可导入；**支持 `interrupt_before/after`** | ✅ |
| langchain-core / langchain-openai | 1.6.3 / 1.6.2；`bind_tools` 已在现行 `llm_router.py` 生产使用 | ✅ |
| fake LLM | `GenericFakeChatModel` / `FakeListChatModel` 可导入 | ✅ |
| 工具 Input schema | 12 工具**全部有 pydantic `input_model`**，`args_schema` 零额外工作 | ✅ |
| 审批中断先例 | `copilot/agent/op05.py`（S4.4 竖切）**已用 `interrupt()` + `Command` resume** | ✅ 仓库内有先例 |
| 测试基线 | **2026-09-21 复核：134 passed / 1 failed**。SC-ISO-001 场景数据被并行窗口还原回 FORBIDDEN，与方向 A 读放开代码冲突（本文档撰写时曾实测 135 绿，其后磁盘态漂移）| ⚠️ W0 先修复（见决策 D7）|

### 2.2 DeepSeek function calling live 实测（2026-09-20，真实 API）

| 场景 | 输入 | 结果 |
|---|---|---|
| C1 明确调用 | "SKU_01_STOCKOUT_01 库存还剩多少" | `get_inventory(sku_code='SKU_01_STOCKOUT_01')` ✓ |
| C2 多工具组合 | "ORD_01_000438 能退货吗，另外物流到哪了" | **一次输出两个 tool_call**（check_return_eligibility + get_shipping_status）✓ |
| C3 闲聊 | "你好，很高兴认识你" | 不调工具，直接回答 ✓ |
| C4 模糊 | "帮我看看那个东西" | 不调工具，主动向用户澄清 ✓ |
| C5 参数抽取 | "订单 ORD_01_000002 的物流状态是什么" | `get_shipping_status(order_no='ORD_01_000002')` ✓ |

**结论：地基成立。** 不需要"路由闭集"，DeepSeek 完全能自主决定调哪个工具、传什么参数、何时反问。

### 2.3 条件多跳 ReAct spike 实测（2026-09-22，决定性验证）

> 背景：并行多工具（C2）已证明，但"Observation → 再决策"的条件多跳此前未验证——这是方案 B 成立性的最大未知数。G1 前先行 spike（脚本 `db/probe_multihop.py`，真实 API，手动 ReAct 循环）。

| 场景 | 输入 | 观测到的链路 | 判定 |
|---|---|---|---|
| S1 条件多跳 | "SKU_01_STOCKOUT_01 有没有缺货风险？如果有，帮我分析原因" | `analyze_stockout_risk`→HIGH/5天 → **条件触发**第二跳 `get_inventory`(8<20) + `analyze_sales_anomaly`(+38%) → 综合回答（数值全部来自工具观察，无编造）| ✅ |
| S2 条件早停 | "SKU_01_NORMAL_01 有没有缺货风险？如果有，帮我分析原因" | `analyze_stockout_risk`→LOW/90天 → **不再深挖**，直接回答"无需进一步分析" | ✅ 条件性成立 |

**结论：DeepSeek 具备真正的条件多跳 ReAct 能力（非无脑多跳，非纯并行工具调用）**——方案 B"从 Tool Router 到 Tool-Orchestrator"的核心论证获得实证。仍属小样本，G1/G2 需批量复测确认稳定性。

---

## 3. 目标架构

### 3.1 架构图

```
用户消息
  → [前置节点] Workspace Mode（UNSET=交集目录 / 客服 / 运营）+ LLM 出 Domain 建议（经 request_capability 通道，见 §3.3）
  → ReAct 循环（create_react_agent + ToolNode）：
      LLM 看到 effective_catalog（按角色过滤的工具目录）
      → 自主决定：调工具 / 调审批 workflow / 直接回答 / 反问澄清
      → 工具执行（确定性，经 run_tool：ISO 守卫 + 错误语义不变）→ 结果回喂
      → 继续决策 / 汇总输出
  → 审批 workflow（OP-05 / CS-08）：结构化结果 → interrupt() 挂起
      → 用户确认/拒绝 → Command(resume) 续跑 → 执行/终止 + 审计
  → 出口：_persist（session/run_log/记忆）+ trace + response 信封（契约不变）
```

### 3.2 LLM 工具目录设计（关键）

**直连工具（10 个，进 LLM 目录）：**

| tool_id | 工具 | 客服 | 运营 |
|---|---|---|---|
| T-Q-03 | 库存查询 | ✓ | ✓ |
| T-Q-04 | 订单查询 | ✓ | ✓ |
| T-Q-05 | 物流查询 | ✓ | ✓ |
| T-K-01 | 知识检索（RAG）| ✓ | ✓ |
| T-A-01 | 物流延误分析 | ✓ | ✓ |
| T-A-09 | 退货资格判定 | ✓ | ✓ |
| T-A-04 | 慢销筛选（mode=slow_moving）| ✗ | ✓ |
| T-A-05 | 商品健康度 | ✗ | ✓ |
| T-A-06 | 销售异常 | ✗ | ✓ |
| T-A-07 | 缺货风险 | ✗ | ✓ |

**workflow 工具（2 个，进 LLM 目录）：**

| 工具 | 可见角色 | 内部流程 |
|---|---|---|
| OP-05 补货建议 workflow | 运营 | T-R-01 建议（内置）→ HAS_RECO → interrupt 确认 → **确认=记录确认事件**（V1 无采购单写入）|
| CS-08 退货 workflow | 客服 | T-A-09 资格判定 → eligible → interrupt 确认 → **T-X-01 建单（内置）+ 审计** |

**内置件（不进 LLM 目录）：** T-R-01、T-X-01。理由见 §3.4 R10。

**Meta-tool（恒在，所有模式可见）：** `request_capability(domain)` —— LLM 判断任务需要超出当前 Workspace Mode 的能力时调用；**仅发起请求，权限变更必须用户确认**（见 §3.3 D10=a+）。类比 Unix `sudo`：不调业务数据、不改业务状态，是运行时**能力协商机制**，非业务命令。

**各角色实际可见目录：**
- 运营：10 直连 + OP-05 + request_capability = **12 个条目**
- 客服：6 公共直连 + CS-08 + request_capability = **8 个条目**
- UNSET 模式：**6 个公共工具 + request_capability = 7 个条目**

### 3.3 角色策略（决策 D8/D9/D10：Identity · Workspace Mode · Business Domain 三分离）

**核心原则：LLM 可以判断业务域，但永远不能获得或改变能力边界。** 三个概念彻底拆开：

| 概念 | 含义 | 由谁决定 | 作用 |
|---|---|---|---|
| ① Identity / Session Context | 用户身份与会话上下文 | V1=Demo Session；生产=Auth | 身份载体 |
| ② Workspace Mode（Capability Profile）| 当前会话"以什么能力集工作"（UNSET / CUSTOMER_SERVICE / OPERATIONS）| **V1=UI 显式切换**（保留零预选体验）| 决定工具目录过滤 |
| ③ Business Domain | 当前任务属于哪个业务域 | **LLM 动态判断** | 仅影响 Prompt 优先级/上下文与 capability 建议，**不承担授权** |

> **诚实性声明（D9）**：V1 是单用户 Demo，**不存在生产安全授权边界**——Workspace Mode 只是"能力配置/岗位视角模拟"，用户在 UI 可自由切换，不构成 RBAC。生产设计的正确形态是：`Auth/RBAC → Permission → Tool Catalog` 在 Agent 外部完成硬过滤，LLM 无法改变。对外表述务必用此措辞，不得声称"V1 有 RBAC"。

**WorkspaceMode 正式状态（不用 None 当异常）：**
```
WorkspaceMode = UNSET | CUSTOMER_SERVICE | OPERATIONS
UNSET 的工具目录 = intersection_catalog（6 公共工具）+ request_capability
```

**V1 交互流（D10 = a+：建议 → 一键切换 → 原请求自动重跑）：**
1. 会话默认 `UNSET` → 交集目录
2. LLM 判断任务需要超出当前目录的能力 → 调 **`request_capability(domain)`** meta-tool（只请求，不改权限）→ 运行时置 `capability_pending = {domain, original_message}`
3. UI 显示"该请求属于运营分析 → [切换到运营模式]"
4. 用户一键确认 → `Workspace Mode` 更新 → **用 original_message 自动重跑**（新目录下 LLM 自由选工具）
5. **防呆**：capability 请求每轮最多一次（防乒乓）；重跑为幂等读，原消息原样重放——若原消息本就触发审批 interrupt，重跑会再次 interrupt，属正常幂等行为
6. **禁止**：UI 不得因 LLM domain 自动切换模式——必须用户确认（保持"用户显式决定能力模式"）

**这不是回到 Router：** domain 判断只决定"要不要扩能力目录"，扩完后 LLM 仍在目录内自由选工具、组合、多跳——request_capability 是能力通道，不是执行路由。

**对照现行代码的差异（需按此改造，勿当已交付）：** 现行 [orchestrator.py:155](copilot/agent/orchestrator.py:155) 是 `session["role"] = result.role or "operations"` —— LLM 判断直接成为会话授权角色且被持久化，正是本策略要消除的混淆。

### 3.4 三条红线的结构性保持（本方案的核心安全设计）

Spec 红线原文（agent-runtime-v2-spec-v1.md）：

| 红线 | 定义 | 方案 B 保持方式 |
|---|---|---|
| **R4** | 正式结论由确定性工具裁定，LLM 只解释不裁定 | ① 工具层**零改动**（calc/SQL 不变）② system prompt 写死"正式结论一律以工具返回值为准，禁止自行推算或编造数值" ③ 工具 description 加后缀"（本工具返回即正式结论）" |
| **R5** | 业务分支只看结构化 State，禁止「LLM 感觉」作分支 | **是否触发审批由 workflow 内部结构化结果决定**（route_status / confirmation_required），不由 LLM 判断。LLM 选工具是编排自由，不是业务裁定 |
| **R10** | Action 在审批之后 + 写前必须重验证关键业务事实 | ① T-X-01 **不进 LLM 目录**，只在 CS-08 workflow 内部执行——因为 **T-X-01 本身不重验退货资格**（已核实：只验订单存在/幂等/数量≤可退），裸暴露会让 LLM 跳过资格判定直接建单，破 R10 ② CS-08 内部链：资格判定（结构化三态）→ interrupt 人审 → 建单 ③ T-X-01 保留数量重校验 + 审计 |

---

## 4. 决策记录（均已拍板）

| # | 决策 | 内容 | 状态 |
|---|---|---|---|
| D1 | T-X-01 不裸暴露 | 只在 CS-08 workflow 内部执行（R10 结构性保证）；T-R-01 同理收进 OP-05 | ✅ 已确认 |
| D2/D8/D9 | 角色策略（Identity · Workspace Mode · Domain 三分离）| **LLM 只判 Domain（建议，不授权）；Workspace Mode（Capability Profile）由 UI 显式切换；UNSET 用交集目录；生产由 Auth/RBAC 提供授权。V1 明示无生产安全授权边界**。取代早前"置信意图才锁" | ✅ 已确认（A' + D9）|
| D10 | 未锁定→能力域扩展（a+）| UNSET 起步；LLM 调 `request_capability(domain)` meta-tool → UI 一键切换 → **原请求自动重跑**；防乒乓（每轮最多一次）；UI 不得因 domain 自动切换 | ✅ 已确认（a+）|
| D11 | Tool 输出投影（Adapter）| Agent-facing 观察层：`Frozen Tool → Authoritative Result → Adapter 投影 → Concise Observation → LLM`；**不修改 Frozen Tool 契约**；第一优先级 `get_order_detail`（SELECT * 全行）；增量推进 | ✅ 已确认（现在做，W1.2）|
| D12 | capability 重跑语义 | **同一 thread + 不追加用户消息 + 输入 `capability_confirmed + original_message`**；模式切换后用新目录**重建 agent**（状态经 PostgresSaver 保留），视为上一轮 continuation；conversation 只追加一条系统旁注，不重复用户原文。反方案（新 thread）会丢 working_context、破多轮续答 | ✅ 已确认（同 thread）|
| D3 | workflow 保留口径 | 只保留 OP-05 + CS-08 两个审批 workflow；OP-04/07/08/03、CS-06 降级为普通工具。口径：**需多步/审批 → workflow，否则工具** | ✅ 已确认 |
| D4 | SC 断言变更 | 从 `route_status` 改为 `formal_result` 具体值（方案 B 必然代价）| ✅ 已确认 |
| D5 | 并行双轨（整体替换）| 新 ReAct 图放新模块 `copilot/agent/react.py`，legacy 保持默认至 Phase 6 切换；每阶段可回退。**已决定整体替换 ReAct 主循环，放弃早期讨论的「混合模式」（确定性意图走 workflow + 组合型开放 LLM）** | ✅ 已确认 |
| D6 | dryrun 测试范式 | fake LLM（GenericFakeChatModel 预设 tool_calls）+ 真实工具执行层；mock 掉"LLM 选工具"这唯一非确定点 | ✅ 已确认 |
| D7 | SC-ISO-001 跨店语义 | scenarios.yaml 被并行窗口还原为 FORBIDDEN，与方向 A 读放开代码（tool.py 未提交）冲突。**2026-09-21 Owner 拍板：选项 A**——重新应用 NORMAL 同步（读放开 + source_store 标注，延续方向 A 语义：跨店可读、跨店不可写、来源标注）| ✅ 已确认（选项 A）|

**补充定稿（分析中确认的次要设计）：**
- HITL 从"Runtime 级状态机"改为 LangGraph `interrupt()`（Spec §9.2 需同步修订，见 §10）
- OP-05 确认后语义 = 仅记录确认事件（V1 无采购单写工具，不悬空）
- `build_react_graph(model=...)` 必须支持模型注入（fake LLM 测试的前提）
- run_log 语义映射：`intent` 列 ← 主工具名；`route_status` 列 ← 审批状态（表结构不动）
- 错误语义：工具失败返回 `{error_code, error_detail}` 结构（不 raise），让 LLM 如实转述
- **UNSET 持久化**：`runtime.session.role` 存 sentinel `'unset'`（零 DDL，改一处 SQL 谓词）；workspace_mode **权威来源是 PostgresSaver 的 AgentState.session_context**，DB 列仅用于侧栏徽章显示

---

## 5. 实施项全清单（23 项）

**改动量**：S（<50 行）/ M（50~200 行）/ L（>200 行）；**难度**：低/中/高。

### W0 基线

| # | 内容 | 文件 | 量 | 难度 | 风险 | 阻碍 |
|---|---|---|---|---|---|---|
| 0.1 | 按 D7（选项 A）重新应用 SC-ISO-001 同步（NORMAL + source_store=2）→ 提交方向 A + SC 同步 | git + `scenarios.yaml` | S | 低 | 基线不绿则 G0 永远过不了 | 无（D7 已拍板）|

### W1 工具层

| # | 内容 | 文件 | 量 | 难度 | 风险 | 阻碍 |
|---|---|---|---|---|---|---|
| 1.1 | `session_ctx(session)` 替代硬编码 `ops_ctx`（现硬编码 role=operations/user_id=1）| `copilot/context.py` | S | 低 | 无 | 无 |
| 1.2 | 10 直连工具转 LangChain `@tool`（args_schema 用现成 Input pydantic；**ctx 一律走 `context_schema` 注入，禁止闭包捕获**——配合 W6.1 按 workspace_mode 缓存 agent 防跨会话串 ctx）+ **Agent-facing 输出投影 Adapter（D11）**：V1 只删**确定冗余**字段（内部 id / store_id / customer_id），保留全部业务相关字段（含 items）；投影双清单等工具面扩大时再形式化；**只作用 LLM 可见层，不修改 Frozen Tool 返回结构，不影响 workflow 内部逻辑** | **新** `copilot/agent/toolkit.py` | M | 中 | ctx 注入方式（context_schema，禁止闭包）；错误语义（返回 error dict 而非 raise）；投影过度裁剪导致丢正式字段 | 无 |
| 1.3 | 工具描述标准化为 **Agent Interface 8 字段**：What it does / When to use / When NOT to use（如 check_return_eligibility 不该用于"发起退货"，那走 CS-08）/ Required inputs / 参数含义 / 输出含义 / 错误含义 / **Authoritative?**（R4 后缀）。影响 Agent 效果的关键项，不轻视 | 各 `copilot/tools/*.py` | M | 中 | 描述差 → 选错工具率上升（效果影响大于换模型）| 无 |
| 1.4 | 角色目录过滤 + 未锁定期交集目录 | toolkit.py | S | 低 | 无 | 无 |
| 1.5 | live demo 验证脚本（UTF-8 安全打印）| 新脚本 | S | 低 | 无 | **GBK 编码坑**（实测踩过：DeepSeek 回 emoji 崩 GBK 控制台）|

### W2 ReAct 主循环

| # | 内容 | 文件 | 量 | 难度 | 风险 | 阻碍 |
|---|---|---|---|---|---|---|
| 2.1 | `create_react_agent` 组装：model 注入口、checkpointer、state_schema；**循环控制多维度**：max_iterations + max_tool_calls 计数 + 单调用 timeout（get_llm 已有 60s）；token/cost budget V1 不做 | **新** `copilot/agent/react.py` | L | 高 | 循环失控/超长（多维上限兜底）| 需 live 调试 |
| 2.2 | ReAct system prompt：persona + 身份 + R4 声明 + 能力边界 + **缺槽必问禁编造** + **request_capability 触发指令**（任务需要目录外能力时调用，与 W2.9 联动）| `copilot/agent/context.py` 改造 | M | 中 | **缺槽臆造（全案最高风险）**：prompt 是第一道软防线 | 无 |
| 2.3 | conversation → messages 播种（截断 N 轮）| react.py | S | 中 | 播种错位 → 上下文丢失 | 无 |
| 2.4 | 角色策略（D8/D9/D10）：Workspace Mode（UNSET/CUSTOMER_SERVICE/OPERATIONS，UI 可切换）+ LLM 只出 **Domain 建议**；公告话术改为"更像运营场景，可切换"措辞 | react.py + web | M | 中 | 授权与 Domain 混淆（本项正是消除它）| 无 |
| 2.5 | response 信封适配 + `run_agent` 兼容入口（两个 UI 依赖此契约）| react.py | M | 中 | 信封漂移 → UI 破损 | 无 |
| 2.6 | trace/run_log 适配（tool_called 事件；intent←主工具）| react.py | S | 低 | 可观测语义漂移（可接受）| 无 |
| 2.7 | Spec §9.2 偏差记录 | spec 文档 | S | 低 | 文档与实现矛盾（若不改）| 无 |
| 2.8 | **AgentState 显式 schema**（`state_schema`，已实测支持）：`messages` + `session_context`(user_id/workspace_mode/store_id) + `working_context`(current_order_no/current_sku/current_domain) + `execution_context`(tool_calls/iterations/pending_workflow)。**working state 覆盖规则**：用户显式给出新实体（如 ORD002）即覆盖旧值——写进 prompt + state 更新逻辑 + 回归测试；**模式切换不重置 working_context**（实体/任务上下文与能力模式正交，重跑时 LLM 仍可见已解析实体）。**原则：State 只记实体/任务上下文，不缓存业务事实**（事实永远从工具取，呼应 R10 写前重验）| react.py | M | 中 | 陈旧 working state 误用（需覆盖规则而非靠模型自觉）| 无 |
| 2.9 | **request_capability meta-tool（D10=a+ + D12）**：恒在目录（所有模式可见）；LLM 判断任务需要更高能力域时调用 → 运行时置 `capability_pending{domain, original_message}` → UI 一键确认 → 更新 Workspace Mode → **同 thread 重跑**（不追加用户消息，输入 `capability_confirmed+original_message`，新目录重建 agent，conversation 只加系统旁注）；防乒乓（每轮最多一次）；禁止 UI 因 domain 自动切换 | react.py + web | M | 中 | 乒乓循环；重跑污染（幂等读可容忍）| 无 |

### W3 审批 workflow

| # | 内容 | 文件 | 量 | 难度 | 风险 | 阻碍 |
|---|---|---|---|---|---|---|
| 3.1 | CS-08 workflow 工具：T-A-09 → interrupt → 确认 → T-X-01 + 审计 | toolkit.py / workflows.py | L | 中（op05.py 有 interrupt 先例，由高降级）| approval 元数据组装（approver_id ← session）| 无 |
| 3.2 | OP-05 workflow 工具：T-R-01 → HAS_RECO → interrupt → 确认=记录 | 同上 | M | 中 | 悬空语义（已定义：仅记录）| 无 |
| 3.3 | resume 路径：确认/拒绝文本 → `Command(resume=...)` 续跑 | react.py + API 层 | M | 高 | interrupt 与 web 请求生命周期对接（全案最复杂接线）| 需 PostgresSaver 在线 |

### W4 测试重构

| # | 内容 | 文件 | 量 | 难度 | 风险 | 阻碍 |
|---|---|---|---|---|---|---|
| 4.1 | **fake LLM 最小用例**（预设 tool_calls → ToolNode 真执行）| tests | S | **高（最脆一环）** | 接线失败 → dryrun 范式不成立 | **前置为 Phase 1 末 spike** |
| 4.2 | SC 驱动改造：断言 formal_result 具体值 | test_router_scs.py | M | 中 | 部分 SC 缺 expected_formal_result 字段 | 数据补齐工作量 |
| 4.3 | 新架构测试：R4 数值忠实 / 缺槽反问 / 角色过滤 / 审批 offline / ISO | tests | L | 中 | 覆盖不全 → 回归不可见 | 无 |
| 4.4 | legacy 测试分流：**44/81 个 runtime 级测试迁移或退役**；tool/calc/generator 级（~90 个）不动 | 4 个测试文件 | M | 中 | op05.py 竖切（6 测试）处置 | 无 |

测试盘点（copilot/tests 81 个 + generator 54 个 = 135）：
- 全量迁移：test_orchestrator（19）、test_router_scs（9）
- 部分迁移：test_agent_runtime（19 中约 10 个 registry/router 级退役，schema/persona/context 保留）
- 随模块退役：test_agent_op05（6，op05.py 竖切）
- 基本不动：test_rag（9）、test_restock（19）、generator 测试（54）

### W5 能力补强

| # | 内容 | 文件 | 量 | 难度 | 风险 | 阻碍 |
|---|---|---|---|---|---|---|
| 5.1 | 记忆读回：`get_memory(user_id)` → ReAct system prompt「用户长期偏好」块（复用 `context.assemble` 的 memory 字段——该字段现有运行时调用方为零）；**V1 每轮注入**（记忆量小、逻辑简单；token 敏感时后续可加缓存+TTL，V1 不做）| react.py / context | S | 低 | 无 | 无 |
| 5.2 | 知识生成式答案 + 证据引用（模板保留为 dryrun 兜底）| prompt + toolkit | M | 中 | 答案质量波动 | 无 |
| 5.3 | 黄金问答重基线（答案从模板变生成式）| eval 用例 | M | 中 | 断言漂移 | 无 |

### W6 Web 切换

| # | 内容 | 文件 | 量 | 难度 | 风险 | 阻碍 |
|---|---|---|---|---|---|---|
| 6.1 | NiceGUI 适配：**Workspace Mode 切换 UI + capability 一键切换 + 原请求自动重跑**（`capability_pending` 存 `AgentState.execution_context`，UI 经 `graph.get_state(thread_id)` 读取渲染，与 load_conversation 同模式）+ resume + 加载态。**agent 生命周期边界**：agent 按 workspace_mode 重建并缓存（graph factory，3 实例）——模式切换时重建**同 thread** 的新图，`run_agent` 契约不变；**工具 ctx 一律 `context_schema` 注入**（不闭包），同一 mode agent 可跨 session 复用。**双确认通道边界**：API 层区分 `resume`（审批，`Command(resume=...)`）与 `capability_confirm`（能力重跑，rebuild + re-invoke），UI 两个确认按钮走不同端点，不得混用。**UI 按钮状态派生**：从 `graph.get_state` 当前状态派生（capability_pending 非空→切换按钮；否则 `response.interaction.approval_required`→审批按钮；不得沿用重跑前的本地状态——重跑是新的 invoke，其 response 可能带新 interaction）。**重跑结果以新助手气泡追加**（V1 简单；"替换 pending 气泡"作 G6 可选优化）| `web/app.py` / `web/api.py` | M | 中 | resume 语义 + 异步处理；graph 生命周期；按钮状态派生 | 无 |
| 6.2 | FastAPI 适配 | `copilot/api/app.py` + static | M | 中 | 同上 | 无 |
| 6.3 | 默认切 ReAct + 保留 `AGENT_BACKEND=legacy` env 开关一版 | 入口 | S | 低 | 切换后回退能力 | 无 |

### W7 文档与清理

| # | 内容 | 文件 | 量 | 难度 | 风险 |
|---|---|---|---|---|---|
| 7.1 | Spec 修订记录 + AGENTS.md §1.1 快照更新 | docs | S | 低 | 文档漂移 |
| 7.2 | legacy 清理（router/registry/llm_router/op05.py 退役或归档）| 多文件删除 | S | 低 | 误删仍被引用模块 |

---

## 6. 分阶段计划与门禁（G0~G7）

**门禁纪律：每阶段 = 核查（客观可跑检查）+ 评估（人工对话级验收）；通过才进下一阶段，不跨阶段带病推进。**

### Phase 0 → G0（0.5h + 环境冒烟 15min）
- 内容：**环境冒烟脚本化** `scripts/smoke_check.py`（PG 连接 / Ollama bge-m3 embedding / DeepSeek key 一次调用 / pytest 基线四连，后续 live 门禁复用）→ W0.1（按 D7 选项 A 恢复 SC 同步 → 提交）
- **G0 核查**：pytest 全绿（当前 134/1，修复后应 135）；git status 干净
- **G0 评估**：提交信息准确描述方向 A + SC 同步；确认无其他并行窗口未合流的改动

### Phase 1 → G1（约 3h）
- 内容：W1.1~1.5 + **W4.1 前置 spike**（fake LLM 最小用例）+ **条件多跳批量复测**（脚本 `db/probe_multihop_batch.py`，基于 §2.3 单样本扩展，5~10 样本确认稳定性）
- **G1 核查**：
  - [ ] legacy 135 测试仍全绿（零侵入证明）
  - [ ] fake LLM spike 打通（预设 tool_calls → 工具真执行 → 结果返回）
  - [ ] 条件多跳批量复测：低库存→深挖 / 高库存→早停，≥80% 符合预期
- **G1 评估**（live demo 清单，逐项过）：
  - [ ] 明确请求 → 正确工具 + 正确参数
  - [ ] 跨工具组合 → 一次多 tool_call
  - [ ] 工具报 NOT_FOUND → LLM 如实转述，不编数据
  - [ ] 缺 SKU/订单号 → LLM 反问，**不编造标识符**
  - [ ] 目录过滤生效：未锁定期只见交集目录；切到运营模式才见运营工具
- 回退：toolkit 纯新增，不接入即回退

### Phase 2 → G2（约 5h，V1.5 预算按 1.5x ≈ 7~8h）
- 内容：W2.1~2.8（react.py 并行新模块，legacy 仍默认）
- **G2 核查**：legacy 测试仍绿；`build_react_graph(model=fake)` 离线跑通一轮；working state 覆盖规则有回归测试
- **G2 评估**：**5 类代表对话人工清单**，每项核对工具选择/参数/数值一致(R4)/越界拒绝/workspace mode 过滤：
  - [ ] **A 单跳**：库存查询、订单查询
  - [ ] **B 并行多工具**：退货 + 物流（C2）
  - [ ] **C 条件多跳**：库存 → 观察 → 销售异常 → 缺货风险 → 综合回答（证明不是 Tool Router，而是 Tool-Orchestrator）——**G2 硬门禁**
  - [ ] **D 错误恢复**：get_order → NOT_FOUND → LLM 不编造 → 询问用户
  - [ ] **E 上下文追问**：ORD001 → 物流？ → 能退吗？（working state 引用 + 覆盖规则：中途换 ORD002 应更新）
  - [ ] **F 能力扩展（D10=a+ + D12 硬门禁）**，拆三条独立断言：
    - [ ] F1：UNSET 下运营专属请求 → fake LLM 预设断言 LLM 输出 `request_capability(operations)` tool_call（**而非越权调 T-A-07**）
    - [ ] F2：state 断言 `execution_context.capability_pending == {domain: operations, original_message: ...}`
    - [ ] F3：切换后同 thread 重跑 → LLM 调出 T-A-07 且 **conversation 无重复 user message**（断言写法：重跑前后 `graph.get_state(thread_id).values['messages']` 中 `role=='user'` 的消息数相等）
- 回退：不切默认即回退

### Phase 3 → G3（约 4h，V1.5 预算按 1.5x ≈ 6h）
- 内容：W3.1~3.3
- **G3 核查**：offline（fake LLM）审批流测试：interrupt 挂起 → Command(resume) → 恢复；**resume 重放幂等**——interrupt 前节点（T-A-09 读）无副作用，恢复不造成重复 Action（LangGraph 特性：resume 会重跑 interrupt 前代码）
- **G3 评估**（live 全链路）：
  - [ ] 退货：eligible → 挂起确认 → "确认" → **T-X-01 真建单** → audit_logs 有记录 → 同 request_id 重放幂等返回原单
  - [ ] 退货：ineligible → **不触发 interrupt**，直接说明原因
  - [ ] 补货：HAS_RECO → 挂起 → 确认 → 记录确认事件（不写业务表）
  - [ ] 拒绝路径 → 终止且可开新对话
- 回退：workflow 工具从目录摘除即回退

### Phase 4 → G4（约 5h）
- 内容：W4.2~4.4
- **G4 核查**：
  - [ ] 全量测试绿
  - [ ] **拔掉 DeepSeek key 也能全绿**（dryrun 纯净性）
  - [ ] SC 覆盖不少于现状（data SC 全部有 formal_result 断言）
  - [ ] response 信封字段做成断言测试
  - [ ] 新测试 fixture 显式设置 `LLM_MODE=dryrun`（现有 test_router_scs / test_agent_op05 已如此，不依赖环境默认）
- **G4 评估**：抽 3 条 SC 人工复核断言语义合理（不为绿而绿）
- 回退：legacy 测试保留至本阶段末，可整体回退

### Phase 5 → G5（约 2h）
- 内容：W5.1~5.3
- **G5 核查**：知识问答黄金集通过（生成式答案含引用且与检索内容一致）
- **G5 评估**：记忆演示——"我默认看 7 天" → 新会话中窗口参数确实变为 7 天
- 回退：prompt 注入开关化即回退

### Phase 6 → G6（约 3h）
- 内容：W6.1~6.3
- **G6 核查**：双 UI E2E：新会话 → 业务问答 → 审批 → 确认 → 结果；切会话历史正确；**重启进程后线程续跑**
- **G6 评估**：手动体验加载态/角色回显无破损
- 回退：env 开关一键回 legacy

### Phase 7 → G7（约 1.5h）
- 内容：W7.1~7.2
- **G7 核查**：文档与实现一致；grep 无死引用
- **G7 评估**：技术叙事演练——能讲清"为什么从意图闭集走向工具调用、R4/R5/R10 如何保持"

**总工时约 30~35h（V1.5 校准，原 24h 偏乐观）。关键路径：`4.1 spike → 2.1 react → 3.1 审批 → 2.9 capability → 4.x 测试`。Phase 2/3 为超时重灾区，预算按 1.5x 预留（W2.1+W2.8+W2.9 叠加、W3.3 全案最复杂接线）。**

---

## 7. 风险总册（按首次暴露时点排序）

| 等级 | 风险 | 首次暴露 | 缓解 |
|---|---|---|---|
| **高** | 缺槽臆造（LLM 编 SKU/订单号）| G1 | prompt 硬规则 + 工具 NOT_FOUND 兜底 + G1/G2 清单专项断言 |
| **高** | fake LLM tool_calls 接线失败 | G1 spike | 前置独立 spike；失败改用 FakeListChatModel 或自写 FakeModel |
| **高** | interrupt resume 与 web 生命周期对接 | G3/G6 | op05.py 有先例；先 offline 后 live 分两步验 |
| 中 | 未锁定→运营/客服专属请求受阻 | G2 | request_capability 通道 + 一键切换 + 原请求自动重跑（D10=a+）|
| 中 | 工具描述导致选错工具 | G1/G2 | demo 迭代描述；G2 清单覆盖全部 10 工具 |
| 中 | SC expected_formal_result 数据不全 | G4 | 逐条补齐（数据在，字段缺）|
| 中 | response 信封漂移破 UI | G6 | 信封字段断言测试（G4 加）|
| 中 | ReAct 循环 cost/超长 | G2 | max_iterations + 温度 0 |
| 低 | GBK 编码、run_log 语义、文档漂移 | 各阶段 | 已知已知，逐个处理 |

## 8. 环境阻碍检查单（live 门禁前置条件）

每个 live 门禁（G1/G2/G3/G6）执行前确认：

1. **Docker PG 5434 在线**（所有工具依赖：`postgresql://ec:...@localhost:5434/ec_copilot`）
2. **Ollama + bge-m3 在线**（T-K-01 查询时现场 embedding：`localhost:11434`）
3. **DeepSeek key 有额度**（live 测试）
4. **demo/验证脚本用 UTF-8 安全输出**（Windows GBK 控制台踩过坑：DeepSeek 回 emoji 崩溃）
5. 旧会话 checkpoint 与新 state schema 不兼容——切换后**开新会话测试**，不做迁移

Python 环境：`C:/Users/HSY20/.conda/envs/ecommerce-agent/python.exe`（Git Bash 裸 `python`/`conda` 不可用）。

## 9. 实施边界（Scope）

**改（内）**：Agent Runtime 层编排逻辑、测试范式、web 适配（该层不在冻结清单）。

**不改（外）**：
- ❌ 不新增/删除业务工具——12 工具的 tool_id、行为、返回结构原样
- ✅ request_capability 是 **Runtime meta-tool**（非业务工具），新增它不违反"12 工具不变"边界
- ❌ 不加向量记忆/重排器/混合检索（P1 另立需求）
- ❌ 不做认证/多用户/流式（超出 V1）
- ❌ 不改 Frozen 契约（Business / Tool / Database / RAG / Workflow 文档保持权威）
- ✅ 保持 `run_agent(graph, thread_id, session, message) → {response, state}` 契约与 response 信封字段不变

## 10. 与既有文档的关系

| 文档 | 关系 |
|---|---|
| Business / Tool / Database / RAG / Workflow（Frozen）| **不动**。方案 B 只改运行时编排方式，业务语义、工具契约、数据口径全部继承 |
| `agent-runtime-v2-spec-v1.md`（V1.0，未冻结）| **Phase 7 需修订两处**：① §9.2 "HITL 为 Runtime 级状态机，非 LangGraph interrupt" → 改为 interrupt 方案；② §8 Intent Registry → 工具目录驱动。补修订记录 |
| `agent-evaluation-v2-v1.md` | 双轨评测天然对齐：legacy 可作评测基线（D5 并行双轨期间）|
| AGENTS.md §1.1 | Phase 7 更新快照（产品形态描述从"意图路由"改为"工具调用式"）|

## 附录 A：Jev（TypeSafe System One）选型记录

> 2026-09-22 记录。信息源：Jev 官网（jevtypesafeai.com/zh）、LangChain 官方博客、PyPI 实查；Jev 发布于 2026-09-15（本项目本分析之后，属调研补充，不影响方案 B）。

### A.1 是什么

TypeSafe AI 首款 **System One 模型**（2026-09-15 发布，HN 1679 分，当日被 Vercel AI Gateway / OpenRouter 接入）。定位：**非结构化状态进，类型化概率决策出——不生成文本**。三个原语：Choice（≤255 选项选一 + 概率分布）、Score（2~10 级打分）、Noul（校准的是/否概率）。官方口径 70~500ms、比 LLM 快 40~200×、$0.25~0.42/M 输入 token（厂商数字，未独立验证）。闭源托管，仅 API。

### A.2 LangChain 集成（已核实）

- ✅ `langchain-typesafe` 0.0.1a3（PyPI，Beta/pre-release）：`TypeSafeClassifier` + `Noul/Choice/Score`
- ✅ LangChain 官方博客（2026-09-17，Sydney Runkle）：`ModelRouterMiddleware` / `AutoModeMiddleware`，**均在 `experimental` 命名空间**
- ⚠️ **不是 ChatModel**：不返回文本，不能 drop-in 替换 ChatOpenAI；与 LangChain 的整合是"agent 循环里嵌 Jev 决策调用"

### A.3 项目适配评估（结论：V1 不引入，方案 B 不改）

| 候选用点 | 评估 | 结论 |
|---|---|---|
| 意图路由（替换 llm_router）| 与方案 B 方向相反（我们正要删意图闭集）| ❌ 永不 |
| 工具选择（Tool Selection）| 会退化为"新型 Intent Router"，削弱方案 B 核心价值 | ❌ 永不 |
| 角色判定（D8/D9）| 每会话一次的低频操作，DeepSeek 顺带判定已够 | ❌ |
| 审批风险闸门 | R10 要求 HITL 人审；且我们仅 1 个写工具（T-X-01），风险面 = 1 | ❌ V1 |
| 业务事实裁定 | R4 确定性工具裁定，不外包给第三方决策模型 | ❌ 永不 |
| 停止判断（answer_ready）| 与 LLM 单决策者原则冲突（双决策者）| ❌ 不优先 |
| **Jev-as-judge 评估生成式答案** | B5 后知识答案变生成式，eval 需 judge 升级；与 DeepSeek-as-judge 比成本收益 | ✅ Phase 2 候选 |
| **工具风险闸门（AutoMode 模式）** | 工具面扩大 / 出现第 2+ 写操作时 | ✅ Phase 2 候选 |
| **模型路由（ModelRouter 模式）** | 引入第二档模型时 | ✅ Phase 2 候选 |

### A.4 不引入 V1 的理由

发布仅 1 周、集成包 pre-release、中间件 experimental、GitHub 已有中间件执行顺序 issue（#40694）；架构中每个候选用点当前均有更简单或更确定性的方案。**技术选型论证价值**（当下最实际价值）："System One vs System Two"分层 + 五层分工（LLM 想做什么 / 决策模型是否满足条件 / Code 允不允许 / Workflow 按什么流程 / HITL 人是否授权），可用作技术选型论证样例。

---

## 11. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-21 | 首版：需求定义、可行性实测记录、架构与红线设计、D1~D6 决策、23 项实施清单、G0~G7 阶段门禁、风险册 |
| V1.1 | 2026-09-21 | 交叉审查修正：基线实况改为 134/1（SC-ISO-001 被并行窗口还原，新增决策 D7）；明确 D5 整体替换语义（放弃混合模式）；标注 D2 与现行方向 A 代码的差异；W2.4 补角色公告保留；W5.1 明确记忆注入点 |
| V1.2 | 2026-09-22 | 新增附录 A（Jev 选型记录）：调研后判定 V1 不引入、方案 B 不改；Phase 2 候选为 Jev-as-judge / 工具风险闸门 / 模型路由 |
| V1.3 | 2026-09-22 | 采纳 D8=A'（Workspace Mode 与 Business Domain 分离，取代 D2 置信锁定；对照代码确认混淆点 orchestrator.py:155）；条件多跳 spike 实测通过（§2.3）；AgentState 显式 schema（W2.8）+ 循环控制多维（W2.1）+ 工具描述 8 字段模板（W1.3）；G2 升级为 5 类对话清单（条件多跳为硬门禁）；G3 加 resume 重放幂等断言 |
| V1.4 | 2026-09-22 | 定稿 D9（Identity/Workspace Mode/Domain 三分离 + 明示 V1 无生产授权边界）、D10=a+（request_capability meta-tool + capability_pending + 原请求自动重跑 + 防乒乓，W2.9）、D11（Tool 输出投影 Adapter，W1.2）；UNSET 为正式状态；文档一致性清理（架构图/§3.3/风险表旧 D2 语义全部统一）；G2 增 F 能力扩展硬门禁 |
| V1.5 | 2026-09-22 | 定稿 D12（capability 重跑语义：同一 thread + 不追加用户消息 + 新目录重建 agent）；三隐患边界定义落 W2.8（模式切换不重置 working_context）/ W2.9（重跑语义）/ W6.1（capability_pending 存 AgentState + UI get_state）；G2-F 拆 F1/F2/F3 三断言；工时校准 30~35h（Phase 2/3 按 1.5x）；Phase 0 前加环境冒烟 |
| V1.5.1 | 2026-09-22 | 通读审查修正：W6.1 补 graph factory（agent 按 workspace_mode 重建并缓存，run_agent 契约不变）+ 双确认通道边界（resume vs capability_confirm）；W2.2 补 request_capability 触发指令；§3.3 精确"重跑幂等"措辞；§9 明示 request_capability 为 meta-tool 不违反 12 工具边界；附录 A.3 陈旧 D2 引用改 D8/D9；Phase 2/3 标题标 1.5x 预算 |
| V1.5.2 | 2026-09-22 | 收敛审查采纳：W1.2 定案 **ctx 走 context_schema 注入（禁闭包）**；UNSET 持久化 sentinel 'unset'（权威在 checkpointer）；W6.1 UI 按钮从 graph.get_state 派生 + 重跑结果追加新气泡（V1）；W5.1 记忆每轮注入；G4 补 dryrun fixture 检查；G2-F3 补断言写法；投影收敛为"V1 只删确定冗余字段"；环境冒烟脚本化 smoke_check.py + 多跳批量脚本 probe_multihop_batch.py；request_capability 加 sudo 类比 |
| V1.5.3 | 2026-09-26 | 实施状态记录（Phase 2-4 落地）：① UI 体验补齐——空会话引导文案（E1 §3.4）、模式下拉中文化+当前会话高亮、WebSocket 加载恢复最近会话（web/app.py）；② 会话标题 COALESCE 回填（store.py create_session ON CONFLICT 更新 title，legacy None 标题行复用后回填）；③ capability 提示中文统一（react.py _MODE_LABEL）；④ 模型行为调优——系统提示『查询 vs 发起』边界 + check_return_eligibility/analyze_stockout_risk/cs08/op05 四处工具描述收紧 + 3 条 dryrun 断言（test_react.py），live 3/3 复测通过（UNSET 申请退货不再降级为资格查询）。**UNSET 持久化实现口径更新**：P2 落地为『session.role 存大写 workspace_mode、run_log.role 存小写』（取代 §4 的 'unset' sentinel 措辞；legacy 旧行大小写混杂仅历史遗留）。全量测试 159 passed |

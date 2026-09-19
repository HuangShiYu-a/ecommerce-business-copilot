# E-commerce Business Copilot — Agent Evaluation V2（Spec-3）

版本：V1.0 · 状态：定稿 · 日期：2026-09-19

**文档定位**：Agent Runtime V2 的**评测层规范**。评测对象 = **Agent 行为**（意图路由 / 槽位 / 多轮 / 澄清 / 续答 / 权限 / 记忆 / Trace），区别于 S3 eval_slice（数据验收）与 sc_runner（业务正确性）。对应《Agent Runtime V2 Spec》§15 的落地细节。

---

## 1. 定位与边界

### 1.1 评测什么

- **Runtime Eval V2** 评测 Agent 行为：意图路由 / 槽位抽取 / 多轮 / 澄清 / 续答 / 权限 / 记忆 / Trace。
- **不是**重新验证业务正确性——那是 33 SC 的职责。
- **不是**数据生成验收——那是 S3 eval_slice 的职责。

### 1.2 与现有资产的关系

| 资产 | 角色 | 本 Spec 的处理 |
|---|---|---|
| 33 SC（26 data + 7 runtime）| 业务场景数据 | **Legacy Regression 轨**（不回归；见 §2.2 升级）|
| 71 tests | 实现验证 | 回归轨一部分（pytest 集成，D6）|
| sc_runner | 工具路由验证 | 保留，作为 33 SC 回归的执行器 |
| S3 eval_slice | 数据验收 | 保留，独立 |

### 1.3 评测运行环境

- 评测基于 **eval 数据导入的 PG**（`import_data.py --profile eval`）。
- **用例引用的实体（订单/SKU）必须与评测数据集一致**——防止引用不存在的实体（D5 已确认 eval 数据充分）。

---

## 2. 双轨评测架构

| 轨 | 内容 | 判定 |
|---|---|---|
| **Legacy Regression** | 33 SC + 71 tests **穿新 Router** 全 PASS | 0 回归 |
| **Runtime Eval V2** | Agent 行为维度（§4）| 全部 P0 用例 PASS |

### 2.1 最终验收

```
Legacy Regression = 0 回归
+
Runtime Eval V2   = P0 用例全 PASS
```

> 33 SC 全 PASS ≠ Runtime 完成；Agent 行为正确性必须由 Runtime Eval V2 单独证明。

### 2.2 Legacy Regression 升级

现有 SC 只断言**业务结果**（如 HAS_RECO）。穿新 Router 后，每个 SC 额外断言**路由正确性**：

```
SC 输入 → intent 正确 → workflow 正确 → tool 正确 → 业务结果不变
```

即 33 SC 同时获得「业务正确性 + 路由正确性」双断言。

---

## 3. 评测链（逐环节断言，D3）

```
input → intent → slot → clarification → workflow → tool → tool_args
      → RAG → formal_result → final_answer → trace
```

- **逐环节独立断言**：定位问题具体卡在哪一环。
- 并非每个用例都断言全部环节——按用例目的选择断言哪些环节，缺省不断言。

---

## 4. Runtime Eval V2 维度（P0 每维度 ≥3 用例，D4）

| 维度 | 用例示例（输入）| 核心断言 |
|---|---|---|
| intent routing | 「SKU_01_STOCKOUT_01 要补货吗」| intent=restock_recommendation |
| wrong intent | 「帮我写首诗」| out_of_scope 优雅回复 |
| missing slot | 「帮我查订单」（无订单号）| Clarifier 问精准问题，不退出 |
| multi-turn | 查订单 → 送到哪 → 退货可行 | 对象跨轮次从记忆解析 |
| confirmation | 补货 HAS_RECO → 确认/拒绝 | HITL resume 正确（SC-OP05-005/006）|
| resume | 错误中断后「继续」| 从 checkpoint 继续，不重算正式结果 |
| out_of_scope | 与业务无关 | 优雅兜底，不崩溃 |
| permission | 运营角色问客服专属意图 | 拒绝 / FORBIDDEN |
| memory | 预置偏好种子 → 验证注入 | 记忆进入 Context |
| trace | 各维度用例附带 | P0：关键步骤存在（§8.4）|

---

## 5. 评测语料（data/eval-cases/，D1）

独立于 `scenarios.yaml`（业务场景数据）——评测语料与业务场景解耦。

```
data/eval-cases/
├── routing.yaml        # 意图路由问法（每 intent 多样问法 + 负例）
├── multi_turn.yaml     # 多轮剧本（引用真实订单号，D5 已确认 27 候选）
├── negative.yaml       # 错误路由测试（误分类/实体错配/歧义 → 期望纠正行为）
└── rag_gold.yaml       # 黄金问答（知识扩 15-25 篇后编纂）
```

---

## 6. 断言模型（用例 schema）

### 6.1 单轮用例

```yaml
- id: rt-001
  input: "SKU_01_STOCKOUT_01 要补货吗"
  store_id: 1
  role: operations
  mode: dryrun
  expected:
    intent: restock_recommendation      # Router
    workflow: OP-05                      # Intent Registry → Dispatcher
    tool: T-R-01                         # 工具选择
    tool_args: { sku_code: "SKU_01_STOCKOUT_01" }
    formal_result: HAS_RECO              # 确定性结果
    final_answer_contains: ["补货"]      # 最终回答关键事实
    trace_contains: [intent_detected, tool_called, final_response]  # P0 关键步骤
```

### 6.2 多轮剧本（turn 序列，逐轮断言）

```yaml
- id: mt-001
  mode: dryrun
  turns:
    - input: "帮我查订单 ORD_01_000437"
      expected: { intent: order_query, slot: { order_id: "ORD_01_000437" } }
    - input: "送到哪了"
      expected: { intent: shipping_status, slot_resolved_from: order_id }  # 从记忆解析
    - input: "这个能退货吗"
      expected: { intent: return_eligibility, workflow: CS-08 }
```

- `slot_resolved_from`：断言该槽位由多轮记忆解析，非消息显式给出。

---

## 7. 回归门

- **触发**：提交前 / 合入前必跑（`pytest`）。
- **判定**：
  - Legacy Regression = **0 回归**（33 SC + 71 tests）
  - Runtime Eval V2 = **P0 用例全 PASS**
- 任一不满足 → 阻断合入。

---

## 8. 运行方式

### 8.1 双模式（D2）

| 模式 | 路由 | 断言强度 | 用途 |
|---|---|---|---|
| **dryrun**（`LLM_MODE=dryrun`）| 规则路由（确定性）| **精确断言**（intent/workflow/tool 精确匹配）| 主评测，可复现、可进 CI |
| **live**（真实 LLM）| LLM 结构化路由 | **只 smoke**（确认不崩溃 / 关键步骤存在）| 集成验证，不跑精确断言（避免 LLM flaky）|

### 8.2 集成（D6）

- **pytest 集成**：复用现有 71 tests 基础设施；用例 yaml → fixture 加载 → 运行 Runtime → 断言器 → 报告。
- `data/generator/tests`（数据轨）与 `copilot/tests`（运行时轨）分开；Runtime Eval 归 `copilot/tests`。

### 8.3 Trace 断言（D7）

- **P0**：断言**关键步骤存在**（如 `intent_detected` / `tool_called` / `final_response`）。
- **P1**：断言**完整步骤序列**（顺序敏感）——延后。

---

## 9. 与 Spec-1/2 一致性核对

| Spec-1/2 | 本 Spec | 一致 |
|---|---|---|
| §8.6 意图清单 | §6.1 `expected.intent` 取值一致 | ✅ |
| §8.3 Intent Registry | §6.1 `expected.workflow` 由 Registry 决定 | ✅ |
| §7.3 RouterResult（无 workflow）| 用例断言 intent +（Registry→workflow）| ✅ |
| §7.5 AgentResponse 分层 | `final_answer_contains` 断言 message；`formal_result` 对应 result | ✅ |
| §3.1 Pending Task Check | multi-turn 用例走 Pending Task Check 路径 | ✅ |
| §9.6 正式结果复用边界 | resume 用例断言「不重算」 | ✅ |
| Spec-2 session/thread | 多轮剧本同 session 执行（1 thread）| ✅ |
| §13 Trace Domain Event | `trace_contains` 用 §13.2 事件枚举 | ✅ |

---

## 附：数据充分性（D5 结论）

- eval 数据：505 单 / 97 SKU / 27 可退窗口候选 / staff_users 双角色×双店。
- 多轮剧本可引用**真实订单号**（如 ORD_01_000437，服装/服饰，签收 4 天前）。
- RAG 黄金问答（rag_gold.yaml）待知识扩至 15-25 篇多格式后编纂（阶段 3 数据侧）。
- 评测运行环境：`import_data.py --profile eval` 导入 PG。

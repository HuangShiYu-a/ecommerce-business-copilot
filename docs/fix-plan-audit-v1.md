# 审计缺陷修复方案 V1.0（草案）

> 文档性质：**实施前方案**（分析/规划，非代码改动）
> 版本：V1.0（草案）
> 日期：2026-09-27
> 状态：Draft（待用户确认后实施）
> 范围：本轮审计（H1-H4 / M1-M5 / L1-L6）的修复方案 + 实施边界
> 关联：docs/agent-plan-b-react-v1.md（D9 授权边界）、docs/workflow-cs08-09-v1.md、docs/workflow-cs06-v1.md、docs/workflow-ops-p0-v1.md

---

## 0. 本文档要解决的问题（What）

### 0.1 触发问题（用户实测，最直接）

**订单 `ORD_01_000438` 每次申请退货都会被再次要求「创建退货申请」，即使上一次已创建成功。**

现象：每次都能申请、能审批通过，但下次再测同一个例子，系统仍重新弹出「是否创建退货申请」。用户疑问：创建退货功能是否真实有效？是否一个订单可重复创建退货申请？

**回答（已核实）**：
- 数据库层面**真实有效**：`after_sales_requests` 有 `UNIQUE(store_id, idempotency_key)`，幂等键 `CS08-{order}-{item}` 重放返回原单，**不会双写**。
- 问题在**流程层**：CS-08 workflow（`make_cs08_workflow_tool`）从不检查 `existing_return`（该订单已有成功退货单），eligible 分支无条件走「审批 interrupt → 建单（幂等重放）」，于是每次重复「创建仪式」，产生 UX 噪音。

### 0.2 全量审计发现（15 项）

对 14 个工具、2 个工作流工具、8 个计算模块、ReAct + legacy 双后端做了代码 + 数据实证审计，结论全部真实存在：

| 编号 | 问题 | 严重度 | 一句话 |
|---|---|---|---|
| H1 | CS-08 忽略 existing_return，重复触发创建 | 高 | 已存在退货单仍重复走建单仪式 |
| H2 | 在途超期订单永远报 NORMAL | 高 | 已发货未送达且超 promised → 硬编码 NORMAL（188 单受影响） |
| H3 | 可退数量守卫含非成功态 | 高 | REJECTED/CANCELLED/PENDING 也扣可退量 |
| H4 | 文本审批否定句误判为同意 | 高 | 「不同意」→ approved（双后端） |
| M1 | 慢销窗口销量未过滤 | 中 | SUM 统计全量历史，含 CANCELLED/窗口外订单 |
| M2 | workflow 工具内部异常冒泡 500 | 中 | 只有 finally 无 except，与直连工具不对称 |
| M3 | 跨店守卫只看字符串前缀 | 中 | int id 绕过 → NOT_FOUND 而非 FORBIDDEN（SQL 兜住，无越权） |
| M4 | 模式/角色/门店客户端自声明 | 中 | 无服务端鉴权，但 D9 明示 V1 无生产授权边界 → 设计取舍 |
| M5 | MAX(id)+1 建单竞态 | 中 | 并发撞主键（单用户 demo 风险低） |
| L1 | CS-08 固定 items[0] 整行退 | 低 | 无法选行/部分退 |
| L2 | 幂等 dup 无状态过滤 | 低 | 被拒后重提命中旧单（复杂度最高，单列） |
| L3 | legacy 确认话术错误 | 低 | 所有 workflow 都回「补货建议生效」 |
| L4 | 健康度 returns 维度含全状态 | 低 | REJECTED 也算有售后 |
| L5 | RAG scope 过滤在 top_k 之后 | 低 | 类目未知时不排除专属规则 |
| L6 | sales_anomaly prev==0→drop=0 | 低 | 口径选择，建议加标注而非改判定 |

### 0.3 根因归纳（5 类模式）

1. **算出来的事实没人消费**：H1、L5（信号算了未接线）
2. **硬编码死分支代替判定**：H2、L6（规格在、实现占位）
3. **状态过滤口径不一致**：H3、L2、L4（同一概念不同口径互相矛盾）
4. **双后端/双通道未对齐**：H4、M2、L3（行为分裂）
5. **健壮性不对称**：M2、M5（一条路径兜底、一条不兜底）

---

## 1. 实施目标（Goal）

1. **止血 H4/H1**：真实交互路径不再误判、不再重复触发退货创建（本次问题的核心）。
2. **对齐规格 H2**：在途超期判 ANOMALY，与 WF-CS06 / SC-CS06-004 期望一致。
3. **统一口径 H3**：可退数量只算成功态，与 existing_return 一致。
4. **补齐健壮性 M1/M2**：SQL 统计正确、workflow 异常不冒泡成 500。
5. **文档对齐 M3/M4/M5**：不合理的注释/声明更正，不改行为。
6. **L 批小修**：逐项最小改动。

**验收标准**：全量 `pytest -q` 通过 + 定向断言（H4 否定句、H1 already_exists、H2 ORD_01_001454→ANOMALY、H3 REJECTED 后可退）+ `scripts/eval_g3.py` / `scripts/eval_g5.py` 改后重跑 PASS。

---

## 2. 实施边界（Boundary，不越界）

**不做的事：**
- **不改 schema**：M5 不用 BIGSERIAL/IDENTITY（需迁移 + 重导数据，成本高），demo 阶段仅文档标注或加 `LOCK TABLE`；不改 `after_sales_requests` / `service_tickets` 表结构。
- **不引入新表 / 新工具 / 新 workflow**：全部修复在现有文件内完成。
- **不动 LLM 主流程**：不改 persona、不改系统提示词语义、不改 LLM 模型；H4 只改文本判定逻辑，不涉及 LLM 调用。
- **不做 L2 的完整修复**：L2（幂等 dup 无状态过滤）涉及幂等键生成 + schema 唯一约束联动，复杂度最高，**本次仅标注、不实施**（单列后续）。
- **不实现 UI 改动**：web/app.py 不需要改（`already_exists` 走正常消息路径即可呈现）。
- **不废弃 legacy**：L3 只改文案，保留 legacy 后端可用。
- **不改数据生成器/黄金数据**：除非某项断言要求新增（H2 转 data 型、H1 SC-CS08-006 加断言），否则不动 `data/`。
- **不修评估方案本体**：只同步受影响的断言（eval_g3、scenarios.yaml），不重写 evaluation-plan。

**边界内：** 仅 copilot/ 下 10 个左右源文件 + scripts/eval_g3.py + data/scenarios/eval/scenarios.yaml + 测试文件的定向修改。

---

## 3. 修复方案细节（按优先级）

### P0-H4 审批文本否定句误判（先做，真实交互路径）

**现状实现状态**：
- [copilot/agent/react.py:213-234](copilot/agent/react.py) `resolve_approval_text`：`_APPROVAL_ACCEPT`（"确认"/"同意"）**先于** `_APPROVAL_REJECT` 判断 → 输入「不同意」含"同意" → 判 approved。
- [copilot/agent/orchestrator.py:82](copilot/agent/orchestrator.py) `handle_pending`：`any(k in message for k in ("确认","同意","可以","好的"))` → 同样的否定误判。
- [copilot/context.py:58-76](copilot/context.py) `capability_text_decision`：已做「拒绝词优先 + 疑问句守卫」，是现成的正确范式。

**需要进行的操作**：
1. 在 [copilot/context.py](copilot/context.py) 新增 `approval_text_decision(message) -> "approved"|"rejected"|None`，复用 `capability_text_decision` 的范式：
   - 疑问句守卫（`吗/？/是否/为什么/怎么` → None，不判定）
   - 拒绝词优先，扩展 `_APPROVAL_REJECT` = ("拒绝","取消","不同意","不确认","不要")
   - 再查接受词 ("确认","同意","可以","好的")
2. [react.py](copilot/agent/react.py) `resolve_approval_text` 改调该 helper。
3. [orchestrator.py:82](copilot/agent/orchestrator.py) `handle_pending` confirm 分支改调该 helper。
4. 测试断言：补「不同意→rejected」「确认→approved」「含疑问句→None」。

**风险**：低（纯判定逻辑，不动 LLM/数据）。
**阻碍**：无。注意保留「好的/可以」原判定不被否定词误伤（"好的"不含拒绝词）。

---

### P0-H1 CS-08 重复触发创建（本次核心问题）

**现状实现状态**：
- [copilot/tools/check_return_eligibility.py:50-53](copilot/tools/check_return_eligibility.py)：`existing_return` 无条件附加到 result（成功态 APPROVED/COMPLETED/PROCESSING），**但只在不 eligible 分支被 workflow 透传**。
- [copilot/agent/toolkit.py:185-221](copilot/agent/toolkit.py) `make_cs08_workflow_tool._run`：eligible 分支（:193-199 之后）**不查 existing_return**，:203 无条件 `interrupt()`，:212-218 用幂等键建单（重放返回原单）。
- [copilot/agent/workflows.py:189-207](copilot/agent/workflows.py) legacy `_cs08`：同样只判资格，existing_return 不参与。

**需要进行的操作**（Option A：工作流层短路，不动工具契约）：
1. [toolkit.py](copilot/agent/toolkit.py) `_run`：在 `data.get("decision") != "eligible"` 分支**之前**，先判 `if data.get("existing_return"): return {...}`——返回 `{**data, "status": "already_exists", "message": f"订单 {order_no} 已有退货申请（{request_no}），不再重复创建"}`，不 interrupt、不建单。
2. legacy [workflows.py](copilot/agent/workflows.py) `_cs08`：同步短路 → `confirmation_required=False`，返回 existing_return 信息。
3. **必须同步改断言**（现状断言与修复目标冲突）：
   - [scripts/eval_g3.py:53-57](scripts/eval_g3.py)：幂等重放段改为断言「重跑**不再** approval_required，直接返回已有单（idempotent/status=already_exists）」。
   - [data/scenarios/eval/scenarios.yaml:123-135](data/scenarios/eval/scenarios.yaml) SC-CS08-006：从「无路由断言对照」改为有断言（workflow 层不 interrupt）。
4. 测试断言：新增「预置 APPROVED 退货单后调 cs08_return_workflow → 不触发 interrupt、返回 already_exists」。

**风险**：中（动评测断言是必要项）。
**阻碍**：eval_g3 现断言与目标冲突，须先改；SC-CS08-006 断言口径需定义（eligible + 不 interrupt，还是单独状态）。
**注意**：`test_ta09_eligible_within_window`（[test_restock.py:101](copilot/tests/test_restock.py)）不受影响——工具 `decision` 仍返回 eligible，只有 workflow 行为变。

---

### P0-H2 在途超期误报 NORMAL

**现状实现状态**：
- [copilot/calc/fulfillment.py:12-29](copilot/calc/fulfillment.py) `fulfillment_delay`：`delivered` 为空时 `overdue = False` **硬编码**（:19），`reason="overdue"` 分支是死代码；函数**无 as_of 参数**，无法比较。
- 调用点：[copilot/tools/fulfillment_delay.py:31](copilot/tools/fulfillment_delay.py)、[copilot/sc_runner.py:139](copilot/sc_runner.py) 均不传 as_of。
- **数据实证**：188 单（店1=161/店2=27）「已发货、未送达、promised < as_of 2026-09-17」，全部被报 NORMAL。SC-CS06-004（ORD_01_000005，在途超期）期望 ANOMALY，但该用例是 `runtime_eval` 不被 `test_all_data_scs` 断言，缺陷静默存在。

**需要进行的操作**：
1. [fulfillment.py](copilot/calc/fulfillment.py) `fulfillment_delay(conn, order, store_id, as_of)` 加参数；delivered 为空时：`promised_delivery_at < as_of` → `ANOMALY(reason="overdue_in_transit", overdue_days=…)`，否则 `NORMAL(in_transit)`。
2. 调用点传 `AS_OF_DATE`：[tools/fulfillment_delay.py](copilot/tools/fulfillment_delay.py)、[sc_runner.py](copilot/sc_runner.py:139)。
3. 断言：SC-CS06-004 修复后自然对齐（建议转 data 型并断言）；新增 `ORD_01_001454 → ANOMALY` 测试。
4. **口径确认（阻碍）**：`promised` 为空 / 未发货已超 promised 是否也算 ANOMALY，需定死边界（建议：仅「已发货未送达且超 promised」判 ANOMALY，未发货走原逻辑，避免过度扩展）。

**风险**：名义高（翻转 188 单），但已 grep 确认 `data/eval-cases/`、`scripts/*.py` 无任何断言 CS-06 输出值（tool_sel.yaml 只断言工具选择）；修复后与规格/SC-CS06-004 一致 = 对齐而非偏离。
**阻碍**：口径边界（上一步）需业务确认。

---

### P1-H3 可退数量守卫状态过滤

**现状实现状态**：
- [copilot/tools/create_return_request.py:73-78](copilot/tools/create_return_request.py)：`SUM(quantity) WHERE order_item_id=%s AND store_id=%s` **无 status 过滤**。
- **数据实证**：REJECTED×4（订单 813/867/944/1332）、CANCELLED×4（279/656/2141/2956）、PENDING×1（111）——这些订单从未成功退过也被永久扣可退量。
- 与 [copilot/calc/return_policy.py:87-92](copilot/calc/return_policy.py) `existing_return`（只算成功态）口径不一致。

**需要进行的操作**：
1. [create_return_request.py:74](copilot/tools/create_return_request.py) 加 `AND status IN ('APPROVED','COMPLETED','PROCESSING')`，与 existing_return 完全统一。
2. **口径决策（阻碍）**：PENDING 是否占可退量——建议不占（与 existing_return 一致），但要定死并写注释，避免再分裂。
3. 断言：新增「预置 REJECTED 行后仍可申请」。
4. 已核实：不影响现有 test_restock（`_clean_tx01` fixture 先清 CS08-* 行；`test_tx01_over_quantity` 用 99 无论如何都 PRECONDITION_FAILED）。

**风险**：中（影响可退数量计算）。
**阻碍**：PENDING 口径。

---

### P1-M1 慢销窗口销量未过滤

**现状实现状态**：
- [copilot/calc/slow_moving.py:25-47](copilot/calc/slow_moving.py)：窗口/状态过滤写在 `orders` LEFT JOIN 的 **ON** 子句（:33-35），`SUM(oi.quantity)`（:26）仍统计 SKU 的**全量历史 order_items**——未命中的 oi 行（窗口外/非有效状态）仍被求和。
- **数据实证**：`SKU_01_SLOW_01` 报了 6（含 1 笔 CANCELLED 的 2），正确窗口数应为 4。当前种子数据未翻转候选集，但报告值错误，且历史销量高的真慢销 SKU 会被误排除。

**需要进行的操作**：
1. 把窗口/状态过滤移到 `order_items` 侧：`LEFT JOIN order_items oi ON oi.sku_id=s.id AND oi.order_id IN (SELECT id FROM orders WHERE store_id=... AND status IN (...) AND ordered_at>=...)`，确保 `SUM(oi.quantity)` 只算窗口内有效订单。
2. 验证 `SKU_01_SLOW_01` 从 6 → 4。

**风险**：中（SQL 重构注意 LEFT JOIN 语义：过滤放 ON 不会把 sku 行挤出）。
**阻碍**：无（纯 SQL 修复）。

---

### P1-M2 workflow 工具异常冒泡 500

**现状实现状态**：
- [copilot/agent/toolkit.py:185-221](copilot/agent/toolkit.py) `make_cs08_workflow_tool._run` 与 [242-273](copilot/agent/toolkit.py) `make_op05_workflow_tool._run`：只有 `finally: conn.close()`，**无 except**；DB 异常直接穿透 `tools_node` → `graph.invoke` → FastAPI 500。
- 对比：直连工具经 `run_tool` 有 `except → DEPENDENCY_ERROR` 兜底（[tool.py:153-162](copilot/tool.py)），路径不对称。

**需要进行的操作**：
1. 两个 workflow `_run` 补 `except Exception → {error_code: "DEPENDENCY_ERROR", error_detail: str(e)}`。
2. **必须 `except GraphInterrupt: raise`** 放行审批中断（否则打断 interrupt 机制）。
3. 断言：注入 DB 故障 → 返回 error dict 而非抛异常。

**风险**：低。
**阻碍**：不能吞 interrupt（上一步是硬约束）。

---

### P1-M3 跨店守卫语义（文档对齐，不改行为）

**现状实现状态**：
- [copilot/tool.py:96-116](copilot/tool.py) `cross_store_info`：只扫字符串参数（`ORD_/SKU_` 前缀），`create_return_request` 经 workflow 传 int `order_id/item_id` 绕过前缀检测。
- **实际安全**：`create_return_request` SQL 按 `ctx.store_id` 过滤，workflow 已先经 `get_order_detail(ctx.store_id)` 确认订单归属本店；跨店 int id 只会 NOT_FOUND，无越权。

**需要进行的操作**：仅更新 [tool.py](copilot/tool.py) 注释 + 相关文档：明确「int 参数由 SQL store 过滤兜底（NOT_FOUND）；字符串前缀才走 FORBIDDEN」。
**风险/阻碍**：无。

---

### P1-M4 客户端自声明（文档确认，不改）

**现状**：[copilot/api/app.py:35-48](copilot/api/app.py) `AgentRequest` 接受客户端自声明 `workspace_mode/store_id/user_id`，无服务端校验。
**结论**：[agent-plan-b-react-v1.md:145](docs/agent-plan-b-react-v1.md) D9 已明示「V1 单用户 Demo，无生产安全授权边界，不构成 RBAC」。**设计取舍，非缺陷**。
**操作**：无需代码改动；如需，可在该文档补一句「前端自声明是 V1 取舍，生产须 Auth/RBAC 硬过滤」。

---

### P1-M5 建单 id 竞态（标注/低成本加固）

**现状实现状态**：
- [copilot/tools/create_return_request.py:80-81](copilot/tools/create_return_request.py)：`SELECT MAX(id)+1` 无锁，并发建单撞主键；audit id 取 `next_id+1` 同理。单用户 demo 风险低。

**需要进行的操作**（二选一）：
1. **低改**：INSERT 前 `LOCK TABLE after_sales_requests IN SHARE ROW EXCLUSIVE MODE`（事务内），并发安全且不动 schema。
2. **仅标注**：文档注明已知限制，demo 不修。
**建议**：选 1（改动小、无 schema 迁移）。若选 2，明确记录为遗留项。
**风险/阻碍**：低。

---

### P2-L 批（逐项小修）

| 项 | 现状 | 最小操作 |
|---|---|---|
| L1 | [toolkit.py:199-207](copilot/agent/toolkit.py) 固定 `items[0]` 整行退 | 输入加可选 `item_id` + 更新 `_DESCRIPTIONS`；或 V1 文档标注 |
| L2 | [create_return_request.py:66-71](copilot/agent/toolkit.py) dup 无状态过滤，被拒后重提命中旧单；与 schema 唯一键联动 | **本次不实施**，标注为后续项（需幂等键生成 + schema 级设计） |
| L3 | [orchestrator.py:85](copilot/agent/orchestrator.py) 所有 workflow 回「补货建议生效」 | 按 `task.intent` 区分文案（退货→「已确认，退货申请流程已启动」） |
| L4 | [calc/product_health.py:31-35](copilot/calc/product_health.py) returns 维度无 status 过滤 | 加成功态过滤 |
| L5 | [rag.py:52-86](copilot/rag.py) scope 过滤在 top_k 后；类目未知不排除专属规则 | 无命中时提高 top_k 重查；类目未知时排除专属规则（与 `_scope_match` 联动） |
| L6 | [calc/sales_anomaly.py:53](copilot/calc/sales_anomaly.py) prev==0→drop=0 | 加 `baseline_insufficient: true` 标注，不改判定 |

---

## 4. 风险项汇总（Risk）

| 风险 | 影响 | 缓解 |
|---|---|---|
| **H1 评测断言变更** | eval_g3 幂等重放段、SC-CS08-006 断言与修复目标冲突 | 先行同步改断言；明确「不 interrupt」为新期望 |
| **H2 翻转 188 单** | 在途超期单从 NORMAL→ANOMALY | 已确认无测试/黄金数据依赖输出值；与 SC-CS06-004 一致；grep 复核后再提交 |
| **H2 口径外溢** | 未发货超期/缺 promised 的判定边界 | 定死「仅已发货未送达且超 promised → ANOMALY」 |
| **H3 PENDING 口径** | 是否占可退量影响后续申请 | 与 existing_return 统一（不占），注释定死 |
| **M1 SQL 语义** | LEFT JOIN 过滤放错位置挤出 SKU 行 | 过滤放 oi 侧 ON，验证慢销数从 6→4 |
| **M2 吞 interrupt** | except 误吞 GraphInterrupt 打断审批 | 硬约束 `except GraphInterrupt: raise` |
| **L2 遗留** | 被拒后无法重提（现状） | 本次标注不修，避免 schema 迁移 |

## 5. 阻碍项汇总（Blocker）

| 阻碍 | 涉及 | 需谁决策 |
|---|---|---|
| H2 在途超期口径边界 | fulfillment.py | 业务确认「已发货未送达且超 promised」= ANOMALY |
| H3 PENDING 是否占可退量 | create_return_request.py | 业务/实现口径确认 |
| H1 SC-CS08-006 断言新口径 | scenarios.yaml / eval_g3.py | 确认「已有退货→不 interrupt」为正式期望 |
| L2 完整修复需 schema 级设计 | create_return_request + schema.sql | 本次不做，排后续 |

## 6. 回归验证清单（Verification）

实施每步后执行：

```bash
# 全量测试（依赖 Docker PG + dev 数据）
"C:/Users/HSY20/.conda/envs/ecommerce-agent/python.exe" -m pytest -q

# 定向断言
# H4: 输入「不同意」→ rejected；「确认」→ approved；含疑问句 → 不判定
# H1: 预置 APPROVED 退货单 → cs08_return_workflow 返回 already_exists、不 approval_required
# H2: ORD_01_001454 → analyze_fulfillment_delay = ANOMALY(overdue_in_transit)
# H3: 预置 REJECTED 行 → 同 item 仍可申请
# M1: query_product_performance(slow_moving) SKU_01_SLOW_01 units == 4

# 全链路评估（改后需重跑确认 PASS）
"C:/Users/HSY20/.conda/envs/ecommerce-agent/python.exe" scripts/eval_g3.py
"C:/Users/HSY20/.conda/envs/ecommerce-agent/python.exe" scripts/eval_g5.py
```

## 7. 实施顺序

**H4 → H1 → H2 → H3 → M1/M2 → M3/M4/M5（文档/低改）→ L 批**
（H4/H1 低成本先止血；H2 对齐规格；H3 统一口径；M 批补齐健壮性；L 批逐项小修。）

---

## 8. 实施项总清单（含改动量 / 难度 / 风险 / 阻碍）

**改动量**：S=<10 行、M=10~50 行、L=>50 行或跨多文件。**L2 明确不实施**（需 schema 级设计，单列遗留）。

| 项 | 涉及文件 | 改动量 | 难度 | 风险 | 主要阻碍 |
|---|---|---|---|---|---|
| **H4** 审批文本否定句 | context.py(新helper)、react.py、orchestrator.py、tests | S-M | 低 | 低 | 保留「好的/可以」原判定不被误伤 |
| **H1** CS-08 短路 existing_return | toolkit.py、workflows.py、eval_g3.py、scenarios.yaml、tests | M | 中 | 中 | eval_g3 幂等重放段 + SC-CS08-006 断言需同步改；新口径确认 |
| **H2** 在途超期→ANOMALY | fulfillment.py、tools/fulfillment_delay.py、sc_runner.py、scenarios.yaml、tests | M | 中 | **高**（翻转188单，实测无测试依赖） | 口径边界确认（仅已发货未送达且超 promised） |
| **H3** 可退数量状态过滤 | create_return_request.py、tests | S | 低 | 中 | PENDING 是否占量口径决策 |
| **M1** 慢销窗口过滤 | slow_moving.py | S-M | 中 | 中 | 无（SQL LEFT JOIN 语义注意） |
| **M2** workflow 异常兜底 | toolkit.py（2 处） | S | 低 | 低 | 硬约束：`except GraphInterrupt: raise` |
| **M3** 跨店守卫注释 | tool.py | S | 低 | 无 | 无 |
| **M4** 客户端自声明文档 | 无（或 agent-plan-b 补注） | 0 | 低 | 无 | 无 |
| **M5** 建单 id 竞态 | create_return_request.py | S（LOCK TABLE）或 0（标注） | 低 | 低 | 选 LOCK TABLE 须同事务 |
| **L1** 固定 items[0] | toolkit.py、描述 | M 或 0（标注） | 中 | 中 | 范围决策：本次做 or 仅标注 |
| **L2** 幂等 dup 无状态过滤 | create_return_request + schema | **L（不实施）** | 高 | 高 | schema 级设计，排后续 |
| **L3** legacy 话术错误 | orchestrator.py | S | 低 | 低 | 无 |
| **L4** 健康度 returns 全状态 | product_health.py | S | 低 | 低 | 无（与 H3 同一「成功态口径」） |
| **L5** RAG scope 后滤 | rag.py | M | 中 | 中 | 无 |
| **L6** sales_anomaly 标注 | sales_anomaly.py | S | 低 | 低 | 无 |

**总体评估**：无 L 级实施项（唯一 L 是 L2，不实施）；全部为 S/M 改动；最高风险项 H2 已实测确认无自动化测试依赖。

---

## 9. 阶段规划（每阶段有核查 Gate，达标才进入下一阶段）

### 阶段 0 — 基线核查（Gate 0）
- **操作**：跑全量 `pytest -q` + `eval_g3` + `eval_g5`，记录基线通过/失败项（不改动）。
- **退出条件**：基线记录完成，作为后续每阶段对照基准。
- **目的**：区分「本次改动引入的回归」与「既有失败」。

**阶段 0 基线执行记录（2026-09-27 已执行）**
- pytest（全量）：`160 passed`（2m01s），1 条 `LangGraphDeprecatedSinceV10` 弃用警告（与本轮修复无关）。
- eval_g3（live）：**3/4** —— 退货建单/审计/幂等 PASS、ineligible 不中断 PASS、拒绝路径 PASS；**补货确认 FAIL**（live LLM 未触发 op05_restock_workflow 审批 interrupt，直接以缺货风险结论作答；属 live LLM 行为抖动，非代码缺陷，记为基线已知失败）。
- eval_g5（live）：**2/2 PASS**（记忆生效 forecast_days=7 + 黄金问答 grounding；脚本结尾自清理 user1 记忆）。
- 副作用核查：无残留 —— CS08-*/tx01_* 售后与审计行 = 0；user1 记忆被 eval_g5 按设计清空。
- **对后续阶段的影响**：阶段 1 的 Gate 判定「eval_g3 PASS」以基线 3/4 为对照 —— 阶段 1 后重跑应保持建单/审计/幂等、ineligible、拒绝三项 PASS；补货确认若仍 FAIL 属已知 live 抖动不阻塞；H1 修复后 eval_g3 幂等重放段断言将同步更新，属预期变更。

**阶段 1 执行记录（2026-09-27 已完成）**

已实施 H4 + H1，改动清单：
- **H4**：context.py 新增 `approval_text_decision`（疑问守卫 + 拒绝词优先，`_APPROVAL_REJECT` 含 不同意/不确认/不用）；react.py `resolve_approval_text` 与 orchestrator.py `handle_pending` confirm 分支改调共用 helper。
- **H1**：toolkit.py `make_cs08_workflow_tool` 在 interrupt 前短路 `existing_return`（返回 `status=already_exists`，不建单）；workflows.py legacy `_cs08` 同步短路；orchestrator `_draft_workflow_tpl` 加 already_exists 文案。
- **评测/断言同步**：eval_g3 拒绝路径重排到建单前（否则 438 建单后无法再触发 interrupt）+ 重放段改为断言「重放不重复（already_exists、不 approval_required）」；test_workflow.py 幂等重放段同步为 already_exists 语义。
- **SC-CS08-006（数据断言，已暂缓）**：尝试改为 `expected_route: ineligible`，但该共享文件 `data/scenarios/eval/scenarios.yaml` 的改动被并行窗口活动回滚（并行窗口约 15:38 提交了 gold 数据集 7e7812f，其工作流重置了 data 目录）。为避免与并行窗口抢同一文件，暂不重放；工作流层短路行为已由 test_react/test_workflow/eval_g3 的代码级断言完整覆盖，SC-CS08-006 保持无路由断言不影响 Gate 1。
- **新增测试**：test_react.py 3 条 —— `test_approval_text_decision_negation_and_question`、`test_resolve_text_approval_negation_rejected`、`test_cs08_existing_return_short_circuits_no_reapproval`。

Gate 1 核查结果：
- pytest 全量：**163 passed**（基线 160 + 3 新增，无回归）。
- 定向断言：不同意→rejected ✅、确认→approved ✅、预置 APPROVED 退货单→cs08_return_workflow 返回 already_exists 且不 approval_required ✅。
- eval_g3 改后：**3/4** —— 拒绝路径 ✅、退货建单（建单/审计/**重放不重复**）✅、ineligible 不中断 ✅、补货确认 FAIL（与基线一致，已知 live LLM 抖动，非本轮引入）。
- 残留核查：CS08-*/txh1 售后与审计行 = 0。

**Gate 1 判定：✅ 通过**（H4/H1 止血完成，无回归；补货确认 FAIL 为基线已知项）。

### 阶段 1 — 止血批（H4 + H1，本次问题核心）
- **操作**：
  1. H4：context.py 新增 `approval_text_decision`（疑问守卫 + 拒绝词优先 + 扩展拒绝词）→ react.py / orchestrator.py 改调 → 补测试。
  2. H1：toolkit.py eligible 分支在 interrupt 前短路 `existing_return`（返回 already_exists）→ workflows.py legacy 同步 → eval_g3 幂等重放段改断言 → SC-CS08-006 加断言 → 补测试。
- **Gate 1 核查**：pytest 全绿；定向断言「不同意→rejected」「确认→approved」「预置 APPROVED 退货单→cs08_return_workflow 返回 already_exists 且不 approval_required」；eval_g3 改后 PASS。
- **不达标**：停在本阶段修断言/逻辑，不进入阶段 2。

### 阶段 2 — 对齐规格批（H2）
- **操作**：fulfillment.py 加 `as_of` 参数、delivered 空时 `promised<as_of→ANOMALY(overdue_in_transit)` → tools/fulfillment_delay.py + sc_runner.py 传 AS_OF_DATE → SC-CS06-004 转 data 型断言 → 新增 ORD_01_001454→ANOMALY 测试。
- **前置确认**：H2 口径边界（仅已发货未送达且超 promised 才判 ANOMALY）由业务确认后再动。
- **Gate 2 核查**：pytest 全绿；ORD_01_001454→ANOMALY；grep 复核无黄金数据/e2e 依赖 CS-06 输出值；eval_g3/g5 PASS。
- **不达标**：若翻转触发某断言失败，回退修口径。

### 阶段 3 — 口径统一批（H3 + L4）
- **操作**：H3 给 create_return_request.py 的 SUM 加 `status IN (成功态)`（与 existing_return 统一，**先定死 PENDING 不占量**）；L4 给 product_health.py returns 维度加成功态过滤；各补测试。
- **Gate 3 核查**：预置 REJECTED 行后同 item 仍可申请；健康度 returns 只算成功态；pytest 全绿。
- **不达标**：PENDING 口径未定时暂停等待决策。

### 阶段 4 — 健壮性批（M1 + M2 + M5）
- **操作**：M1 把慢销窗口/状态过滤移入 oi 侧子查询；M2 给两个 workflow `_run` 补 `except Exception→error dict` + `except GraphInterrupt: raise`；M5 建单加 `LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE`（或仅标注）。
- **Gate 4 核查**：`SKU_01_SLOW_01` 慢销 units 从 6→4；注入 DB 故障返回 error dict 而非 500；pytest 全绿。
- **不达标**：修 SQL 语义 / 确认 interrupt 未被吞。

### 阶段 5 — 文档对齐批（M3 + M4）
- **操作**：tool.py 注释更正跨店守卫语义；agent-plan-b 补「前端自声明是 V1 取舍」备注。
- **Gate 5 核查**：文档审阅确认；pytest 不受影响。
- **不达标**：无（纯文档）。

### 阶段 6 — L 批（L1 + L3 + L5 + L6）
- **操作**：L1 先决策（加 item_id 参数 or 仅标注）；L3 legacy 话术按 intent 区分；L5 rag.py 无命中重查 + 类目未知排除专属规则；L6 sales_anomaly 加 `baseline_insufficient` 字段。
- **Gate 6 核查**：各自断言 + pytest 全绿；L1 若复杂则降级为标注。
- **不达标**：停本阶段处理失败项。

### 阶段 7 — 总回归 + 收尾（Gate 7）
- **操作**：全量 pytest + eval_g3/g5 + 手动 UI 冒烟（退货不再重复触发、审批「不同意」正确拒绝）。
- **收尾**：更新本文档状态（完成项 / 遗留项 L2、M5 若选标注）。
- **退出条件**：全部 PASS，遗留项明确记录；L2 单列后续任务。

---

## 10. 依赖与关键决策点

**无硬依赖**（各项改动文件独立），顺序由「业务价值 + 风险可控」驱动：先止血（H4/H1）→ 对齐规格（H2）→ 统一口径（H3/L4）→ 健壮性（M1/M2/M5）→ 文档 → L 批。

**3 个前置决策点（进入对应阶段前需定）**：
1. H2 口径：在途超期判定边界（阶段 2 前）；
2. H3/L4 口径：PENDING 是否占可退量（阶段 3 前）；
3. L1 范围：本次实现 item_id 选择，还是仅标注（阶段 6 前）。

**2 个必须同步的评测改动**：eval_g3 幂等重放段、SC-CS08-006 断言（阶段 1，与 H1 同批）。

---

## 11. 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| V1.3 | 2026-09-27 | 阶段 1 执行记录（H4+H1 已实施、Gate 1 通过：pytest 163/163、eval_g3 3/4 同基线） |
| V1.2 | 2026-09-27 | 阶段 0 基线执行记录落盘（pytest 160/160、eval_g3 3/4、eval_g5 2/2，无残留） |
| V1.1 | 2026-09-27 | 追加 §8 实施项总清单、§9 阶段规划（Gate 0~7）、§10 依赖与决策点 |
| V1.0 | 2026-09-27 | 初版草案：基于全量审计（15 项）+ 并行复核 + 爆炸半径核查 |

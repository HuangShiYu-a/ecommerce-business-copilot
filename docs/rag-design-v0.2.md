# E-commerce Business Copilot — RAG / Knowledge Design V1.0

> 文档性质：**Knowledge / RAG 契约**（非实现代码）  
> 版本：**V1.0**  
> 状态：**Frozen**（2026-09-13；经 Cross-Contract Review；未经用户批准不得改写核心契约）  
> 上游契约（只读，冲突时以上游为准）：  
> - [business-scenarios-v1.md](./business-scenarios-v1.md) V1.1  
> - [core-tool-design-v1.md](./core-tool-design-v1.md) V1.1 Frozen  
> - [database-design-v1.md](./database-design-v1.md) **V1.2.3 Frozen**（含 §23 / §6.3 CS-06↔T-K-01）  
> 约束：不得改写上游业务 / Tool / DB 核心定义；新缺口记入 Open Questions 或走变更提案。  
> 文件名保留 `rag-design-v0.2.md`（历史路径）；**以文头版本 V1.0 Frozen 为准**。

---

## 0. 本版已采纳决策（D1–D7）

| ID | 决策 | 摘要 |
|----|------|------|
| D1 | A | 顶层 `knowledge_type` 对齐 T-K-01；子类用 `section` / tags / metadata |
| D2 | A（收窄） | 无完整冲突平台；可编码消解极少条；否则 `undetermined` / 转人工；禁止 LLM 瞎选规则 |
| D3 | M-C | 生命周期正式列：已由 **Database V1.2** 落地 |
| D4 | A | V1 不做 Rerank |
| D5 | A | V1 = Metadata Filter + Vector |
| D6 | B | 普通任务可自主调 Knowledge；**CS-08 Workflow 强制**取规则再 Eligibility |
| D7 | B | 正式结论分场景：资格→Analysis；指标→Analysis；建议→Recommendation；解释/草稿→LLM |

---

## 1. RAG 定位与边界

### 1.1 职责

RAG / Knowledge Base 负责：**存储、组织、检索并向 Agent 提供业务规则与正式知识文档**。  
不负责：实时业务事实、派生指标计算、高风险写库。

### 1.2 与 Database

| 侧 | 内容 |
|----|------|
| PostgreSQL 业务表 | 订单、库存、商品、售后单等**事实** |
| `store_configs` | 安全库存、lead time、阈值、权重等**计算旋钮** |
| `knowledge_*` + pgvector | 政策 / SOP / 规则**文本** |

原则：事实优先 DB；规则优先 Knowledge；配置参数优先 Config。

### 1.3 职责分层（含补货）

| 层 | 退货例 | 补货例 |
|----|--------|--------|
| Fact | 订单状态、签收时间、行数量 | 库存、销量 |
| Config | （少）店内阈值若有 | safety_stock、lead_time |
| Knowledge | 七日无理由、例外类目文 | 大促备货政策等**文字**（可选） |
| Derived / Analysis | `check_return_eligibility` 三态 | 缺货风险、日均销 |
| Recommendation | — | `calculate_restock_recommendation` |
| LLM | 解释、客服草稿 | 解释建议 |
| Action + HITL | `create_return_request` | 补货执行（V1 常 Phase2） |

### 1.4 同时使用 DB + RAG

例如 CS-08：Query 事实 + Knowledge 规则 → Analysis 资格 → LLM 解释 →（可选）Action。

---

## 2. Knowledge Scope

### 2.1 `knowledge_type`（与 T-K-01 对齐）

`after_sales` | `customer_service` | `inventory` | `operations` | `logistics` | `pricing` | `promotion` | `general`

### 2.2 子类（D1）

不扩展 Tool 枚举。示例：

```text
after_sales → section: return | exchange | refund | damaged_item
inventory   → section: stockout | overstock | replenishment | safety_stock
```

`section` 落在 `knowledge_chunks.section`（及/或 metadata tags）。

### 2.3 V1 P0 语料优先（P0-Core）

对齐 Business/Tool P0（尤其 CS-06 / CS-08 / OP-05 / OP-07），**最小语料**而非运营知识大平台：

```text
P0-Core
├── after_sales     → 退货资格与店铺售后（CS-08/09）
├── logistics       → 基础发货时效 / 物流异常处理规则（CS-06）
└── operations      → 极少量 Store 商品健康/类目文字规则（OP-07）
                  → 可选：极少量库存文字政策（OP-04/05 解释用）
```

**明确区分（OP-07 / 补货）：**

| 内容 | 归属 |
|------|------|
| 健康分权重、阈值、safety_stock、lead_time 等数值旋钮 | **`store_configs` + Calculation** |
| 评分维度说明、特殊类目例外、备货文字政策等 | **RAG（少量）** |

**后置（非 V1 P0-Core）：** `pricing` / `promotion` / 完整生命周期与清仓语料、客服升级 SOP 等（可为 P1）。

详见 §12。

## 3. Knowledge Governance

### 3.1 层级

`legal` / `platform` / `store`（与 DB `layer`、T-K-01 一致）。

默认**解释原则**：Legal > Platform > Store；不足以覆盖所有例外。

### 3.2 冲突四段（概念）

| 段 | 含义 | V1 |
|----|------|-----|
| Detection | 候选规则可能互斥 | 最小：多条高相关且结论倾向矛盾 → 标冲突 |
| Resolution | 按**已编码**规则消解 | 仅 §3.3 清单；禁止猜测 |
| Explanation | 说明依据 | LLM + `rule_sources` |
| Escalation | 无法确定 | `undetermined` / `RULE_CONFLICT` + 人工 |

### 3.3 V1 正式有限消解规则（≤5，非通用引擎）

> 下列为 **V1 可执行原则**；未命中则不得自动选边 → `undetermined` / `RULE_CONFLICT` + 人工。  
> **不做**全库冲突扫描平台或开放域 specificity 推理引擎。

| # | 规则 | V1 状态 | 电商例子 |
|---|------|---------|----------|
| R1 | **仅当前有效文档**参与判定与默认检索（DB V1.2 半开区间谓词） | **可执行** | `INACTIVE` 或已过 `effective_to` 的旧版七日政策不得命中 |
| R2 | **适用范围明显不符**的候选规则排除（类目/商品类型/场景标签与事实不一致） | **可执行（服务层过滤）** | 订单商品为「定制类」时，不适用「普通商品无理由」一般条款 |
| R3 | **已标明的特殊规则**优先于同层更一般表述（specificity） | **可执行（有限）** | Store 文档写明「耳机类签收 7 日内可退」优先于同店「默认 15 日」的笼统句——**仅当**适用范围字段/section 可明确比对 |
| R4 | **权威层级**：仅当适用范围已明确可比时，`legal > platform > store` | **可执行（有限）** | 店铺「概不退货」不得压过已适用的法定/平台七日底线（在事实已落入该适用范围时） |
| R5 | 经 R1–R4 仍无法确定 | **可执行** | 返回 `undetermined` / `RULE_CONFLICT`，说明冲突来源，转人工 |

说明：R3/R4 依赖种子文档带清晰 `layer`/`section`（及可选适用标签）；无法结构化比对时走 R5，**禁止 LLM 猜哪条更合理当作正式结论**。

### 3.4 来源与审核（V1 约束，非平台）

可信来源入库；禁止未审核网络文 / AI 自造规则冒充权威；失效知识不得作为当前有效命中。

---

## 4. Metadata 与过滤

### 4.1 Document 正式列（对齐 DB V1.2）

`knowledge_type`, `layer`, `platform`, `store_id`, `status`, `version`, `effective_from`, `effective_to`, `source_uri`, …

### 4.2 JSONB / section

| 用途 | 落点 |
|------|------|
| 子类、条款标题 | `chunks.section` |
| 易变 tags、适用类目列表等 | JSONB |
| 生命周期真相 | **仅 document 列**（chunk 不冗余 effective 为真相源） |

### 4.3 Retrieval Filter（V1 必须）

在向量检索前（或候选集上）应用：

- `knowledge_type`（及可选 section）  
- `layer` / `platform`  
- `store_id`：**当前店 ∪ 全局**；由服务层依据 **`user_context.store_id` 注入**，**LLM 不得自行提供或覆盖**店铺隔离条件（不新增 T-K-01 必填入参）  
- **当前有效谓词**（Database §13.21 半开区间）

`version`：展示/审计/选版；一般不作相似度条件。

---

## 5. Document Structure & Chunking

- 按业务语义 / 条款组织；一 chunk 尽量完整规则单元  
- 禁止：无脑定长截断把一条规则劈成无上下文的两半；禁止整库单 chunk  
- V1 启发式：一节/一条款 ≈ 一 chunk；具体长度 Open（实验）

---

## 6. Retrieval Pipeline（V1）

```text
Metadata Filter（含有效窗）
    → Vector Search（pgvector）
    → Top-K（配置默认，非 LLM 自由决定）
    → Context（供 LLM 解释；资格结论仍走 Analysis）
```

### 6.1 Non-Goals（V1）与升级触发

| 能力 | V1 | 升级信号 |
|------|-----|----------|
| Hybrid（关键词+向量） | 不做 | Eval：条款编号/专名精确召回差 |
| Rerank | 不做 | Top-K 内正确段长期排后 |
| Graph RAG / 复杂 rewrite | 不做 | — |

---

## 7. Agent 与 Knowledge Tool

### 7.1 唯一入口

`search_business_knowledge`（T-K-01）。Agent 不直操向量索引。

入参保持契约：`query`, `knowledge_type`, `platform`, `layer`。  

**实现边界：** 服务层自动注入 `user_context.store_id` 并应用「当前店 ∪ 全局」与有效窗过滤；**LLM / Agent 不得通过入参覆盖店铺隔离**。

### 7.2 调用策略（D6）

| 场景 | 策略 |
|------|------|
| 普通咨询 | Agent 可自主决定是否调用 Knowledge |
| **CS-06 物流异常** | 建议 Workflow 在需要处理建议时取得 `logistics` 规则（与 T-A-01 可选知识依赖一致） |
| **CS-08 退货资格** | Workflow **强制**取得相关规则（调 T-K-01 或等价注入）→ 再 `check_return_eligibility` |

不建独立复杂 Retrieval Router 产品。

---

## 8. 谁产生正式结论（D7）

| 任务 | 正式结论来源 | LLM 角色 |
|------|--------------|----------|
| 政策解释 / 回复草稿 | — | 基于 RAG+事实生成 |
| 能否退货 | **`check_return_eligibility`** 三态 | 解释 `decision` / reasons |
| GMV/健康分/异常等 | Analysis Tools | 解释 |
| 补货建议 | Recommendation + Config + Facts | 解释 |
| 建退货单等 | Action + 审批 + 审计 | 确认话术 |

**禁止**：仅凭「读完 RAG Context」由 LLM 输出正式 `eligible`。

推荐编排：

```text
Facts (Query/DB) + Rules (T-K-01)
    → check_return_eligibility
    → eligible | ineligible | undetermined
    → LLM 解释 / 草稿
    →（执行）HITL → create_return_request
```

---

## 9. Failure Handling

| 情况 | 行为 |
|------|------|
| 无命中 / 知识不可用 | 不编造规则；说明无法确认；可追问或转人工 |
| 低相关 | 不强行定论；可收窄重查或 `undetermined` |
| 冲突且无 R1–R5 可消解 | `undetermined` / `RULE_CONFLICT` + 人工 |
| 过期/未生效 | 有效谓词排除；不进入默认候选 |

---

## 10. 与高风险 Action

RAG 只提供依据。写状态仍受 Tool Risk Policy：`requires_approval`、`audit_required`、幂等。

---

## 11. V1 范围

### 必须

- 边界与分层（Fact/Config/Knowledge/Decision/Action）  
- taxonomy + section 约定  
- DB V1.2 生命周期过滤  
- Metadata + Vector + 默认 Top-K  
- T-K-01 入口；CS-08 强制知识路径  
- 失败不幻觉；冲突不瞎选  
- P0 语料骨架 + 最小 Eval 骨架（§12–13）

### 非目标

完整审批平台、自动全库冲突引擎、Hybrid/Rerank（直至触发）、Graph RAG、**pricing/promotion/完整生命周期等非 P0-Core 语料一次铺齐**。

---

## 12. P0 语料清单（骨架）

| 优先级 | 建议文档主题 | type | layer 例 | 对齐场景 |
|--------|--------------|------|----------|----------|
| P0-Core | 七日无理由退货（法定/平台底线） | after_sales | legal/platform | CS-08 |
| P0-Core | 例外商品 / 不可退类目 | after_sales | platform/store | CS-08 |
| P0-Core | 完好要求与凭证 | after_sales | platform/store | CS-08 |
| P0-Core | 店铺补充售后政策 | after_sales | store | CS-08/09 |
| P0-Core | 发货时效 / 物流异常处理基础规则 | logistics | platform/store | **CS-06** |
| P0-Core | 商品健康维度说明 / 特殊类目运营例外（极短） | operations | store | **OP-07** |
| P0 可选 | 库存/备货文字政策（非数值旋钮） | inventory | store | OP-04/05 解释 |
| P1 | 客服升级/补偿边界 SOP | customer_service | store | CS-11 等 |
| 后置 | 定价/促销/完整生命周期与清仓 | pricing/promotion/… | — | 非 V1 最小集 |

**提醒：** 健康分权重、安全库存天数、lead time 等**不得**只写在 RAG 正文代替 `store_configs`。

具体正文由人工编写种子，禁止爬取冒充平台真理。

---

## 13. 最小 Eval 骨架（10–20 条量级）

每条建议含：`query`、期望 `knowledge_type`/`section`、是否应命中、若走 CS-08 时期望三态倾向、冲突样例标记。

用途：验证过滤、召回、以及「未调 Knowledge / LLM 越权定论」回归。指标细节（Recall@K 等）实施期补。

---

## 14. Open Questions / Implementation Notes

> Cross-Contract SOFT 收口于此，**不扩 V1 范围**。

### 14.1 仍开放（实验 / 实施）

| ID | 问题 | 状态 |
|----|------|------|
| Q-emb | Embedding 模型与维度 | Open（DB 占位 1536） |
| Q-topk | 默认 Top-K 数值 | Open（实验） |
| Q-chunk | chunk 长度启发式标定 | Open |
| Q-R3-tags | 特殊类目适用标签在 JSONB 中的约定细节 | Open（实施期） |
| Q-R3-R4 | Specificity（R3）与 Authority（R4）交叉时的细优先级 | Open；**不可比 → R5**，不做通用 Resolver |
| Q-elig-consume（CC-S4） | Eligibility 如何消费规则文本（原文 / 抽取结构化） | → **Workflow / Technical**；底线：不替代三态 |
| Q-tk01-meta（CC-S3） | T-K-01 是否对外返回 version/effective_* | → **Technical**；V1 过滤在服务端完成，**不改** Frozen Tool 出参 |
| Q-eval-cover（CC-S5） | Eval 补 CS-06 / OP-07 各 2～3 条 | → **Evaluation**；不扩成独立评估平台 |

### 14.2 已决策 / 已关闭

| ID | 项 | 状态 |
|----|-----|------|
| D1–D7 | 主轴决策 | **已决策** |
| D2 R1–R5 | V1 有限规则 | **已收口（§3.3）** |
| D3 落库 | version / effective_* | **DB V1.2** |
| P0 语料 | CS-06 / OP-07 | **已收口（§2.3 / §12）** |
| CC-S1 | DB §23 CS-06 漏 T-K-01 | **已关闭（DB V1.2.2）** |
| CC-S6 | 重叠 ACTIVE 有效窗 | **DB-G13 Future** |

### 14.3 Implementation Notes（留给 Workflow，不改本契约正文）

| ID | 说明 |
|----|------|
| **CC-S2** | CS-06：`analyze_fulfillment_delay` 判定是否延迟；若输出**处理建议/客服话术**，再调 `search_business_knowledge`（`logistics`）。非「全程强制 RAG」。 |
| HITL 分层 | `T-A-09` 资格三态 ≠ 人工批准执行 ≠ `T-X-01` 写库；Workflow 须三分叉。 |

---

## 15. 设计原则摘要（V1 Frozen）

1. RAG ≠ 事实库；Config ≠ 政策长文。  
2. 有效知识可执行过滤（status + 半开时间窗）。  
3. 单 Tool 入口；店铺上下文隔离（服务层注入 `store_id`）。  
4. 关键路径 Workflow 约束；普通路径可自主。  
5. 正式资格/指标结论不交给「只读了 RAG 的 LLM」。  
6. V1 检索：Metadata + Vector；Hybrid / Rerank 有升级触发条件后置。  
7. 冲突：有限 R1–R5；不能确定则 undetermined / 人工。  
8. **本文 V1.0 Frozen**；变更须提案 + 用户批准 + Cross-Contract 影响分析。

### V1 明确后置

Hybrid、Rerank、复杂 Resolver、复杂 Router、完整知识治理平台、改 Tool 出参扩元数据、采购/建单类补货 Action（见 Tool Gap-02）。

---

## 16. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V0.1 | （用户草案） | 初稿思路 |
| V0.2 | 2026-09-13 | 按 Proposal A + D1–D7 落地 Draft；对齐 Database V1.2 |
| V0.2.1 | 2026-09-13 | P0-Core logistics/operations；Config vs RAG；R1–R5；store_id 注入 |
| **V1.0 Frozen** | 2026-09-13 | Cross-Contract 通过；CC-S1 由 DB 关闭；SOFT 收口 §14；正式冻结 |

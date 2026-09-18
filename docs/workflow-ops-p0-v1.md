# Workflow — Ops P0 Bundle V1.0.2（WF-OP05 / OP-04 / OP-07 / OP-08 / OP-03）+ 场景索引

> 文档性质：**业务 Workflow 契约初稿合集**（非 LangGraph 实现、非造数）  
> 版本：**V1.0.2**  
> 状态：**V1.0.2 Frozen**（七 WF P0 合集；变更须用户批准新版本；不改四份业务 Frozen）  
> 方法依据：[workflow-design-spec-v1.md](./workflow-design-spec-v1.md)  
> 模板参照：[workflow-cs08-09-v1.md](./workflow-cs08-09-v1.md)、[workflow-cs06-v1.md](./workflow-cs06-v1.md)  
> 上游（只读）：Business V1.1 · Tool V1.1 Frozen · Database V1.2.3 Frozen · RAG V1.0 Frozen · [AGENTS.md](../AGENTS.md)  
> 约束：不得改写 Frozen；冲突见本文 **§A / 各 WF §15**。  
> 收口策略：本批 **5 个 P0 Ops WF** + 已有 CS 两模板 = Workflow Design Phase 目标集合；P1/P2 **仅索引**，不写正文。

---

## A. 合集说明与 Cross-Workflow 约定

### A.1 本文件包含

| 章节 | 内容 | R1 |
|------|------|-----|
| §B | **WF-OP05** 补货建议（学习锚点 / 建议首个实现 WF） | ✅ 需要 Workflow |
| §C | **WF-OP04** 缺货风险 | ✅ |
| §D | **WF-OP07** 商品健康度 | ✅ |
| §E | **WF-OP08** 销售异常诊断 | ✅ |
| §F | **WF-OP03** 滞销商品识别 | ✅ |
| §G | 全场景「是否需要独立 WF」索引（含 P1/P2，无正文） | — |

### A.2 统一章节结构（每条 WF）

每条 Workflow 均按下列 **15 段**编写（与批量设计指令一致）：

1. Scope  
2. Why Workflow（R1）  
3. Formal Result Source  
4. Main Flow  
5. Nodes  
6. Conditional Edges  
7. State  
8. Recovery  
9. Human Intervention  
10. Business Confirmation  
11. Approval  
12. Action  
13. LLM Boundary  
14. Failure Handling  
15. Cross-Contract Review  

### A.3 跨 WF 必须遵守的映射原则

> **Tool 输出业务分析结果；Workflow 根据结构化结果决定路径。**  
> 禁止每个 Workflow 私自重新发明状态语义。

| Workflow | Tool 侧正式结果（示例） | Workflow 路由状态（编排映射，非 LLM） |
|----------|-------------------------|--------------------------------------|
| OP-04 | `high_risk_products[]`（条目可含 `risk_level`） | `HAS_RISK` ⇔ 数组非空；`NO_RISK` ⇔ 成功且空；`UNDETERMINED` ⇔ 失败/不足（见 §C.6） |
| OP-05 | `recommended_quantity` + `method` | `HAS_RECO` \| `NO_RECO` \| `UNDETERMINED` |
| OP-07 | `score` / `level` / `data_completeness` | 按 `level` 或完整度策略分支（见 §D） |
| OP-08 | `is_anomaly` + `anomaly_basis` | `NORMAL` \| `ANOMALY` \| `UNDETERMINED` |
| OP-03 | T-A-04 候选集；可选 T-A-05 `level`/`risk_factors`（**≠** 滞销风险等级） | `HAS_CANDIDATES` \| `EMPTY` \| `UNDETERMINED` |

**命名卫生：** 分析展望窗口统一用 **`horizon_days`**（Tool 若接受 `forecast_days` 仅作别名；对外文档与 State 不主推 `forecast_days`，避免误解为完整 forecasting）。

**编排 State 字段（ON-4 收口）：** 七 WF 实现统一使用 **`route_status`**。取值随各 WF 路由族（上表）；CS-08-09 可将 T-A-09 `decision` 同步写入同一字段。禁止并行维护 `anomaly_status` 第二字段。

### A.4 共享计算服务（禁止双算法）

| 服务 | 消费方 | 口径 |
|------|--------|------|
| **Inventory Calculation Service** | OP-04 `analyze_stockout_risk`、OP-05 `calculate_restock_recommendation` | 日均销估计 / DOI / 预计缺货日 **同一实现**；销量 units 遵守 DB **§12A** |
| **Sales Calculation Service** | OP-03/07/08 等销售类指标 | GMV/orders/units/AOV 等遵守 **§12A** |
| **Health Scoring（Domain 计算）** | OP-07（OP-03 可复用） | 权重来自 **StoreConfig**；文字例外来自 Knowledge |

### A.5 已知契约张力（上报，不静默改 Frozen）

| ID | 说明 | 本合集处理 |
|----|------|------------|
| **Gap-OP05-Action** | Business OP-05：采购量确认须审批、创建补货申请需审批可追溯；Tool **Gap-02**：`create_restock_request` **未进 Core**，V1 以建议+确认为主 | WF-OP05：V1 做到 **Recommendation + Business Confirmation**；**不**实现采购建单 Action；Phase2 再接 Approval+Action |
| **Gap-OP03-Profit-Surface** | Business OP-03 输出含**利润**与风险等级；T-A-04 出参**无** `profit`；Core 无独立利润查询面 | V1：利润若进入本场景，**仅能**经 T-A-05 健康维**间接**承载；**不得**宣称 T-A-04 已输出利润；**不得**把 `health.level` 自动等同「滞销风险等级」。不上新 Tool / 不改 Frozen |
| **Config vs RAG** | 安全库存/lead time/健康权重/异常阈值 = **StoreConfig**；RAG 仅文字政策/类目例外 | 各 WF 写清：评分/阈值缺失 → UNDETERMINED 或降级，**禁止**用 RAG 补数值旋钮 |

---

## B. WF-OP05 — 补货建议

### B.0 Contract 对齐声明

| 层 | 对齐要点 |
|----|----------|
| **Business** | 库存 → 销量趋势 → 历史销量需求估计 → 安全库存/采购周期 → 建议量；**非完整 forecasting**；建议可自动，采购执行另议 |
| **Tool** | `get_inventory`、`query_sales_metrics`、（可选）`analyze_stockout_risk`、`calculate_restock_recommendation`（T-R-01）；可选 `search_business_knowledge`（inventory）；**无** `create_restock_request` |
| **Database** | Inventory、OrderItem、StoreConfig（lead time / safety）；指标不落宽表；§12A |
| **RAG** | 可选 inventory 文字政策（解释）；**数值旋钮不在 RAG** |

---

### 1. Scope

**In Scope**

```text
解析补货分析范围（SKU/商品/类目/默认高风险集）
  → 加载库存与销售事实
  →（可选）缺货风险预筛
  → Inventory Calculation + T-R-01 生成建议量
  → LLM 解释（标注 method=historical_sales_estimate）
  → Business Confirmation（运营确认是否采纳建议清单/数量）
  → END（V1 不创建采购单）
```

**Out of Scope**

- 创建采购单 / `create_restock_request`（Phase2）  
- 完整时序/季节性/促销驱动的 forecasting 系统  
- 清仓/调价/下架执行（OP-06/09/12）  

---

### 2. Why Workflow（R1）

满足 R1：多域事实 → **确定性计算服务** → Recommendation Tool → 解释 → **人工确认**；存在「无建议 / 数据不足」分支。  
**不是**单次 `get_inventory` 查询。

---

### 3. Formal Result Source

| 结论 | 来源 |
|------|------|
| 日均销估计、DOI、预计缺货日 | **Inventory Calculation Service**（与 OP-04 共用） |
| 建议补货量、reasons、method | **T-R-01 `calculate_restock_recommendation`** |
| 是否「需要补货」的业务路由 | 编排层根据 T-R-01 输出映射（见 §6），**非 LLM** |
| 库存政策文字解释 | 可选 **T-K-01**（inventory） |
| 是否采纳建议 | **Business Confirmation**（人） |

---

### 4. Main Flow

```text
运营输入
  → N0 Intent & Scope Validation（store_id、目标 SKU/商品/类目、horizon_days?）
  → 范围是否可解析？
        否 → 澄清 → 回 N0
        是 → N1 Load Inventory & Sales Facts
              ├── get_inventory
              └── query_sales_metrics（时间窗按 Store/默认策略）
  → 计算所需事实是否足够？
        否 → Recovery / UNDETERMINED
        是 → N2 Stockout Pre-screen（默认开启；缩小「谁要补」候选）
              └── analyze_stockout_risk
              └── **可跳过条件：** 调用方已指定明确 SKU/商品集合且只需算建议量
  → N3 Restock Recommendation
        └── calculate_restock_recommendation（逐 SKU 或批量由实现约定）
  → 【CE】HAS_RECO | NO_RECO | UNDETERMINED
  → N4（可选）Load Inventory Policy Text（仅解释需要时）
  → N5 Result Presentation（建议表 + method 标注 + 依据）
  → N6 Business Confirmation（确认采纳/修改备注/拒绝）
  → END（记录确认结果；不写采购单）
```

**N2 与 Tool 组合示例对齐：** Tool §10 常见路径含 `analyze_stockout_risk` → `calculate_restock_recommendation`；本 WF 将 N2 定为**默认预筛**，指定 SKU 算量时可跳过（非删除该能力）。

**禁止形态：** LLM 根据「感觉」直接给出建议采购量；或绕过 T-R-01 用 RAG 算数量。

**Open Note 关闭（ON-2 → Technical）：** V1 Confirmation **不要求** Frozen Tool 意义上的 `approver_id`（无 Action）。操作者角色、Confirmation 是否记应用日志 → **Technical Design**；禁止为实现方便改 Frozen Tool 或虚构 Approval。

---

### 5. Nodes

| Node | 业务职责 | Tool / 机制 |
|------|----------|-------------|
| N0 | 意图（补货建议）、范围与 horizon 校验 | LLM 抽槽 |
| N1 | 加载库存与销售事实 | `get_inventory` + `query_sales_metrics` |
| N2 | 缺货预筛（默认；指定 SKU 可跳过） | `analyze_stockout_risk` |
| N3 | 正式补货建议 | `calculate_restock_recommendation` |
| N4 | 可选库存政策文字 | `search_business_knowledge` |
| N5 | 结果呈现与解释 | LLM（非 Tool） |
| N6 | 确认是否采纳建议 | HITL Business Confirmation |

---

### 6. Conditional Edges

| 路由状态 | 映射依据（结构化） | 下一步 |
|----------|-------------------|--------|
| `HAS_RECO` | 存在 `recommended_quantity > 0`（或策略定义的正建议）的条目 | N4? → N5 → N6 |
| `NO_RECO` | 计算成功但无需补货（数量为 0 / 未达补货点） | N5 说明「暂无补货建议」→ END（可跳过 N6） |
| `UNDETERMINED` | `DATA_UNAVAILABLE` / 关键配置缺失 / 销量窗口无效等 | Recovery 或 N5 说明不确定 → Intervention |

---

### 7. State

**建议保留**

```text
request_id, user_id, role, store_id
scope（product_ids[] / sku_ids[] / category_id?）
horizon_days?
inventory_snapshot_ref?（摘要：sku, available_qty, safety_stock）
sales_period, sales_metrics_summary?
stockout_prefilter_ref?（可选）
recommendations[]（sku, recommended_quantity, avg_daily_sales_est,
  safety_stock?, lead_time_days?, estimated_stockout_date?, reasons[], method）
route_status（HAS_RECO|NO_RECO|UNDETERMINED）
knowledge_reference?（可选）
confirmation_status?, confirmed_quantities?（人可改备注，不以人口头数覆盖系统计算真相）
error_code?, current_step?
```

**不进 State：** DB 会话、全量订单行、全量 RAG chunks。

---

### 8. Recovery

```text
缺库存或销量窗口 → 补查 / 调整时间窗 → 重入 N1/N3
缺 lead_time / safety 配置 → 使用 StoreConfig 默认或 UNDETERMINED（禁止臆造天数）
部分 SKU 失败 → 部分成功呈现 + 失败项标注
```

---

### 9. Human Intervention

事实/配置长期不足、权限失败、计算服务不可用、运营范围严重歧义且无法澄清。

---

### 10. Business Confirmation

**需要（V1 主闸门）：** 运营确认是否采纳本批建议（及备注）。  
确认 ≠ 改写系统计算结果为「真相」；若人要改数量，应记为「人工调整意图」，Phase2 Action 再带审批。  
Business 文案中的「审批人确认」在 **V1 无建单 Action** 时映射为本 Confirmation（人决定是否采纳 Recommendation）；**不是**虚构的 Approval Node。

---

### 11. Approval

**V1：无采购建单则无 Approval Node。**  
Phase2 接入 `create_restock_request` 时：Confirmation 之后增加 Approval + Audit。

---

### 12. Action

**V1：无。** 禁止 LLM/本 WF 直写采购相关业务表。

---

### 13. LLM Boundary

| 允许 | 禁止 |
|------|------|
| 抽槽、解释 T-R-01、组织建议话术 | 编造库存/销量/建议量 |
| 说明 method=historical_sales_estimate 局限 | 宣称「精准预测/季节模型」 |
| | 无确认创建采购单 |

---

### 14. Failure Handling

| 情况 | 行为 |
|------|------|
| 无权限 / 跨 store | FORBIDDEN |
| 库存或销售不可用 | DATA_UNAVAILABLE → UNDETERMINED |
| 配置缺失 | UNDETERMINED 或降级默认（须在 basis 标明） |
| Knowledge 不可用 | 仍可输出数值建议；解释标注「政策文本不可用」 |

---

### 15. Cross-Contract Review

| 层 | 结论 |
|----|------|
| Business | ✅ 建议链路；⚠️ 建单审批见 Gap-OP05-Action |
| Tool | ✅ T-R-01；与 stockout 共用计算服务 |
| DB | ✅ Inventory + OrderItem + StoreConfig；§12A |
| RAG | ✅ 可选 inventory 文字；旋钮在 Config |
| Spec | ✅ R1–R12；无强行 Action |

**Data Requirements 要点（一句话）：** 需可复现的 SKU 库存（含 safety）、符合 §12A 的销量时间线、StoreConfig lead_time/补货策略；Scenario 引用真实 `store_id`/`sku_id`。

---

## C. WF-OP04 — 缺货风险分析

### C.0 Contract 对齐声明

| 层 | 对齐要点 |
|----|----------|
| **Business** | 当前库存 + 历史销量估计消耗 + 安全库存/补货周期 → 风险清单；模型只解释 |
| **Tool** | `get_inventory`、`query_sales_metrics`、`analyze_stockout_risk`（T-A-07） |
| **Database** | Inventory、OrderItem、StoreConfig；§12A units |
| **RAG** | 可选库存政策解释；**不**裁定 risk_level |

---

### 1. Scope

**In Scope**

```text
范围校验 → 加载库存/销售 → T-A-07 缺货风险分析
  → HAS_RISK | NO_RISK | UNDETERMINED
  → 呈现风险清单（DOI、预计缺货日、risk_level）+ 解释
  → END（无 Action）
```

**Out of Scope**

- 生成补货量（→ 移交 **WF-OP05**）  
- 创建采购单  
- 用 LLM 指定 risk_level  

---

### 2. Why Workflow（R1）

多事实 → 确定性风险分析 → 按清单是否非空分支呈现 → 可与 OP-05 衔接；超出「查一下库存」。

---

### 3. Formal Result Source

| 结论 | 来源 |
|------|------|
| avg_daily_sales_est / days_of_inventory / estimated_stockout_date / 条目 `risk_level` | **T-A-07**（内部调用 Inventory Calculation Service；纳入清单的阈值已在 Tool + StoreConfig 内消化） |
| 路由 HAS_RISK / NO_RISK / UNDETERMINED | 编排**只消费**结构化结果（见 §6），**不在 WF 内二次发明「中风险算不算」规则** |

---

### 4. Main Flow

```text
N0 Intent & Scope（horizon_days、类目/SKU 可选）
  → N1 Load Facts（get_inventory + query_sales_metrics）
  → 事实足够？
        否 → Recovery / UNDETERMINED
        是 → N2 Stockout Risk Analysis（analyze_stockout_risk）
  → 【CE】HAS_RISK | NO_RISK | UNDETERMINED
  → N3 Result Presentation
  →（可选）运营选择「生成补货建议」→ 移交 WF-OP05（同一 scope）
  → END
```

> 入参对外统一 **`horizon_days`**。若实现层兼容 Tool 别名 `forecast_days`，须映射为同一窗口语义；**不得**对外宣传为 forecasting 模型。

---

### 5. Nodes

| Node | 职责 | Tool / 机制 |
|------|------|-------------|
| N0 | 意图与 `horizon_days` 校验 | LLM 抽槽 |
| N1 | 库存+销售事实 | `get_inventory` + `query_sales_metrics` |
| N2 | 正式缺货风险 | `analyze_stockout_risk` |
| N3 | 解释与清单呈现 | LLM |

---

### 6. Conditional Edges

| 路由 | 映射（R5：只看结构化 State） | 下一步 |
|------|------------------------------|--------|
| `HAS_RISK` | T-A-07 成功且 `high_risk_products[]` **非空** | N3；可提示移交 OP-05 |
| `NO_RISK` | T-A-07 成功且 `high_risk_products[]` **为空** | N3 说明窗口内无明显缺货风险 |
| `UNDETERMINED` | 失败码 / 关键配置或销量不足 | Recovery 或说明 |

**说明：** 条目内 `risk_level`（如 high/medium）由 Tool/StoreConfig 决定「谁进入 `high_risk_products[]`」。Workflow **不再**用「或含中风险按 Store 策略」做第二套判定；避免与 Tool 输出语义重复。

---

### 7. State

```text
request_id, user_id, role, store_id
horizon_days
scope filters
inventory_summary?, sales_period?
risk_products[]（即 high_risk_products 摘要：sku, current_stock, avg_daily_sales_est,
  days_of_inventory, estimated_stockout_date?, risk_level）
route_status
handoff_to_op05?
error_code?, current_step?
```

---

### 8. Recovery

补全库存快照或拉长/缩短销量窗后重入 N2；仍不足 → UNDETERMINED。

---

### 9. Human Intervention

配置严重缺失、计算服务不可用、跨店权限问题。

---

### 10. Business Confirmation

**通常不需要**（只读分析）。

---

### 11. Approval

**无。**

---

### 12. Action

**无。** 移交 OP-05 不算本 WF Action。

---

### 13. LLM Boundary

| 允许 | 禁止 |
|------|------|
| 解释 risk_level 与依据 | 改写或发明 risk_level / 库存数 |
| 建议「下一步可跑补货建议」 | 直接给出正式补货量（应走 OP-05/T-R-01） |

---

### 14. Failure Handling

| 情况 | 行为 |
|------|------|
| DATA_UNAVAILABLE | UNDETERMINED + 说明缺失项 |
| 空店无 SKU | NO_RISK 或 EMPTY 说明（实现统一语义） |
| FORBIDDEN | 拒绝 |

---

### 15. Cross-Contract Review

| 层 | 结论 |
|----|------|
| Business | ✅ |
| Tool | ✅ T-A-07；与 T-R-01 共计算服务 |
| DB | ✅ |
| RAG | ✅ 不裁定风险 |
| Spec | ✅；边界移交 OP-05 |

**Data Requirements 要点：** 多 SKU 库存梯度 + 可支撑 DOI 的销量历史 + StoreConfig 安全库存/策略；含「即将缺货」与「健康库存」对照案例。

---

## D. WF-OP07 — 商品健康度分析

### D.0 Contract 对齐声明

| 层 | 对齐要点 |
|----|----------|
| **Business** | 多维事实 → Store 权重评分 → **数据完整度** → 诊断与建议；缺流量时降级标注 |
| **Tool** | `calculate_product_health`（T-A-05）；可辅以 `query_product_performance`；`search_business_knowledge`（operations） |
| **Database** | 多域事实 + StoreConfig 权重；**不建** product_health 持久宽表（V1 实时算） |
| **RAG** | 极少量健康维度说明/类目例外；**权重数值在 Config** |

---

### 1. Scope

**In Scope**

```text
定位商品 → 汇总维度事实（由 T-A-05 内部取数或前置 Query）
  → 确定性健康分 + completeness
  → 按 level / 完整度策略呈现
  → 可选加载运营文字规则增强解释
  → 建议动作方向（不执行）
```

**Out of Scope**

- 下架/调价/清仓执行  
- 用 LLM 直接打分  
- 跨完整度商品的误导性「裸分对比」而不提示 completeness  

---

### 2. Why Workflow（R1）

多维取数 → 确定性评分 → 完整度分支 → 条件性知识 → 建议；属特色分析链，非单 Tool 展示。

---

### 3. Formal Result Source

| 结论 | 来源 |
|------|------|
| score / level / dimensions / data_completeness / risk_factors | **T-A-05 `calculate_product_health`**（权重与维定义来自 **StoreConfig** + Domain 计算） |
| 类目文字例外、维度说明 | **T-K-01**（operations，**可选**） |
| 建议动作方向 | LLM 基于上述结构化结果组织（**非正式处置指令**） |

**Knowledge `required/optional` 钉死（V1）：**

```text
健康分计算不得依赖 LLM/RAG 检索。
T-K-01 只承担：维度说明、类目例外、文字政策。
若评分所必需的结构化 StoreConfig（权重等）缺失
  → UNDETERMINED 或 Tool 降级（basis 标明）
  → 禁止用 RAG「补」数值权重。
```

Tool 字段 `knowledge_dependency: required/optional` 在本 WF 解释为：**解释增强可选**；**不是**「没有 Knowledge 就不能算分」。

---

### 4. Main Flow

```text
N0 Intent & product 定位
  → N1（可选）Load Performance Snapshot（query_product_performance）
  → N2 Health Calculation（calculate_product_health）
  → 【CE】按 level 与 completeness（见 §6）
  → N3（可选）Load Ops Knowledge（类目例外/维度说明）
  → N4 Result Presentation（分、维、完整度、风险、建议方向）
  → END
```

---

### 5. Nodes

| Node | 职责 | Tool / 机制 |
|------|------|-------------|
| N0 | 意图与 product_id | LLM 抽槽 |
| N1 | 可选表现快照 | `query_product_performance` |
| N2 | 正式健康度 | `calculate_product_health` |
| N3 | 可选运营知识 | `search_business_knowledge` |
| N4 | 解释与建议方向 | LLM |

---

### 6. Conditional Edges

编排示例（具体阈值在 StoreConfig；**映射代码化**）：

| 条件 | 路径 |
|------|------|
| `data_completeness` 过低（如 used/configured < 阈值） | N4 **强调降级/不可裸比**；可 Intervention 若核心维全缺 |
| `level` ∈ {attention, risk, …}（以 Tool 枚举为准） | N3 可选 → N4 加强风险解释 |
| `level` 健康 | N4 简洁呈现 |
| Tool 失败 | UNDETERMINED 路径 |

不要求 LLM 判断「算不算健康」。

**ON-3 收口：** `level` 枚举以 **T-A-05 实际输出**为准（文档示例含 `attention`）。Workflow **不得**发明新等级名；StoreConfig 只提供权重/阈值，不在 WF 层另开一套 level 词汇。Eval 使用 Tool 返回值。不改 Frozen Tool 去穷尽枚举。

---

### 7. State

```text
request_id, user_id, role, store_id
product_id, evaluation_period_days?
performance_snapshot?
health_result（score, level, dimensions, data_completeness, risk_factors, basis）
knowledge_reference?
advice_direction?
error_code?, current_step?
```

---

### 8. Recovery

核心维缺失 → 仍可返回带 `missing[]` 的降级结果；仅当 Tool 无法计算时 UNDETERMINED。

---

### 9. Human Intervention

核心维全不可用、规则/配置冲突、权限问题。

---

### 10. Business Confirmation

**不需要**（分析场景）。

---

### 11. Approval

**无。**

---

### 12. Action

**无。**

---

### 13. LLM Boundary

| 允许 | 禁止 |
|------|------|
| 解释分数与风险、给优化方向 | 改分数/level |
| 提示完整度差异 | 在缺失流量时断言「转化差」等无证据结论 |

---

### 14. Failure Handling

| 情况 | 行为 |
|------|------|
| product NOT_FOUND | 停止 |
| 部分维缺失 | 降级 + missing 标注（成功路径） |
| Knowledge 不可用 | 仍呈现分数；解释减弱 |
| FORBIDDEN | 拒绝 |

---

### 15. Cross-Contract Review

| 层 | 结论 |
|----|------|
| Business | ✅ 完整度与降级 |
| Tool | ✅ T-A-05；Knowledge 仅文字增强（见 §3 钉死语义） |
| DB | ✅ 实时算、无 health 宽表；权重在 StoreConfig |
| RAG | ✅ operations 短文本；**禁止** RAG 补权重数值 |
| Spec | ✅ |

**Data Requirements 要点：** 单店多样本商品，覆盖「全维 / 缺可选维 / 缺核心维」三类 completeness；StoreConfig 权重；少量 operations 知识条目。

---

## E. WF-OP08 — 销售异常诊断

### E.0 Contract 对齐声明

| 层 | 对齐要点 |
|----|----------|
| **Business** | **先**可配置基线判定异常，再归因；无流量时归因限于已有事实 |
| **Tool** | `query_sales_metrics`、`compare_sales_period`、`get_inventory`、`get_price_history`、反馈类、`analyze_sales_anomaly`（T-A-06） |
| **Database** | 销售 §12A、Inventory、PriceHistory、Feedback、Campaign?、StoreConfig 阈值 |
| **RAG** | 可选；**不**替代 `is_anomaly` |

---

### 1. Scope

**In Scope**

```text
定位商品/范围与 period
  → 加载销售对比与相关证据事实
  → T-A-06 正式异常判定 + 证据/候选原因
  → NORMAL | ANOMALY | UNDETERMINED
  → 呈现诊断与建议方向（不执行改价/促销）
```

**Out of Scope**

- 直接改价、建促销、下架  
- LLM 主观认定「异常」  
- 无流量数据时编造流量归因  

---

### 2. Why Workflow（R1）

多 Tool 取证 → 确定性异常判定 → 三态分支 → 诊断建议；模式对齐 CS-06（Analysis→Branch），但是销售域。

---

### 3. Formal Result Source

| 结论 | 来源 |
|------|------|
| `is_anomaly`、`anomaly_basis`、`evidence[]`、`possible_causes[]` | **T-A-06 `analyze_sales_anomaly`** |
| 实际异常阈值/基线数值 | **StoreConfig**（由 Tool 内部解析）；**非**用户口头百分比 |
| 路由 NORMAL / ANOMALY / UNDETERMINED | 编排映射（同 CS-06 原则） |
| 话术与运营建议方向 | LLM 基于结构化结果 |

**`baseline_policy` 入参语义（必须遵守）：**

```text
baseline_policy = 可选的业务策略/模式标识（如 wow / store_default）
        ↓
Tool 根据 StoreConfig 解析真实阈值与基线
        ↓
is_anomaly

禁止：
用户说「跌 10% 就算异常」
  → LLM 把 10% 当作系统阈值直接覆盖 StoreConfig
```

---

### 4. Main Flow

```text
N0 Intent & Scope（product_id?、period、baseline_policy? 仅作策略标识）
  → N1 Load Evidence Facts
        ├── query_sales_metrics / compare_sales_period
        ├── get_inventory
        ├── get_price_history
        └── search_customer_feedback / analyze_customer_feedback（按需）
  → N2 Sales Anomaly Analysis（analyze_sales_anomaly；阈值来自 StoreConfig）
  → 【CE】NORMAL | ANOMALY | UNDETERMINED
```

**正确：** Facts → Analysis → Branch → Advice  
**禁止：** RAG/LLM 先判异常再找数；用户口授阈值覆盖系统配置。

---

### 5. Nodes

| Node | 职责 | Tool / 机制 |
|------|------|-------------|
| N0 | 意图与 period | LLM 抽槽 |
| N1 | 多域证据事实 | 销售对比 + 库存 + 价格史 + 反馈（按需） |
| N2 | 正式异常分析 | `analyze_sales_anomaly` |
| N3 | 结果呈现 | LLM |

N1 **允许多 Tool**（Spec R3）。

---

### 6. Conditional Edges

| 路由 | 映射 | 下一步 |
|------|------|--------|
| `NORMAL` | `is_anomaly=false` 且分析成功 | N3：说明未达异常阈值 + 依据 |
| `ANOMALY` | `is_anomaly=true` | N3：异常事实 + Top causes + 建议方向 |
| `UNDETERMINED` | 失败 / 事实不足无法判定 | Recovery 或说明；禁止硬判异常 |

---

### 7. State

```text
request_id, user_id, role, store_id
product_id?, period
baseline_policy?（策略标识；非数值阈值）
sales_compare_summary?
inventory_summary?, price_change_summary?, feedback_summary?
anomaly_result（is_anomaly, anomaly_basis, evidence[], possible_causes[], sales_change?）
route_status（NORMAL|ANOMALY|UNDETERMINED）
advice_direction?
error_code?, current_step?
```

---

### 8. Recovery

补 period / 补价格史或反馈后重入 N2；仍不足 → UNDETERMINED。

---

### 9. Human Intervention

基线配置冲突、关键依赖不可用、范围无法定位。

---

### 10. Business Confirmation

**通常不需要。**

---

### 11. Approval

**无**（无写操作）。若建议后续调价/促销，**移交** OP-09/10 设计（Phase2），本 WF 不批。

---

### 12. Action

**无。**

---

### 13. LLM Boundary

| 允许 | 禁止 |
|------|------|
| 解释 evidence / 排序后的 causes | 否定或篡改 `is_anomaly` |
| 给观察类建议 | 无流量时编造「投流下降」等 |
| | 把用户口头阈值写入系统基线 |

---

### 14. Failure Handling

| 情况 | 行为 |
|------|------|
| 销售数据不足 | UNDETERMINED |
| 部分证据源缺失 | Tool 降级归因；basis 标明 |
| FORBIDDEN | 拒绝 |

---

### 15. Cross-Contract Review

| 层 | 结论 |
|----|------|
| Business | ✅ 先判定后归因；阈值属可配置系统规则 |
| Tool | ✅ T-A-06；`baseline_policy` 仅策略标识（见 §3） |
| DB | ✅ §12A + price_history + feedback；阈值在 StoreConfig |
| RAG | ✅ 不替代判定 |
| Spec | ✅ 对齐 CS-06 模式差异化节点 |

**Data Requirements 要点：** 含「达阈值异常」与「未达阈值」对照时间线；价格变动、库存断裂、退货/反馈等可解释证据；StoreConfig 异常阈值。

---

## F. WF-OP03 — 滞销商品识别

### F.0 Contract 对齐声明

| 层 | 对齐要点 |
|----|----------|
| **Business** | 低动销识别 + 风险与建议方向；事实期望含销售/库存/利润/退货；本场景以识别为主 |
| **Tool** | **主：** T-A-04 `mode=slow_moving` = **候选筛选视角**（非清仓决策、非正式滞销风险判定）；**增强：** T-A-05 提供 health `level`/`risk_factors`（可含利润维，见 Gap） |
| **Database** | OrderItem、Inventory、退货等；成本/利润相关字段可支撑 health 计算；§12A |
| **RAG** | 可选清库存文字标准（解释）；**不**单独裁定「应下架」 |
| **Gap** | 见 §A.5 **Gap-OP03-Profit-Surface** |

---

### 1. Scope

**In Scope**

```text
时间窗与类目范围
  → T-A-04 mode=slow_moving → 低动销候选清单（非「正式滞销风险判定」）
  →（可选）Top N × T-A-05 → 健康/风险增强信号（含利润维若数据可得）
  → 呈现：候选表现事实 +（若有）health 信号 + 建议动作方向（不执行）
```

**Out of Scope**

- 积压价值清仓主路径（**OP-06**）  
- 淘汰/下架执行（**OP-12**）  
- 把 `mode=slow_moving` 解释成「已批准清仓」或「正式滞销风险等级」  
- 在 T-A-04 输出中假装存在 `profit` 字段  

---

### 2. Why Workflow（R1）

表现查询 →（可选）健康度增强 → 分支（有无候选）→ 建议方向；含与 OP-06/12 边界控制。  
若运营仅要「按销量倒序列表」且不要风险解释，可降级为 Multi-Tool；**本 WF 面向「识别 + 风险方向」完整任务。**

---

### 3. Formal Result Source

| 结论 | 来源 |
|------|------|
| 低动销**候选**列表及销量/库存/`return_rate?` 等 T-A-04 字段 | **T-A-04**（`mode=slow_moving`；过滤阈值在 Tool/StoreConfig，非 LLM） |
| 健康分、`level`、`risk_factors`、完整度（可间接反映利润等维） | **T-A-05**（可选增强；**≠** 自动「滞销风险等级」） |
| 「建议动作方向」文案 | LLM 基于上述结构（非正式执行指令） |

**语义钉死（总审必守）：**

```text
1. slow_moving = 低动销候选筛选视角，不是完整滞销决策，也不是正式「滞销风险等级」。

2. health.level / risk_factors = 健康度增强信号，不自动等价于「滞销风险等级」。
   （例：低销+高利润+低库存 → health 可能不差；低销+低利润+高库存 → 更像经营滞销风险。）

3. Business 要求的利润维度：
   - T-A-04 正式出参无 profit → 禁止 WF 假装已有该字段；
   - V1 若呈现利润相关含义，仅能经 T-A-05 健康维间接承载；
   - 未跑 N2 时：只输出表现事实 + 方向建议，不得输出「正式滞销风险等级」或臆造利润。
   - 详见 Gap-OP03-Profit-Surface（不上新 Tool、不改 Frozen）。
```

**禁止：** LLM 在无 T-A-04/05 依据时自造「滞销风险等级」或利润数字。

---

### 4. Main Flow

```text
N0 Intent & Period / category
  → N1 Slow-moving Candidate Query
        └── query_product_performance(mode=slow_moving, ...)
  → 【CE】HAS_CANDIDATES | EMPTY | UNDETERMINED
  →（HAS_CANDIDATES）N2 Optional Health Enrichment（Top N × calculate_product_health）
        └── 需要「风险方向/利润相关解释」时建议开启 N2
  → N3（可选）Load Clearance Guidance Text（knowledge）
  → N4 Result Presentation
        └── 候选事实 +（若有）health 信号（标注非滞销风险等级）+ 方向建议
  → END
```

---

### 5. Nodes

| Node | 职责 | Tool / 机制 |
|------|------|-------------|
| N0 | 意图与时间窗 | LLM 抽槽 |
| N1 | 低动销候选表现事实 | `query_product_performance` |
| N2 | 可选健康度增强（间接利润等） | `calculate_product_health` |
| N3 | 可选文字标准 | `search_business_knowledge` |
| N4 | 呈现（禁止伪造成滞销风险判定） | LLM |

---

### 6. Conditional Edges

| 路由 | 映射 | 下一步 |
|------|------|--------|
| `HAS_CANDIDATES` | `products[]` 非空 | N2? → N3? → N4 |
| `EMPTY` | 成功但无慢销候选 | N4 说明窗口内无匹配 |
| `UNDETERMINED` | 查询失败/数据不足 | Recovery / 说明 |

---

### 7. State

```text
request_id, user_id, role, store_id
start_date, end_date, category_id?, limit?
candidates[]（仅 T-A-04 字段；无虚构 profit）
health_enrichment[]?（product_id → level, risk_factors, completeness；标注为 health 信号）
knowledge_reference?
advice_direction_summary?
route_status
error_code?, current_step?
```

---

### 8. Recovery

调整时间窗/类目后重入 N1；健康度单商品失败则跳过该增强项（候选列表仍可用）。

---

### 9. Human Intervention

数据大规模不可用、权限问题。

---

### 10. Business Confirmation

**不需要**（识别场景）。若运营要从建议跳到调价/下架，**移交**对应 Phase2 WF，并在那里 Confirmation/Approval。

---

### 11. Approval

**无。**

---

### 12. Action

**无。**

---

### 13. LLM Boundary

| 允许 | 禁止 |
|------|------|
| 解释候选与（若有）health 信号、给方向 | 宣称已批准下架/清仓 |
| 说明「未跑 health 时无正式风险等级」 | 把 `mode=slow_moving` 说成决策/风险判定 Tool |
| | 把 `health.level` 直接改称「滞销风险等级」 |
| | 编造 T-A-04 未提供的 profit |

---

### 14. Failure Handling

| 情况 | 行为 |
|------|------|
| 销售聚合失败 | UNDETERMINED |
| 健康度部分失败 | 列表仍可用，增强列标注失败 |
| Knowledge 不可用 | 不影响候选清单 |

---

### 15. Cross-Contract Review

| 层 | 结论 |
|----|------|
| Business | ⚠️ 利润/风险等级期望与 Core 输出面不完全同构 → **Gap-OP03-Profit-Surface**；V1 经 health 间接或降级标注 |
| Tool | ✅ `slow_moving` 仅筛选；决策不靠 mode；健康可复用；**不上新 profit 字段** |
| DB | ✅ 成本等可支撑 health；不要求本 WF 新增表 |
| RAG | ✅ 可选文字 |
| Spec | ✅ 边界不吞 OP-06/12；缺口上报不静默补能力 |

**Data Requirements 要点：** 慢销 vs 热销对照；高库存低动销样本；可选含利润/成本以支撑 health；与 OP-06 案例勿矛盾；Scenario 勿假设 T-A-04 直接返回 profit。

---

## G. 场景索引：是否需要独立 Workflow（无正文）

> 规则：先过 Spec **R1**。不满足 → `Tool Calling / Multi-Tool Flow`。  
> P1/P2：**只保留判断**，不写 Workflow 正文；**不阻塞** Data → Implementation。  
> **脚注：** 索引「Yes」≠ Core Tool 已就绪。若依赖出 Core 能力（如 `cancel_order`、`analyze_overstock_risk`、`escalate_to_human`），标 **Design Yes / Tool Gap → Phase2**，禁止按索引静默发明 Tool。

### G.1 客服

| Scenario | R1? | Workflow Needed? | Priority | Implementation Phase | Reason（一句话） |
|----------|-----|------------------|----------|----------------------|------------------|
| CS-01 商品基础咨询 | 否 | **No** — Multi-Tool | P0 | Tool Calling | 查询→回复 |
| CS-02 库存与可售 | 否 | **No** | P0 | Tool Calling | 单域查询为主 |
| CS-03 价格与促销咨询 | 否 | **No** | P0 | Tool Calling | 查询→解释 |
| CS-04 推荐/替代 | 边界 | **No**（V1） | P0 | Multi-Tool | 推荐可 Tool 链；无强状态机 |
| CS-05 订单状态查询 | 否 | **No** | P0 | Tool Calling | 查询→回复 |
| CS-06 物流异常 | 是 | **Yes** — [workflow-cs06-v1.md](./workflow-cs06-v1.md) | P0 | 已设计 | 分析→分支→规则→建议 |
| CS-07 取消/修改 | 是 | **Yes（索引）** / Tool Gap | P2 | Phase 2 Design | 判断→确认→高风险 Action；`cancel_order` 等出 Core |
| CS-08→09 退货 | 是 | **Yes** — [workflow-cs08-09-v1.md](./workflow-cs08-09-v1.md) | P0 | 已设计 | 资格三态→确认→审批→Action |
| CS-10 质量/错漏发 | 是 | **Yes（索引）** | P1 | Phase 2 Design | 分类→证据→**移交** CS-08/09；禁止超级售后流 |
| CS-11 客诉/转人工 | 是 | **Yes（索引）** / Tool Gap | P2 | Phase 2 Design | 偏 Intervention；`escalate_to_human` Gap-06 |
| CS-12 反馈汇总 | 否 | **No** | P1 | Tool Calling | 聚合分析展示 |

### G.2 运营

| Scenario | R1? | Workflow Needed? | Priority | Implementation Phase | Reason（一句话） |
|----------|-----|------------------|----------|----------------------|------------------|
| OP-01 经营概览 | 否 | **No** | P0 | Tool Calling | 指标查询展示 |
| OP-02 热销分析 | 否 | **No** | P1 | Tool Calling | 排名/聚合 |
| OP-03 滞销识别 | 是 | **Yes** — 本文 §F | P0 | Design 本批 | 表现→增强→建议方向 |
| OP-04 缺货风险 | 是 | **Yes** — 本文 §C | P0 | Design 本批 | 计算→风险清单 |
| OP-05 补货建议 | 是 | **Yes** — 本文 §B | P0 | Design 本批 / **首个实现锚点** | 计算→Reco→Confirmation |
| OP-06 积压/清库存 | 是 | **Yes（索引）** / Tool Gap | P1 | Phase 2 | `analyze_overstock_risk` 出 Core；先补 Tool 或降级 |
| OP-07 健康度 | 是 | **Yes** — 本文 §D | P0 | Design 本批 | 多维评分+完整度 |
| OP-08 销售异常 | 是 | **Yes** — 本文 §E | P0 | Design 本批 | 判定→分支→归因 |
| OP-09 调价建议 | 是 | **Yes（索引）** | P1 | Phase 2 | 分析→建议；改价须人 |
| OP-10 促销策略 | 是 | **Yes（索引）** | P1 | Phase 2 | 候选→建议；建活动须人 |
| OP-11 生命周期 | 是 | **Yes（索引）** | P1 | Phase 2 | 阶段判定须结构化规则 |
| OP-12 淘汰/下架建议 | 是 | **Yes（索引）** | P2 | Phase 2 | 建议；禁止自动下架 |
| OP-13 反馈驱动诊断 | 是 | **Yes（索引）** | P1 | Phase 2 | 反馈聚合→诊断 |
| OP-14 经营报告 | 是 | **Yes（索引）** | P2 | Phase 2+ | 组合型 Report WF，后置 |

### G.3 Workflow Design Phase 收口清单（执行纪律）

```text
已完成模板：WF-CS06、WF-CS08-09
本批正文：WF-OP05、OP-04、OP-07、OP-08、OP-03
合计：≈7 个 Workflow 设计（Design Coverage ≠ V1 全实现）

当前状态：
  Cross-Workflow Review ✅
  Freeze Gate ✅
  Workflow Phase Freeze ✅（本文 Frozen）
        ↓
  Data Requirements（由上述 WF + Multi-Tool 场景反推）
        ↓
  Dataset / Generator
        ↓
  Implementation（OP-05 优先）
```

冻结纪律：不以 P1/P2 正文阻塞 Data → 实现；不回头改 Business / Tool / DB / RAG Frozen。不新增独立 Workflow 正文。

---

## H. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-15 | 初稿：五 P0 Ops WF 统一 15 段；R1 门闸；Gap-OP05-Action 上报；全场景索引；单文档合集 |
| V1.0.1 | 2026-09-15 | 总审卫生：Gap-OP03-Profit-Surface；OP-03 语义钉死；OP-04 HAS_RISK=`[]`非空 + `horizon_days`；OP-05 N2 默认预筛与 Confirmation 映射；OP-07 Knowledge 不算分；OP-08 `baseline_policy`；§G Tool Gap 脚注 |
| V1.0.2 | 2026-09-16 | Freeze Gate：`route_status` 统一；ON-2 Confirmation→Technical；ON-3 level 消费 Tool 枚举 |
| V1.0.2 Frozen | 2026-09-16 | 用户确认冻结；§G.3 与 Freeze 后 Data 链对齐 |

# E-commerce Business Copilot — Data Requirements → Dataset Matrix V1.0.1

> 文档性质：**S1 Data Requirements（需求矩阵）**；非 Generator、非 DDL 变更、非造数  
> 版本：**V1.0.2**  
> 状态：**Draft / Review Complete（可进 S2）**（S1 审查小补已收口；S2 须用户批准）  
> 上游（只读 Frozen）：Business V1.1 · Tool V1.1 · Database V1.2.3 · RAG V1.0 · Workflow Spec V1.0 · WF-CS06/CS08-09/Ops P0 · [workflow-cross-review-v1.md](./workflow-cross-review-v1.md) §7 · [AGENTS.md](../AGENTS.md) §15  
> 约束：形状与语义服从 Database Contract；**不得**为造数方便改写任何 Frozen 契约；缺口登记 Gap。

---

## 0. 本文回答什么

| 问题 | 本文 | 非本文（→ 后续阶段） |
|------|------|----------------------|
| 需要哪些实体/关键字段？ | ✅ | — |
| 谁（Tool/WF）用？对应哪些 Scenario？ | ✅ | — |
| 时间/分布/一致性要求？ | ✅ | 算法参数细节 → S2 |
| 规模精确数字（dev/full）？ | 仅方向 | **S2** 钉死 |
| Generator 代码 / 灌库？ | ❌ | S3–S5 |
| 新增 DB 表或改 Frozen？ | ❌ | 仅登记 Gap |

**输入：** Cross-Review §7 + Database §4/§6/§12A + 七 Frozen WF。  
**输出：** 可执行的「数据合同」，供 S2 设计规则、S3 实现生成器。

---

## 1. 数据阶段原则（写入合同）

1. **Workflow 驱动**：只为 Frozen WF + 必要 Multi-Tool 场景准备数据；不为未设计的 P1/P2 WF 大规模造数。  
2. **Canonical 唯一事实源**：Generator → **一份** Canonical Dataset → 再导出 PostgreSQL 与 CSV/Parquet；禁止 PG 与数仓各造一套随机世界。  
3. **Business ≠ Scenario**：业务表存世界真相；`SC-*` 只引用 ID + 期望路由，不复制订单/库存。  
4. **规则造数**：时间因果 + SKU 角色 + Scenario 注入；禁止纯 Faker 无业务约束。  
5. **派生指标不落事实表**：健康分、缺货风险、补货量、`is_anomaly`、GMV 等由 Calculation/Tool 计算（Database §4.4）。  
6. **Config vs RAG**：数值旋钮 → `StoreConfig`；文字规则 → Knowledge（人工短文）。  
7. **可复现 + 校验后可用**：固定 seed；Validate 通过（含 Scenario 真跑计算）后方可 Import / 开发。  
8. **双项目隔离**：Agent 与数仓课设可共享导出物与脚本；代码/库/调度隔离；Agent **不依赖** Hive。

---

## 2. 四类资产（S1 范围）

| 资产 | 内容 | 落地形态（S3+） |
|------|------|-----------------|
| **A. Unified Business Dataset** | OLTP 风格业务实体 | Canonical → PG / CSV·Parquet |
| **B. Scenario / Eval Dataset** | `SC-*` 清单与期望 | JSON/YAML（可独立于业务表） |
| **C. Knowledge Seed** | 少量当前有效规则文 | KnowledgeDocument/Chunk；**人工** |
| **D. Generator Profiles** | 同规则多规模 | `dev` / `eval` 优先；`full` 后扩（S2 定数字） |

---

## 3. 明确不生成（防呆）

| 不生成 / 不建 | 原因 |
|---------------|------|
| `product_health_scores` / 日 GMV 宽表 / 缺货风险结果表 | 派生指标；DB 明确不建 |
| `recommended_quantity` 作为业务事实列 | 属 T-R-01 输出 |
| `is_anomaly` / `HAS_RISK` 作为业务表字段 | 属 Analysis / 路由 |
| 流量 / CTR / 转化事实表 | DB-G01；health 完整度降级 |
| 采购单 / `create_restock_request` 落库冒充 V1 执行 | Gap-OP05-Action |
| T-A-04 输出中的虚构 `profit` | Gap-OP03-Profit-Surface |
| 海量随机 Knowledge | RAG：少量高质量人工稿 |
| 为每个 WF 单独的业务库 | Unified Dataset |

---

## 4. Dataset Matrix — 统一业务底座

> **关键字段**：S1 级需求（非完整物理字典；类型以 Database §13 为准）。  
> **一致性**：标 ⚠️ 的实体在 S2/S3 必须有专门校验规则。

### 4.1 Tenant / Identity / Config

| Entity | 为何存在 | 关键字段（需求级） | 服务 Tool / WF | 时间要求 | 数据分布要求 | Scenario 关联 |
|--------|----------|-------------------|----------------|----------|--------------|---------------|
| **Store** | `store_id` 隔离锚点 | `id`, 名称/状态 | 全 Tool；隔离用例 | 主数据 | **≥2** 店 | 跨店 FORBIDDEN |
| **StaffUser** | `user_context` | `id`, `store_id`, `role` | 全 Tool；CS-08 HITL | 主数据 | 每店客服+运营+可选审批人 | CS-08 确认/审批 |
| **StoreConfig** | 数值旋钮 | `store_id`, `config_key`, `config_value`；**key 清单见 §4.1.1** | T-A-05/06/07, T-R-01；OP-03/04/05/07/08 | 配置生效即可 | 每店完整一套；可构造「缺 key」 | OP-05/08 UNDETERMINED；OP-07 权重 |

#### 4.1.1 StoreConfig key 需求清单（S1 最小集；S2 可补默认值）

> 数值只进 Config，不进 RAG。下列为 **P0 生成必须覆盖的 key 族**（具体默认值/JSON 形态 → S2；须与 Database `store_configs` 示例语义一致）。

| config_key 族（逻辑名） | 用途 | 消费方 |
|-------------------------|------|--------|
| `inventory.lead_time_days` | 采购/补货提前期 | OP-04/05；T-A-07；T-R-01 |
| `inventory.safety_stock_days` 或 SKU 级 `safety_stock` | 安全库存策略 | OP-04/05（表字段与 config 分工在 S2 写清） |
| `inventory.slow_moving.*` | 慢销过滤/排序阈值 | OP-03；T-A-04 mode |
| `health.weights` | 健康分维度权重 | OP-07；T-A-05 |
| `health.core_dimensions` / 完整度策略 | 核心维 vs 可选维 | OP-07 |
| `anomaly.sales_drop_threshold`（及/或 baseline 模式） | 异常判定阈值 | OP-08；T-A-06 |
| （可选）补货 horizon 默认天数 | 与 `horizon_days` 默认 | OP-05 |

每店「完整一套」= 上表 P0 key 齐备；UNDETERMINED 案例 = **故意缺失**其中必要 key。

### 4.2 Product 域

| Entity | 为何存在 | 关键字段 | 服务 Tool / WF | 时间要求 | 数据分布要求 | Scenario 关联 |
|--------|----------|----------|----------------|----------|--------------|---------------|
| **ProductCategory** | 类目/检索/资格 | `id`, 名称, 层级 | T-Q-01/02；T-A-09 | 主数据 | 多类目（含售后政策差异类目更好） | CS-08 类目规则 |
| **Product** | SPU | `id`, `store_id`, `category_id`, `name`, `status`, `cost_price?`, `launch_date`/`listed_at` | T-Q-01/02；OP-07；CS-08 | 主数据+上架时间 | 多状态；部分有 cost | OP-07 完整度；生命周期可选 |
| **ProductSku** | 库存/价格/销售粒度 | `id`, `product_id`, `sku_code`, `selling_price`, `cost_price?`, `status` | T-Q-02/03；OP-03/04/05/07/08 | 主数据 | **角色分化**（见 §5） | 全体 OP + 部分 CS |

### 4.3 Customer / Order（销售事实 · §12A）

| Entity | 为何存在 | 关键字段 | 服务 Tool / WF | 时间要求 | 数据分布要求 | Scenario 关联 |
|--------|----------|----------|----------------|----------|--------------|---------------|
| **Customer** | 订单关联 | `id`, `store_id`… | T-Q-04 | 主数据 | 足够支撑订单量 | — |
| **CustomerAddress** | 可选主数据 | 地址字段 | 订单快照来源 | 主数据 | 少量即可 | — |
| **Order** | 销售/履约头 | `id`, `store_id`, `customer_id`, `status`, 金额, 地址快照, `ordered_at`, `paid_at`, `promised_ship_at`, **`promised_delivery_at`**, `shipped_at`, `delivered_at`, `signed_at`, … | T-Q-04；T-A-01/02/03/06；CS-05/06/08 | **事件时间**；底座 **≥90 天**；日级可聚合 | 多状态；正常/延迟对照 | CS-06/08；OP 销售窗 |
| **OrderItem** | §12A units/GMV | `id`, `order_id`, `product_id`, `sku_id`, `quantity`, `unit_price`, `line_amount`… | 全体销售/表现/健康/缺货/补货 | 同订单时间线 | 与 SKU 角色销量曲线一致 | OP-03/04/05/07/08 |

**口径（§12A，生成时必须遵守）：**

- 计入销量窗 / GMV / units 的订单：`status IN ('PAID','PROCESSING','SHIPPED','COMPLETED')`；**排除** `PENDING_PAYMENT`、`CANCELLED`、`CLOSED`。  
- 时间窗默认按 `orders.ordered_at`（若评测指定 `paid_at` 须标注 `time_basis`）。  
- 有效退货：`type=RETURN` 且 `status IN ('APPROVED','PROCESSING','COMPLETED')`；`quantity ≤` 对应行购买量。  
- 生成器不得另立销售/退货口径；不得用大量取消单冒充有效销量。

### 4.4 Fulfillment

| Entity | 为何存在 | 关键字段 | 服务 Tool / WF | 时间要求 | 数据分布要求 | Scenario 关联 |
|--------|----------|----------|----------------|----------|--------------|---------------|
| **Shipment** | 运单 | `order_id`, carrier, tracking, status, 关键时间 | T-Q-05；T-A-01；CS-06/08 | 事件/状态时间 | 正常+异常运单 | CS-06 |
| **ShipmentEvent** | 轨迹 | `event_type`, `occurred_at`, … | T-Q-05；CS-06 | **事件时间序列** | 有序事件；可缺关键事件 | CS-06 UNDETERMINED / ANOMALY |

### 4.5 Inventory（⚠️ 状态一致性实体）

| Entity | 为何存在 | 关键字段 | 服务 Tool / WF | 时间要求 | 数据分布要求 | Scenario 关联 |
|--------|----------|----------|----------------|----------|--------------|---------------|
| **Warehouse** | 仓维度 | `id`, `store_id`… | T-Q-03 | 主数据 | 每店 ≥1 | — |
| **Inventory** | 当前库存快照 | `store_id`, `warehouse_id`, `sku_id`, `available_qty`, `reserved_qty`, `safety_stock`, `reorder_point?`, `updated_at` | T-Q-03；T-A-07；T-R-01；OP-03/04/05 | **当前快照时间** | 缺货/健康/积压梯度 | OP-04/05 |
| **InventoryMovement** | 变动流水 | `sku_id`, warehouse, **signed `quantity`**, `reason`/`type`, `occurred_at` | 解释/校验；非所有 P0 必读 | **变动时间** | 与销量/退货/补货逻辑一致 | 一致性闸门 |

**一致性规则（S2/S4 必检）：**

```text
期初 + Σ(signed movements) = 当前 available（在约定口径下）
available_qty ≥ 0；reserved_qty ≥ 0
不得出现「流水推不出快照」或「快照与流水长期矛盾」
```

**V1 策略须在 S2 二选一拍板（禁止含糊并行）：**

| 选项 | 含义 | 校验 |
|------|------|------|
| **A. 快照 + Movement** | 生成流水且与 `inventory` 平衡 | S4 强制平衡公式 |
| **B. 仅快照** | 不生成 Movement；库存由「销量叙事 + 角色目标」落快照 | S2 写明推导规则；S4 检库存与订单销量不自相矛盾；**不**宣称完整进销存账 |

推荐：`dev`/`eval` 可先选 **B**；`full`/课设需要进销存故事再升 **A**。

### 4.6 After-sales / Ticket / Feedback / Price / Promo

| Entity | 为何存在 | 关键字段 | 服务 Tool / WF | 时间要求 | 数据分布要求 | Scenario 关联 |
|--------|----------|----------|----------------|----------|--------------|---------------|
| **AfterSalesRequest** | 退货事实+演示建单 | `order_item_id`, **`quantity`**, `type`, status, 审批/幂等字段… | T-X-01；T-A-04/05/09；CS-08-09 | 创建/处理时间 ≥ 送达 | 有效退货集支撑退货率；quantity≤购买 | CS-08；OP-03/07 |
| **ServiceTicket** | 工单（与售后分表） | `ticket_type`, status… | T-X-02 | 创建时间 | 少量即可 | 可选 |
| **AuditLog** | Action 审计 | Action 元数据、approver… | T-X-* | 操作时间 | 可随 Action 演示生成 | CS-08 成功建单 |
| **CustomerFeedback** | 反馈/评价 | `product_id`/`sku?`, 时间, 类目/情感… | T-Q-06；T-A-08；OP-07/08 | **≥ delivered_at** | 有/无反馈对照 | OP-07 完整度；OP-08 证据 |
| **PriceHistory** | 调价证据 | **仅 `sku_id`**, old/new, `effective_at` | T-Q-07；T-A-06；OP-08 | **生效时间** | 部分 SKU 有变价；latest 与 `selling_price` 一致 | OP-08 ANOMALY |
| **Campaign** / **CampaignProduct** | 异常可选证据 | 活动期、商品关联 | T-A-06 可选 | 活动窗口 | 可选少量 | OP-08 可选 |

### 4.7 Knowledge（与业务 Generator 分离）

| Entity | 为何存在 | 关键字段 | 服务 Tool / WF | 时间要求 | 数据分布要求 | Scenario 关联 |
|--------|----------|----------|----------------|----------|--------------|---------------|
| **KnowledgeDocument** | 规则元数据 | `knowledge_type`, `layer`, `store_id?`, `status`, `version`, `effective_from`/`to` | T-K-01 | 生效窗过滤 | **人工** 7–15 篇（P0 最低 7；20–40 为长期扩展目标，非 V1 验收指标） | CS-08/06；OP-07；可选 inventory |
| **KnowledgeChunk** | 检索切片 | embedding、document 关联 | T-K-01 | 同文档 | 短切片；非海量 | 同上 |

**knowledge_type 覆盖（P0）：** `after_sales`（CS-08 强制）、`logistics`（CS-06）、`operations`（OP-07）、可选 `inventory`（OP-04/05/03 解释）。

---

## 5. SKU / 商品角色分化（业务世界，非 Scenario 表）

生成时须刻意制造可区分角色（同一 SKU 可组合多特征）：

| 角色标签（逻辑） | 典型事实组合 | 主要服务 |
|------------------|--------------|----------|
| 爆款 / 正常 / 慢销 | 销量时间线差异 | OP-03；销售指标 |
| 库存充足 / 低库存 / 积压 | Inventory + 销量 | OP-04/05/03 |
| 健康 / 关注 / 高风险信号 | 多维事实+完整度（结果仍由 T-A-05 算） | OP-07；OP-03 增强 |
| 高/低退货 | AfterSales quantity | OP-03/07/08 |
| 有/无价格变动 | PriceHistory | OP-08 |
| 物流正常 / 延迟 | promised vs actual | CS-06 |
| 基线对照 SKU | 「什么都正常」 | 全体 NO_RISK / NORMAL / EMPTY |

**禁止：** 用预写死的 `risk_level` 列代替上述事实组合。

---

## 6. Scenario / Eval 需求矩阵

> Scenario **引用**底座 ID；记录期望路由与（建议）失败原因码。  
> **S1 定需求；S2 定 YAML 字段；S4 必须用 Tool/Calculation 复核。**

### 6.1 建议最小字段（S2 实现）

```text
scenario_id          # 稳定 ID，如 SC-OP04-001
workflow             # OP-04 / CS-06 / …
description
store_id
主键引用             # sku_ids[] / order_id / product_id …
input_scope          # horizon_days、period 等
trigger_type         # 如 LOW_STOCK_HIGH_SALES / MISSING_PROMISED_AT
expected_route       # HAS_RISK | NORMAL | eligible | …
expected_formal_result?  # 可选：摘要级期望（非完整 Tool dump）
expected_reason?     # 如 MISSING_SALES_WINDOW（尤其 UNDETERMINED）
```

### 6.2 按 Frozen WF 的案例类型（来自 Cross-Review §7.2）

| Workflow | 至少覆盖的案例类型 | 依赖的业务事实重点 |
|----------|-------------------|-------------------|
| **CS-08-09** | eligible；ineligible；undetermined（缺签收）；确认取消；审批拒绝；建单成功 | Order 时间/状态；类目；Knowledge after_sales；Staff |
| **CS-06** | NORMAL；ANOMALY；UNDETERMINED（缺时效）；Knowledge 不可用仍可呈现分析 | Order promised_*；ShipmentEvent |
| **OP-04** | HAS_RISK（清单非空）；NO_RISK（空清单）；UNDETERMINED（销量/配置不足）；可移交 OP-05 | Inventory + 销量窗 + StoreConfig |
| **OP-05** | HAS_RECO；NO_RECO；UNDETERMINED；指定 SKU 跳过预筛；Confirmation 采纳/拒绝（评测可模拟） | 同上 + lead_time/safety |
| **OP-07** | 全维；缺可选维；缺核心维（completeness） | 销售/库存/退货/反馈/cost 有无 |
| **OP-08** | ANOMALY（达阈值）；NORMAL（未达）；UNDETERMINED；含价格/库存/反馈证据 | §12A 时间线 + PriceHistory + Feedback + StoreConfig 阈值 |
| **OP-03** | 慢销候选有/无；有/无 health 增强；**无** T-A-04.profit 假设 | performance 事实；可选 health 维 |

### 6.3 Multi-Tool / 隔离（非独立 WF，可选）

| 类型 | 要求 | 说明 |
|------|------|------|
| CS-01/02/05 等 | **不强制**独立 `SC-*` | 由统一底座自然支撑 smoke；需要时可加 `SC-MT-*` |
| 跨店隔离 | 建议至少 `SC-ISO-001` | store A 用户不可读 store B 订单/库存 |

### 6.4 建议 ID 前缀

`SC-CS06-*` · `SC-CS08-*` · `SC-OP03-*` · `SC-OP04-*` · `SC-OP05-*` · `SC-OP07-*` · `SC-OP08-*`  
可选：`SC-ISO-*` · `SC-MT-*`

---

## 7. 时间需求（按域 + 统一时钟）

### 7.1 统一分析时钟（N2 收口）

| 项 | 要求 |
|----|------|
| **`as_of_date`** | Canonical 必须有单一「分析当日」（建议 = 生成时间线末日或配置常量） |
| 销量窗 / DOI / 缺货日 / OP-08 period | 一律相对 `as_of_date` 计算 |
| Scenario | 可写 `as_of_date` 或继承数据集默认；S4 复核不得各用各的「今天」 |

### 7.2 分域时间

| 域 | 粒度 / 语义 | 最短跨度要求（S1） |
|----|-------------|-------------------|
| 订单 / 明细 | 事件时间；日级可聚合 | 相对 `as_of_date` **向前 ≥90 天** |
| 物流 | 事件序列；promised vs actual | 覆盖正常+异常+缺字段 |
| 库存快照 | `updated_at` 对齐 `as_of_date` | 与分析「今天」一致 |
| 库存流水 | `occurred_at` | 若选策略 A，与订单/退货叙事一致 |
| 价格史 | `effective_at` | 异常前后可见变价 |
| 反馈 / 售后 | 创建时间 ≥ 送达 | 支撑退货率与完整度 |
| StoreConfig | 生效即可 | 可构造缺失配置案例 |
| Knowledge | effective_from/to + status | 「当前有效」相对 `as_of_date` 可测 |

---

## 8. Profile 方向（数字留给 S2）

| Profile | 用途 | S1 约束 |
|---------|------|---------|
| **dev** | 日常重生成、联调 | 小；须含各 WF 至少 1 组正反案例 |
| **eval** | 黄金 Scenario | 案例全覆盖 §6.2；体量可小于 full |
| **full** | Agent 演示 + 课设 | 后扩；**非** S3 第一周硬门槛 |

三者：**同一生成规则与 seed 策略**，不同规模参数。

---

## 9. Validation 闸门（S4 验收标准预告）

| 层 | 检查什么 |
|----|----------|
| Schema | PK/FK、NOT NULL、枚举、类型（对 Database） |
| Business consistency | 订单时间序；退货量；反馈时间；价格史 vs 当前价；**Inventory↔Movement** |
| Isolation | 跨 store 不可串读 |
| Scenario correctness | 对 `SC-*` **执行**对应 Analysis/Recommendation（或等价 Calculation）后 `route_status` 与期望一致 |
| Knowledge | 生命周期过滤；CS-08 可取到 after_sales |

---

## 10. 已登记 Gaps（数据阶段不得假装关闭）

| Gap | 数据侧处理 |
|-----|------------|
| Gap-OP05-Action | 不生成「已创建采购单」作为 V1 成功路径真相 |
| Gap-OP03-Profit-Surface | 不写 T-A-04.profit；成本/利润仅作 health 输入事实 |
| DB-G01 无流量 | OP-07/08 用 missing 维；不造 CTR 表 |
| Tool Gap-01/02/06 等 | Phase2；不为索引 Yes 的 WF 造出 Core 外 Action 真相 |

发现新缺口：登记 → 影响分析 → **用户批准**；禁止静默改 Frozen。

---

## 11. 与导出 / 双项目的边界

```text
Canonical Dataset（唯一）
        ├── PostgreSQL (+ pgvector Knowledge)  → Agent Tools / Workflow
        └── CSV / Parquet                      → 课设 Hive ODS→…（独立项目）
```

S1 **不**规定 Hive 分层字段映射；仅保证导出实体与 Agent 同源。

---

## 12. S1 → S2 交接清单

S2 Synthetic Design 必须据此给出：

1. 精确规模（dev/eval/full）与 **seed**  
2. 固定 **`as_of_date`** 与时间线起止  
3. SKU 角色分配表与注入算法说明  
4. Scenario YAML schema + 完整 `SC-*` 列表（七 WF + 建议 `SC-ISO-001`）  
5. **Inventory 策略 A 或 B** 拍板及对应校验规则  
6. StoreConfig **每 key 的默认值/类型**（在 §4.1.1 之上）  
7. Knowledge 文档清单（标题 / `knowledge_type` / layer；对齐 RAG P0-Core）  
8. 目录结构（generator/generated/scenarios/knowledge）  
9. §12A 有效订单/退货状态写入生成规则（本文 §4.3 已定需求）

**仍不写 Generator 代码，直至你批准进入 S3。**

---

## 13. S1 审查收口（V1.0.1）

| 审查项 | 状态 |
|--------|------|
| N1 §12A 有效订单/退货状态 | ✅ 已写入 §4.3 |
| N2 `as_of_date` | ✅ 已写入 §7.1 |
| N3 Movement A/B 二选一 | ✅ 已写入 §4.5 |
| N4 StoreConfig key 清单 | ✅ 已写入 §4.1.1 |
| N5 Multi-Tool / 隔离 | ✅ 已写入 §6.3 |

**结论：** S1 可作为 S2 输入；无阻塞项。S2 文档见 [synthetic-data-design-v1.md](./synthetic-data-design-v1.md)。

---

## 14. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-17 | S1 首版：原则、四资产、实体矩阵、Scenario/时间/Inventory 一致性、Gaps、S2 交接 |
| V1.0.1 | 2026-09-17 | 审查小补：§12A 状态、`as_of_date`、Inventory A/B、StoreConfig keys、Multi-Tool/ISO；S1 收口声明 |
| V1.0.2 | 2026-09-17 | Knowledge 数量口径与 S2 统一：7–15 篇（P0 最低 7；20–40 为长期扩展目标，非 V1 验收指标） |

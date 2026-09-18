# E-commerce Business Copilot — Synthetic Data Design V1.0.5

> 文档性质：**S2 Synthetic Design（如何造数）**；非 Generator 代码、非灌库、非改 Frozen DDL  
> 版本：**V1.0.5**  
> 状态：**已批准**（2026-09-18，作为 Generator 说明书；修订需用户批准）  
> 上游：[`data-requirements-v1.md`](./data-requirements-v1.md) **V1.0.1** · Database V1.2.3 Frozen · RAG V1.0 Frozen · Cross-Review §7 · AGENTS §15  
> 约束：服从 S1 矩阵与全部 Frozen 契约；发现缺口登记 Gap，不得静默改契约。

---

## 0. S2 目标与边界

| 做 | 不做 |
|----|------|
| 钉死 seed、时钟、规模、角色、规则、SC 清单、Config 默认值、Knowledge 清单、目录 | 写 Generator / 灌 PG / Hive / 改 Frozen |
| 拍板 Inventory **策略 B**（dev/eval） | 发明第二套销售/缺货算法 |
| 给出可交给 S3 的「生成说明书」 | 完整 Eval 平台 / 数仓分层设计 |

**推荐默认（本文已采纳，你可改后再进 S3）：**

```text
seed = 42
as_of_date = 2026-09-17
timeline_start = 2026-06-19   # as_of 前满 90 天
inventory_strategy = B        # 仅快照（dev/eval）
profiles_first = dev + eval   # full 后置
```

---

## 1. 时钟与可复现性

| 参数 | 值 | 说明 |
|------|-----|------|
| `seed` | `42` | 全 profile 共用；改 seed = 新世界 |
| `as_of_date` | `2026-09-17` | 分析「今天」；DOI/缺货/period 均相对此日 |
| `timeline_start` | `2026-06-19` | 订单销售窗起点（含当日） |
| `timezone` | `Asia/Shanghai`（逻辑） | 实现可用 UTC 存、按店本地解释；S3 选定一种并写清 |

Scenario 默认继承数据集 `as_of_date`；若单条覆盖须在 YAML 显式写出。

### 1.1 `as_of_date` 与 Knowledge / DB `now()`（实现卫生）

Database Contract 对「当前有效知识」使用半开区间谓词，时钟为 **`now()`**（见 Database §13.21）。  
本数据集的分析与销量窗时钟则是固定 **`as_of_date=2026-09-17`**。二者若不一致（例如评测机真实日期 ≠ as_of），会出现「种子按 as_of 写有效，运行时 `now()` 过滤结果不同」。

**S2/S3 约定（不得改 Frozen 谓词公式）：**

| 层 | 约定 |
|----|------|
| 种子写入 | ACTIVE 文档：`effective_from ≤ as_of_date`；`effective_to IS NULL` 或 `effective_to > as_of_date`；可选 expired 文档：`effective_to ≤ as_of_date` |
| 业务/分析 Tool | DOI、缺货、销量窗、OP-08 period **一律相对 `as_of_date`**（可注入参数或测试时钟） |
| Knowledge 检索评测 | **优先**注入与 `as_of_date` 对齐的评测时钟（如会话/`as_of` 覆盖）；若实现仍直读 DB `now()`，则要求评测环境把系统日设为 `as_of_date`，或把种子窗放宽到覆盖「生成日 ∪ as_of」并在 S4 注明 |
| S4 断言 | Knowledge 生命周期用例必须声明所用时钟（`as_of` 注入 **或** 固定系统日），禁止混用 |

禁止：静默把 Database 谓词改成 `as_of_date` 以迁就脏时钟。

---

## 2. Profile 规模（初值）

| 维度 | **dev** | **eval** | **full**（后置，不阻塞 S3 首版） |
|------|---------|----------|----------------------------------|
| Stores | 2 | 2（同 dev 世界子集或同 seed 切片） | 2 |
| Categories | 8 | 同左 | 10–12 |
| Products / store | ~40 | 覆盖全部 SC 所需即可 | 150–250 |
| SKUs / store | ~80 | 同上 | 300–500 |
| Customers / store | ~200 | 少量 | 1000–2000 |
| Warehouses / store | 1 | 1 | 2 |
| Staff / store | 客服2+运营2+审批1 | 同左 | 可扩 |
| Orders（全店合计，约） | ~1,500–3,000 | 够支撑 SC 时间线 | 30k–80k 量级另议 |
| 时间跨度 | 90 天至 as_of | 同左 | 同左或更长 |
| Knowledge 文档 | P0-Core 全套 + 可选 1 inventory | 同左 | 同左 |
| Scenario | §8 清单全覆盖 | **同一清单**（黄金集） | 可追加非黄金 |

**规则：** `dev` 与 `eval` **同一生成规则与 seed**；`eval` 可以是「完整跑一遍后只导出 SC 引用的对象 + 必要上下文」，或「全量 dev 上挂 manifest」。S3 二选一实现，优先 **同库 + manifest 过滤**。

---

## 3. 租户与人员

| ID 约定 | 含义 |
|---------|------|
| `STORE_01` / `STORE_02` | 两店；**默认分析店 = STORE_01** |
| `STORE_02` | **隔离测试 + 缺配置测试专用店**（见 §5）；不承载需要完整 StoreConfig 的 data-SC |
| `WH_01_01` | STORE_01 主仓 |
| `WH_02_01` | STORE_02 主仓 |
| `STAFF_01_CS_*` | STORE_01 客服 |
| `STAFF_01_OP_*` | STORE_01 运营 |
| `STAFF_01_APPR_01` | STORE_01 审批执行人（CS-08） |

`SC-ISO-001`：以 STORE_01 用户访问 STORE_02 订单 → 期望 FORBIDDEN / 空隔离。

`STAFF_01_APPR_01` 等审批人是**业务流程节点**（Business §2.4），非独立角色：S3 造数时必须是 `staff_users.role ∈ {customer_service, operations}` 的合法员工，仅在具体售后单/工单中充当 `approver_id`；禁止新增独立 approver 角色。

---

## 4. Inventory 策略拍板：**B（仅快照）**

| 项 | 约定 |
|----|------|
| 生成 | `warehouses` + `inventory`（当前快照） |
| **不生成** | `inventory_movements`（dev/eval） |
| 快照如何定 | 按 SKU **角色目标** + 近 14/30 天 §12A 销量叙事，反推合理 `available_qty` / `safety_stock` |
| 校验（S4） | `available≥0`、`reserved≥0`；角色标签与「销量高+库存低」等叙事一致；**不做**流水平衡 |
| full 升级 | 若课设需要进销存，另开变更升策略 **A**，不在本 V1.0 强制 |

禁止：策略 B 下仍写入无关联的假 Movement。

---

## 5. StoreConfig 默认值（STORE_01 / STORE_02 相同，除非 SC 覆盖）

| config_key | value（JSON 或标量，S3 按 DB 列类型序列化） | 说明 |
|------------|-----------------------------------------------|------|
| `inventory.lead_time_days` | `7` | 补货提前期 |
| `inventory.default_horizon_days` | `14` | OP-04/05 默认展望窗 |
| `inventory.slow_moving.lookback_days` | `30` | 慢销观察窗 |
| `inventory.slow_moving.max_units` | `15` | 窗内销量上限（低于则入候选；S3 可微调） |
| `health.weights` | `{"sales":0.3,"inventory":0.2,"margin":0.2,"return":0.2,"feedback":0.1}` | 总和 1.0；键 ⊆ 核心维 |
| `health.core_dimensions` | `["sales","inventory","margin","return","feedback"]` | 对齐 Business OP-07「建议必选」；缺任一 → 完整度降级 |
| `health.optional_dimensions` | `["traffic"]` | V1 仅流量可选且 **恒缺失**（DB-G01）；缺可选 **不**触发核心降级 |
| `anomaly.baseline_mode` | `wow` | 与 `baseline_policy` 策略标识对齐 |
| `anomaly.sales_drop_threshold` | `0.30` | 销量相对基线下跌 ≥30% → 异常候选阈值 |

**V1 简化声明（用户已认账，2026-09-17）：** Business OP-07 可选维原为「评价、履约、流量/CTR/转化等」。V1 处理：评价并入核心维 `feedback`（同源 `customer_feedback`，含 rating）；**履约维 V1 不做**；可选维仅保留 `traffic` 且恒缺失（DB-G01）。核心五维与 Business OP-07 核心维逐字对齐；这是 **V1 implementation profile**（当前实现选定），非改写 Business 定义为「只有五个维度」，亦不改任何 Frozen 契约。

**margin 维口径：** `margin`（毛利）以 `cost_price` 近似（`selling_price − cost_price`），对应 Business OP-07 的「利润」维；与 Gap-OP03-Profit-Surface（T-A-04 不输出 profit）区分。

**SC 覆盖示例：** `SC-OP05-003` / `SC-OP08-003` 在 **STORE_02**（缺配置测试专用店，见 §3）删除或清空必要 key → `UNDETERMINED`。STORE_02 须具备 `R_STOCKOUT` / `R_NORMAL` 级销售与库存事实，确保 UNDETERMINED 的**唯一**原因是缺配置，而非缺销量/库存。

SKU 级 `inventory.safety_stock`：写在 **`inventory.safety_stock` 列**（Database 字段）；Config 不重复存每 SKU，除非 S3 发现需要店级默认 `inventory.safety_stock_days`（可选增补，默认不用）。

---

## 6. SKU 角色分配（逻辑标签 → 生成约束）

> 角色是 **生成标签**（可存于生成器内部表或 `sku` 扩展 meta，**不是**业务风险结论列）。  
> 下列为 **STORE_01** 最低集合；STORE_02 可缩略复制一组用于隔离测试。

| role_id | 标签 | 销量叙事（相对 as_of） | 库存叙事 | 其他 | 主要服务 SC |
|---------|------|------------------------|----------|------|-------------|
| `R_HOT` | 爆款 | 近 30 天高 units | 中高库存 | — | 基线/对照 |
| `R_NORMAL` | 正常 | 中位销量 | 健康 DOI | — | OP-04 NO_RISK 等 |
| `R_SLOW` | 慢销 | 近 30 天极低 units | 偏高库存 | — | OP-03 候选 |
| `R_SLOW_HEALTHY` | 慢销但利润好 | 低销 | **低库存** | 有 `cost` 且毛利高 | OP-03：慢销 ≠ health 差 |
| `R_STOCKOUT` | 将缺货 | 近 14 天销高 | **很低** available | safety 正常 | OP-04 HAS_RISK；OP-05 HAS_RECO |
| `R_OVERSTOCK` | 积压向 | 低销 | 很高库存 | — | OP-03；对照 |
| `R_RETURN_HIGH` | 高退货 | 中销 | 中 | 有效 RETURN 多 | OP-07/08 |
| `R_PRICE_DROP` | 近期降价 | 降价后销量变化 | 中 | PriceHistory 在 as_of 前 7–14 天 | OP-08 |
| `R_ANOMALY_DROP` | 销量骤降 | 前段正常、近 7 天暴跌 | 中 | 达 anomaly 阈值 | OP-08 ANOMALY |
| `R_SPARSE_SALES` | 销量稀疏 | 有效销售点过少 | 任意 | — | OP-04/05 UNDETERMINED |
| `R_HEALTH_FULL` | 健康五核心齐 | 有销/库存/退货/反馈/`cost`（margin） | 中 | 无 traffic | OP-07：五核心齐，仅缺可选 traffic |
| `R_HEALTH_CORE_MISS` | 缺核心维 | 刻意缺 **sales / inventory / margin / return / feedback** 之一 | — | 例如无 cost、无反馈、或无有效销量窗 | OP-07 缺核心维 / 降级 |
| `R_BASELINE` | 全能正常 | 正常 | 正常 | 无异常物流绑定 | 多 WF NORMAL/EMPTY |

**数量建议（dev / STORE_01）：** 每角色 ≥1 个 SKU；`R_NORMAL`/`R_HOT` 可 3+；其余 ≥1。  
**绑定：** S3 生成后把实际 `sku_id` 写回 Scenario manifest（或生成时按 role 预分配稳定 ID，如 `SKU_01_STOCKOUT_01`）。  
**角色 → 具体参数（S3.2 钉死）：** 本表角色只给「销量/库存叙事」约束；角色到具体生成参数（单量、库存数值、分布/抽样规则）由 S3.2 交易主链实现时钉死，并以叙事为约束，不在本文细化到数值区间。

### 6.1 类目清单（P2 与 Knowledge 共享契约，用户 2026-09-18 采纳）

8 个类目为 dev 默认（`profiles.yaml` dev.categories=8）；`full` 后期可扩 `digital`/`jewelry`（不在 V1.0.5 定）。类目是 store 级（`product_categories.store_id`）：STORE_01 用全套；STORE_02 用子集（P2 定，以缺配置/隔离 SC 所需为准）。

| code | 中文 | 售后定位 | 主要服务 |
|------|------|----------|----------|
| `customized` | 定制类 | **法定不可退**（消保法 §25） | CS-08 ineligible；KD-AS-02；R2 排除案例 |
| `fresh` | 食品/生鲜 | **法定不可退**（鲜活易腐） | CS-08 ineligible 第二例；KD-OP-01 类目例外 |
| `electronics` | 数码/电子 | 可退 + 拆封激活价值贬损 | R3 载体（KD-AS-04 店规）；OP-08；R_STOCKOUT/R_PRICE_DROP |
| `beauty` | 美妆/个护 | 平台级不可退/特殊（拆封卫生） | KD-AS-02 平台模拟规则；R_RETURN_HIGH 可选 |
| `apparel` | 服装/服饰 | 一般可退 | CS-08 eligible 主案例；R_RETURN_HIGH；**conflict 产品所在类目** |
| `home` | 家居/家纺 | 一般可退 | R_SLOW/R_OVERSTOCK；OP-03 |
| `books` | 图书/音像 | 部分不可退（音像拆封） | KD-AS-02 例外细化；低成本高频基线 |
| `baby` | 母婴/玩具 | 可退 + 安全类特殊 | KD-OP-01 类目例外；退货/健康多样性 |

**conflict 专属产品 scope tag（SC-CS08-007 前置）：** 在 `apparel` 内用**窄于类目的 product-type tag**（如 `apparel-conflict-test`）标识唯一 conflict 产品；KD-AS-CONF-01/02 的适用标签指向该 tag，保证 R2 对其它 apparel 的 CS-08 eligible 用例排除冲突对。

---

## 7. 生成管线规则（Master → Transaction → Inject）

### 7.1 顺序

```text
1. Stores, Staff, Warehouses, StoreConfig
2. Categories, Products, Skus（打 role 标签）
3. Customers（+ 少量 Address）；下单时把地址**复制**进 `orders` 收货地址快照列（DB §13.10，不指向可变地址表）
4. Orders + OrderItems（90 天；§12A 状态）
5. Shipments + ShipmentEvents（绑定订单）
6. Inventory 快照（策略 B，按 role）
7. AfterSales（有效退货状态集）、Feedback、PriceHistory
8. Campaign（可选少量，挂 R_PRICE_DROP / R_ANOMALY）
9. Scenario Injection 校验/微调（保证 SC 可满足）
10. Knowledge：不自动乱写正文；按 §9 清单人工稿导入
```

### 7.2 订单与 §12A

- 计入分析窗的行：订单 status ∈ `{PAID, PROCESSING, SHIPPED, COMPLETED}`。  
- 可另造少量 `CANCELLED` / `PENDING_PAYMENT` **不计入**销量。  
- 时间序：`ordered_at ≤ paid_at ≤ shipped_at ≤ delivered_at ≤ signed_at`（有则）。  
- `promised_delivery_at`：正常单 ≥ 实际送达；异常单 **promised &lt; actual 或仅有轨迹停滞**。

### 7.3 物流（CS-06）

| 模式 | 构造 |
|------|------|
| NORMAL | 按时送达；事件完整 |
| ANOMALY | 超 promised 未送达或严重延误事件 |
| UNDETERMINED | **缺** `promised_delivery_at` 或关键事件，使 T-A-01 无法判定 |

### 7.4 售后 / 反馈 / 价格

- 反馈 `created_at ≥ delivered_at`。  
- 退货 `quantity ≤ order_item.quantity`；状态用有效退货集才能进 return_rate。  
- PriceHistory：仅 SKU；最新 `new_price` = `product_skus.selling_price`。

### 7.5 禁止

- 落库 health_score / is_anomaly / recommended_qty / HAS_RISK。  
- 为 SC 复制第二套订单真相。  
- RAG 正文写 lead_time/阈值数字代替 StoreConfig。

---

## 8. Scenario YAML Schema 与完整清单

### 8.0 Scenario `nature`（数据态 vs 运行时评测）

| nature | 含义 | S3/S4 期望 |
|--------|------|------------|
| **`data`** | 仅靠 Canonical 种子 + Config/Knowledge 即可复现期望路由 | 导入 PG 后跑 Tool/计算应可绿 |
| **`runtime_eval`** | 依赖 HITL 模拟、故障注入、Knowledge mock 等**过程** | 种子可提供前置事实；断言须在评测 harness 中驱动确认/审批/失败注入；**禁止**误以为「只灌库就能绿」 |

一条 SC 若兼有数据前置与运行时步骤，标 **`runtime_eval`**，并在备注写清前置 data 与 harness 动作。

### 8.1 Schema（S3 文件建议 `data/scenarios/eval/scenarios.yaml`）

```yaml
dataset:
  seed: 42
  as_of_date: "2026-09-17"
  profile: eval

scenarios:
  - scenario_id: SC-OP04-001
    workflow: OP-04
    nature: data              # data | runtime_eval（见 §8.0）
    description: "high stockout risk SKU"
    store_id: STORE_01
    sku_ids: [SKU_01_STOCKOUT_01]
    input_scope:
      horizon_days: 14
    trigger_type: LOW_STOCK_HIGH_SALES
    expected_route: HAS_RISK
    expected_reason: null
    role_hint: R_STOCKOUT   # 生成期用；导出可选保留
```

必填：`scenario_id`, `workflow`, `store_id`, **`nature`**，以及该 WF 所需主键引用。  
`expected_route`：**统一路由枚举族**的 WF（CS-06 / CS-08 / OP-03 / OP-04 / OP-05 / OP-08）必填；**OP-07 无统一 route 枚举**（按 `level`+`data_completeness` 编排），其 `expected_route` 可为 `null`，断言记于 `expected_formal_result`。
选填：`expected_reason`, `expected_formal_result`, `input_scope`, `trigger_type`, `order_id`, `product_id`。

### 8.2 完整 SC 清单（黄金集；S3 绑定真实 ID）

#### CS-06

| scenario_id | nature | expected_route | trigger_type | 备注 |
|-------------|--------|----------------|--------------|------|
| SC-CS06-001 | data | NORMAL | ON_TIME_DELIVERY | |
| SC-CS06-002 | data | ANOMALY | PAST_PROMISED | |
| SC-CS06-003 | data | UNDETERMINED | MISSING_PROMISED_AT | |
| SC-CS06-004 | runtime_eval | ANOMALY | DELAY_THEN_KNOWLEDGE_DOWN | 数据可造延误单；评测 **mock Knowledge 不可用** 仍出分析 |

#### CS-08-09

| scenario_id | nature | expected_route | trigger_type | 备注 |
|-------------|--------|----------------|--------------|------|
| SC-CS08-001 | data | eligible | WITHIN_WINDOW | 可走确认→审批→建单（完整链路另用 harness） |
| SC-CS08-002 | data | ineligible | WINDOW_EXPIRED | |
| SC-CS08-003 | data | undetermined | MISSING_SIGNED_AT | |
| SC-CS08-004 | runtime_eval | eligible | CONFIRM_CANCEL | 前置 eligible 事实；评测停在 Confirmation **取消** |
| SC-CS08-005 | runtime_eval | eligible | APPROVAL_REJECT | 前置 eligible；评测 **审批拒绝** |
| SC-CS08-006 | data | —（对照，无路由断言） | PREEXISTING_AFTERSALES | 种子预置一单已成功售后（status=APPROVED/COMPLETED）作对照，支撑退货率/CS-08 参考；eligible 路由由 001 覆盖 |
| SC-CS08-007 | runtime_eval | undetermined | RULE_CONFLICT | 前置：conflict 产品（apparel+窄 tag，§6.1）+ KD-AS-CONF-01/02 双 ACTIVE 在窗内 + 订单 signed_at∈as_of 前(7,15)天且其余资格条件全满足；**RULE_CONFLICT 断言归 S4/harness**（resolution-service-dependent，见 §8.0） |

#### OP-03

| scenario_id | nature | expected_route | trigger_type | 备注 |
|-------------|--------|----------------|--------------|------|
| SC-OP03-001 | data | HAS_CANDIDATES | SLOW_MOVING | R_SLOW |
| SC-OP03-002 | data | EMPTY | NO_SLOW_IN_SCOPE | 类目/窗内无慢销 |
| SC-OP03-003 | data | HAS_CANDIDATES | SLOW_WITH_HEALTH | R_SLOW_HEALTHY；勿等同滞销风险等级 |
| SC-OP03-004 | runtime_eval | UNDETERMINED | PERF_QUERY_FAIL | 可选；故障注入或数据不足二选一，标清 harness |

#### OP-04

| scenario_id | nature | expected_route | trigger_type | 备注 |
|-------------|--------|----------------|--------------|------|
| SC-OP04-001 | data | HAS_RISK | LOW_STOCK_HIGH_SALES | R_STOCKOUT |
| SC-OP04-002 | data | NO_RISK | HEALTHY_DOI | R_NORMAL |
| SC-OP04-003 | data | UNDETERMINED | MISSING_SALES_WINDOW | R_SPARSE_SALES |
| SC-OP04-004 | data | HAS_RISK | LOW_STOCK_HIGH_SALES | 同 001；metadata `handoff_to: OP-05`（移交为 WF 行为，非数据构造） |

#### OP-05

| scenario_id | nature | expected_route | trigger_type | 备注 |
|-------------|--------|----------------|--------------|------|
| SC-OP05-001 | data | HAS_RECO | RESTOCK_NEEDED | R_STOCKOUT |
| SC-OP05-002 | data | NO_RECO | STOCK_SUFFICIENT | R_NORMAL |
| SC-OP05-003 | data | UNDETERMINED | MISSING_LEAD_TIME_CONFIG | 缺 StoreConfig |
| SC-OP05-004 | data | HAS_RECO | SKIP_PRESCREEN | 指定 SKU 直接算建议 |
| SC-OP05-005 | runtime_eval | HAS_RECO | CONFIRM_ACCEPT | 前置 HAS_RECO；评测模拟 Confirmation 接受 |
| SC-OP05-006 | runtime_eval | HAS_RECO | CONFIRM_REJECT | 前置 HAS_RECO；评测模拟拒绝 |

#### OP-07

| scenario_id | nature | expected_route / 焦点 | trigger_type | 备注 |
|-------------|--------|------------------------|--------------|------|
| SC-OP07-001 | data | 五核心齐；仅缺可选 traffic | FULL_CORE | R_HEALTH_FULL；缺 traffic **不**降核心完整度 |
| SC-OP07-002 | data | 可选维缺失可标注 | MISSING_OPTIONAL | V1 可选仅 traffic 且恒缺；断言「可选缺失已标注、核心未降级」（与 001 可同 SKU 或对照说明） |
| SC-OP07-003 | data | 缺核心维 / 降级 | MISSING_CORE | R_HEALTH_CORE_MISS（缺 margin/feedback/sales 等之一） |

（OP-07 无统一 route 枚举：`expected_route` 可为 `null`，断言记 `level`+completeness 摘要于 `expected_formal_result`，见 §8.1。）

#### OP-08

| scenario_id | nature | expected_route | trigger_type | 备注 |
|-------------|--------|----------------|--------------|------|
| SC-OP08-001 | data | ANOMALY | DROP_OVER_THRESHOLD | R_ANOMALY_DROP |
| SC-OP08-002 | data | NORMAL | BELOW_THRESHOLD | R_NORMAL |
| SC-OP08-003 | data | UNDETERMINED | MISSING_ANOMALY_CONFIG | 缺阈值 key |
| SC-OP08-004 | data | ANOMALY | DROP_WITH_PRICE_EVIDENCE | R_PRICE_DROP |

#### 隔离

| scenario_id | nature | expected_route | 备注 |
|-------------|--------|----------------|------|
| SC-ISO-001 | data | FORBIDDEN | STORE_01 上下文读 STORE_02 |

**合计：** 33 条黄金 SC（26 data + 7 runtime；可按实现微调，但类型不可少于 S1 §6.2）。  
**其中 `runtime_eval`：** SC-CS06-004、SC-CS08-004/005/007、SC-OP03-004、SC-OP05-005/006（共 7 条）；其余为 `data`。

---

## 9. Knowledge 文档清单（人工稿；对齐 RAG P0-Core）

| doc_id | 主题 | knowledge_type | layer | platform / store_id | 对齐 |
|--------|------|----------------|-------|---------------------|------|
| KD-AS-01 | 七日无理由退货底线 | after_sales | legal | platform=default | CS-08 |
| KD-AS-02 | 例外商品/不可退类目 | after_sales | platform | platform=default | CS-08 |
| KD-AS-03 | 完好要求与凭证 | after_sales | platform | platform=default | CS-08 |
| KD-AS-04 | 店铺补充售后政策（STORE_01） | after_sales | store | store_id=STORE_01 | CS-08/09 |
| KD-LG-01 | 发货时效与物流异常处理 | logistics | platform | platform=default | CS-06 |
| KD-OP-01 | 健康维度说明与类目例外 | operations | store | store_id=STORE_01 | OP-07 |
| KD-INV-01 | 库存/备货文字政策（非数字） | inventory | store | store_id=STORE_01 | OP-04/05 可选 |
| KD-AS-EXP-01 | 已过期（`effective_to ≤ as_of`） | after_sales | platform | platform=default | 生命周期过滤（eval 夹具） |
| KD-AS-CONF-01 | 冲突对 A：签收 **7 日内**可退 | after_sales | store | store_id=STORE_01 | SC-CS08-007（R5） |
| KD-AS-CONF-02 | 冲突对 B：签收 **15 日内**可退 | after_sales | store | store_id=STORE_01 | SC-CS08-007（R5） |

`layer` 为**单值枚举**（`legal | platform | store`，对齐 DB §13.x / RAG §3.1 / T-K-01 `rule_sources.layer`）；`platform` / `store_id` 是独立元数据列（DB `platform VARCHAR(32)`，默认 `default`）。RAG §12 示例中的 `legal/platform` 组合写法**不迁移**到本表。

**数量口径（与 S1 §4.7 统一）：** P0-Core 最低 **7 篇**（KD-AS-01~04 / KD-LG-01 / KD-OP-01 / KD-INV-01）；全量 **10 篇** = 7 P0-Core + **KD-AS-EXP-01**（生命周期夹具）+ **KD-AS-CONF-01/02**（R5 冲突夹具）；V1 目标 7–15 篇。expired/conflict 为 **eval 用途、非 P0-Core**，S3.5/S3.6 不得当作数据错误。S1 所述「20–40 篇」为长期扩展目标，**非 V1 验收指标**。

要求：P0-Core 与 conflict 对全部 `status=ACTIVE` 且相对 **`as_of_date`** 落在有效窗内（见 §1.1）；`KD-AS-EXP-01` 为 `effective_to ≤ as_of_date` 测生命周期过滤。  
正文 S3 前人工撰写短文；**禁止**爬取冒充平台真理。  
S4：Knowledge 生命周期断言须声明时钟（`as_of` 注入或固定系统日 = `as_of_date`），与 Database `now()` 谓词兼容，**不**改 Frozen SQL。

**conflict 对构造约束（KD-AS-CONF-01/02，SC-CS08-007 前置，用户 2026-09-18 采纳）：**
- 同层 **store** / 同 `section=return` / 同 scope（`apparel` 下窄 product-type tag）/ **同 specificity** / 双 ACTIVE 在 as_of 窗内；
- 内容维度必须是**资格相关**的退货窗口（7 日内 vs 15 日内），**禁止**落在退款方式等非资格维度（不影响三态，SC 会失效）；
- 类目用普通可退的 `apparel`，**禁止**用法定排除类目（`customized`/`fresh`）——否则 legal 经 R4 直接判 `ineligible`，不落 R5；
- 适用标签为 conflict 产品的窄 tag（**非整个类目**），保证 R2 对其它 apparel 的 CS-08 eligible 用例排除冲突对；
- 订单约束：`signed_at` ∈ as_of 前 **(7, 15) 天**（如 10 天），且**除窗口外其余资格条件全满足**，使 RULE_CONFLICT 唯一来源是窗口矛盾；早于 7 天被 legal 直接判可退，晚于 15 天两条店规均不满足。

---

## 10. 目录约定（S3 落地）

```text
data/
├── generator/           # S3：脚本与 config
│   ├── config/
│   │   ├── profiles.yaml      # dev/eval/full
│   │   └── store_configs.yaml
│   ├── rules/                 # 角色与注入规则
│   └── README.md
├── scenarios/
│   └── eval/
│       └── scenarios.yaml     # §8 清单
├── knowledge/
│   └── seed/                  # §9 markdown/json 人工稿
├── generated/                 # S3 输出（gitignore 大文件可选）
│   ├── dev/
│   │   └── canonical/         # 表级 CSV/Parquet 或 jsonl
│   └── eval/
└── export/                    # S5：pg dump 说明 / 课设包
```

Agent 仓库与课设仓库：**可复制 `generated/*/canonical` + 同一 generator**；课设自建 Hive，不回写本仓库 Frozen。

---

## 11. S4 校验预告（本设计下的检查单）

| 检查 | 策略 B 下 |
|------|-----------|
| Schema / FK | ✅ |
| §12A 状态与退货 quantity | ✅ |
| 时间序 / 反馈≥送达 / 价格史一致 | ✅ |
| Movement 平衡 | **跳过**（未生成） |
| 角色叙事 vs 库存销量 | ✅ |
| 每个 SC expected_route | ✅：`nature=data` 仅灌库+Tool；`nature=runtime_eval` 须 harness |
| OP-07 核心维 | ✅ 五核心齐 / 缺核心降级 / 可选 traffic 缺失不降核心 |
| Knowledge 生命周期 | ✅ 相对 as_of 或声明的评测时钟（§1.1） |
| SC-ISO-001 | ✅ |

---

## 12. Gaps 提醒（不变）

Gap-OP05-Action、Gap-OP03-Profit-Surface、DB-G01、Tool Phase2 Gaps——造数与 SC **不得假装已关闭**。

---

## 13. S2 → S3 交接

### 13.1 已拍板（进入 S3 的默认）

| 项 | 决定 |
|----|------|
| `seed` / `as_of_date` / 策略 **B** / 规模初值 | 采用本文 §0–§2 |
| SC 清单与 `nature` | 采用本文 §8 |
| `health.core_dimensions` 五核心 | 采用本文 §5 |
| **OP-07 可选维 V1 简化**（评价并入 feedback、履约不做、可选仅 traffic） | 用户 2026-09-17 认账；记录于 §5 |
| **缺配置 SC 店铺归属**（STORE_02 专用） | 用户 2026-09-17 拍板；记录于 §3/§5 |
| Knowledge | **方案 A**：正文人工轨与 Generator **并行**；导入属 **S3.5**（见 §15） |
| S3 工程拆分 | **S3.0–S3.7**（见 §15）；`full` / 策略 A / runtime harness / 课设导出后置 |

### 13.2 进入 S3 前确认（已收口）

1. ✅ 批准 S2 **V1.0.4**（含 §15）作为 Generator 说明书（用户 2026-09-17）；**V1.0.5** 增补 conflict 对 + SC-CS08-007 + 8 类目 + 状态翻转（用户 2026-09-18 批准，**Knowledge 窗口评审通过，正式锁定**）
2. **K-A** P0-Core 正文由用户 Knowledge 窗口并行产出（2026-09-18 决定），本仓库不自行生成；S3.5 在稿到位前 stub 导入接口

> 交叉审查两处 ⚠️ 已于 V1.0.3 落定；二轮复审的 `layer` 单值、Knowledge 数量口径、OP-07 断言位、SC 语义已在 V1.0.4 收口；V1.0.5 收口 conflict 对 / R5 SC / 类目契约，见 §6.1/§8.2/§9/§15.2。

S3 总形态：`generate`（分阶段模块）→（S3.6）`validate` 骨架 → 写出 `data/generated/dev|eval`；Knowledge 走 `knowledge/seed` → S3.5 导入。

---

## 14. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-17 | S2 首版：时钟/seed、profile、策略 B、Config 默认值、角色表、生成规则、SC 全清单、Knowledge、目录 |
| V1.0.1 | 2026-09-17 | 交叉审查小补：OP-07 核心维对齐 Business；§1.1 as_of vs Knowledge `now()`；SC `nature`（data/runtime_eval） |
| V1.0.2 | 2026-09-17 | 拍板 S3.0–S3.7 拆分 + Knowledge 方案 A（§15）；更新交接 |
| V1.0.3 | 2026-09-17 | 交叉审查落定：OP-07 可选维 V1 简化认账（§5）；缺配置 SC 定 STORE_02 专用店（§3/§5）；margin 口径、地址快照复制、APPR 角色说明、SC 计数 30→32（§3/§6/§7.1/§8.2） |
| V1.0.4 | 2026-09-17 | 交叉复审收口：Knowledge `layer` 改单值枚举 + `platform`/`store_id` 列、数量口径与 S1 统一（§9）；OP-07 `expected_route` 可空、断言入 `expected_formal_result`（§8.1/§8.2）；SC-CS08-006 改 PREEXISTING_AFTERSALES 对照、SC-OP04-004 移交拆入 metadata（§8.2）；S3.1 门禁措辞（§15.2）；文档标题对齐 |
| V1.0.5 | 2026-09-18 | 状态翻转为**已批准**；§6.1 固化 8 类目 + conflict 专属产品 scope tag；§8.2 加 SC-CS08-007（R5 冲突，runtime_eval，33 条 = 26 data + 7 runtime）；§9 加 KD-AS-EXP-01 + conflict 对 KD-AS-CONF-01/02（全量 10 篇，含构造约束）；§13.2 收口（V1.0.4 已批准、K-A 移交 Knowledge 窗口） |

---

## 15. S3 子阶段拆分与 Knowledge 轨（方案 A）

> **性质：** 实施分期说明书（仍非 Generator 代码）。  
> **原则：** 每子阶段有明确产出与验收门；未过门不进入下一子阶段。  
> **Knowledge：** 正文 **不**由业务合成器随机生成；与订单/库存分轨。

### 15.1 总览

```text
        ┌─ K-A 人工正文（可与 S3.0–3.3 并行）──┐
S3.0 → S3.1 → S3.2 → S3.3 → S3.4 ────────────→ S3.5 → S3.6 → S3.7
骨架    Master   交易    派生    Scenario 绑定    导入KD   校验    eval切片
```

**刻意后置（不阻塞 S3.0–3.7 关门）：** profile=`full`、Inventory 策略 A、embedding 调优、`runtime_eval` harness、课设 Hive/S5 导出。

### 15.2 子阶段定义

| 子阶段 | 范围 | 主要产出 | 验收门（过门条件） |
|--------|------|----------|-------------------|
| **S3.0 骨架** | 目录、CLI、`profiles.yaml`、seed/as_of 读入、空/最小 generate | `data/generator/` 可跑；写出空 manifest 或占位 canonical | CLI 退出码 0；路径符合 §10 |
| **S3.1 Master** | Store/Staff/Warehouse/Category/Product/SKU + role + StoreConfig | 主数据表文件；每角色 ≥1 SKU；§5 Config 齐全 | FK 自洽；两店隔离 ID；P0 StoreConfig keys 与 **Health 五核心维**配置正确 |
| **S3.2 交易主链** | Customer → Order/Item（§12A）→ Shipment/Event → Inventory 快照（B） | 90 天窗订单；策略 B 库存 | 时间序抽样通过；`R_STOCKOUT` 等角色叙事可辨；无 Movement |
| **S3.3 派生事实** | AfterSales、Feedback、PriceHistory、少量 Campaign | 退货/反馈/价格史文件 | quantity 与 §12A；反馈≥送达；价格史落在 as_of 前 |
| **S3.4 Scenario 绑定** | `scenarios.yaml` + 稳定 ID / inject；**仅 `nature=data`** | 黄金 data-SC 主键可解析 | 全部 data-SC 引用存在；runtime_eval 仅挂前置 ID、不断言进程 |
| **S3.5 Knowledge 导入** | 读 `knowledge/seed` → documents/chunks（embedding 可 stub） | Knowledge 表级输出 | P0-Core ACTIVE 在 as_of 窗内；可选 expired 可过滤；**不改** DB `now()` 谓词 |
| **S3.6 校验骨架** | schema/FK/§12A/角色抽样/SC data 路由前置 | `validate` 报告 | 无 P0 级失败（门禁清单见 §11，Movement 跳过） |
| **S3.7 eval 切片** | 同 seed + manifest 过滤（或同库挂 SC） | `generated/eval/` | eval 含全部黄金 SC 引用对象；与 dev 同 seed |

### 15.3 Knowledge 轨（方案 A）

| 工作包 | 内容 | 时机 | 说明 |
|--------|------|------|------|
| **K-A 正文种子** | §9 清单短文 + 元数据（type/layer/store/version/`effective_*`） | **与 S3.0–3.3 并行**；S3.5 前门至少 CS-08 四篇 + CS-06 一篇 | 人工审核；禁止爬取冒充真理 |
| **K-B 切块约定** | 短 chunk、一意一段、元数据继承 | K-A 同期写 README；代码在 S3.5 | 对齐 RAG |
| **K-C 导入器** | seed → documents/chunks（+ 可选 embedding） | **S3.5** | 旁路模块，非订单 Generator |
| **K-D expired 样例** | 如 `KD-AS-EXP-01` | K-A 备 1 篇 | 测生命周期 |
| **K-E runtime mock** | SC-CS06-004 Knowledge 不可用 | **后置**（S4/harness） | 非造数 |

数值阈值只进 StoreConfig；RAG 正文禁止写 lead_time 等数字代替 Config。

### 15.4 阶段门禁规则

1. 每子阶段结束：对照 §15.2 验收门做 **核查与评估**（人工确认）。  
2. **未过门不得进入下一子阶段**（允许门内修 bug 重跑）。  
3. K-A 可并行，但 **S3.5 不得在无最低 P0-Core 稿时强行关门**（可先 stub 导入接口，验收记「稿件阻塞」）。  
4. 发现与 Frozen 冲突：停止扩 scope → 登记 → 你拍板；不得静默改契约迁就脏数据。

# E-commerce Business Copilot — Core Tool Design V1.1

> 文档性质：**Capability Contract / Core Tool Design**（非实现代码、非数据库 DDL）  
> 版本：**V1.1**  
> 状态：**Frozen**（2026-09-12；未经用户批准不得改写核心契约）  
> 业务输入：**仅** [business-scenarios-v1.md](./business-scenarios-v1.md) **V1.1**（已冻结）  
> 约束：本文**不得**修改或重新定义业务场景；发现业务缺口只能记入 Open Gaps 并反馈回 Business Baseline。  
> V1.1 焦点：资格三态、系统事实优先、默认权限规则、Action 风险策略、计算服务复用、表现查询边界、P0 覆盖语义；冻结前补齐 `create_return_request` 的 `quantity` / 行项目必填。

---

## 1. 文档定位与约束

### 1.1 本文回答什么

| 问题 | 由本文回答 |
|------|------------|
| 业务能力如何变成 Agent 可调用接口？ | ✅ |
| 每个 Core Tool 的契约是什么？ | ✅ |
| P0 场景是否被 Tool 覆盖？ | ✅ |
| 风险 / 审批 / 权限上下文 / 失败约定？ | ✅ |
| 具体表结构 / PostgreSQL vs MySQL？ | ❌ → Database Design |
| LangGraph 节点详设？ | ❌ → Workflow Design（本文仅 Composition 原则） |
| Python `@tool` / MCP / REST 实现？ | ❌ → Technical Design |

### 1.2 继承的业务原则（必须遵守）

1. 事实与判断分离；确定性计算不得由模型臆造  
2. 信息不足 / 数据缺失 / 规则冲突 / 能力不可用 → 不得臆测  
3. 高风险：建议 → 审批人确认 → 执行 → 可追溯  
4. 数据访问：员工权限范围 + 敏感信息最小必要  
5. 回复草稿**不是** Tool，属于 Agent 生成能力  
6. 不锁定数据库产品与向量库产品  

### 1.3 设计转化链

```text
Business Baseline V1.1
        ↓
Capability Inventory（本文 §6）
        ↓
Tool Boundary（本文 §7）
        ↓
Tool Contract（本文 §8–9）
        ↓
Scenario Mapping（本文 §10）
```

---

## 2. Tool Design Principles

| # | 原则 | 说明 |
|---|------|------|
| P1 | 单一职责 | 一个 Tool 只做一类业务动作；禁止超级 Tool |
| P2 | 读写分离 | Query/Analysis/Knowledge/Recommendation 与 Action 拆分 |
| P3 | 建议与执行分离 | Recommendation 不改状态；改状态必须走 Action + 审批 |
| P4 | 事实与知识分离 | 结构化事实查询 ≠ 业务规则检索 |
| P5 | 算在能力内 | 指标、资格、健康分、异常判定在 Tool/Service 内确定性完成 |
| P6 | 接口抽象 | Tool 是业务能力接口，实现可为 Function / Service / SQL / API / MCP |
| P7 | 控制数量 | V1 Core 优先覆盖 P0；优先复用；避免过度拆分 |
| P8 | 缺口上报 | 基线未支撑的能力记 Gaps，禁止自创业务规则 |
| P9 | 上下文先于取数 | 默认继承全局 `user_context` + store scope；Tool 仅声明额外限制 |
| P10 | Action 可审计 | **所有 Write/Action 默认 `audit_required=true`**，除非显式例外 |
| P11 | 系统事实优先 | 业务事实由 Tool 从可信数据源读取；**禁止** LLM 注入字段覆盖系统事实 |
| P12 | 计算复用 | 公共指标/库存估计由统一 Calculation Service 计算，各 Tool 只组织输出 |

---

## 3. Tool Architecture

```text
                    Agent (理解 / 编排 / 解释 / 生成草稿)
                              │
                              ▼
                    ┌─────────────────────┐
                    │   Tool Contract     │  ← 本文定义
                    │  (业务能力接口)      │
                    └─────────┬───────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │ Business Service    │  ← Technical Design
                    │ + Calculation Svc   │  （销售/库存等公共计算复用）
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        结构化业务数据      业务知识库      外部能力(可选)
        (产品由 DB 设计定)  (由 Knowledge 定)
```

**不是**：`LLM → 随意 SQL / 随意改状态`。

### 3.1 Calculation Service 复用（契约层约束）

下列 Tool **不得各自实现一套漂移公式**，须共用内部计算能力（实现形态由 Technical Design 决定）：

| Calculation 域 | 复用方 Tool |
|----------------|-------------|
| 销售基础指标（GMV/orders/units/AOV 等） | `query_sales_metrics`, `query_product_performance`, `compare_sales_period`, `analyze_sales_anomaly`, `calculate_product_health` |
| 库存消耗估计（日均销、可维持天数、预计缺货日等） | `analyze_stockout_risk`, `calculate_restock_recommendation` |

```text
        Sales Calculation Service          Inventory Calculation Service
                 │                                      │
     ┌───────────┼───────────┐              ┌───────────┴───────────┐
     ▼           ▼           ▼              ▼                       ▼
 query_sales  product_perf  anomaly   stockout_risk            restock_rec
```

两 Tool 输出目的不同，但同一输入下基础估计值必须一致。

---

## 4. Tool Classification

| 类型 | 含义 | 典型 | 默认风险 |
|------|------|------|----------|
| **Query** | 查事实 | `get_order`, `get_inventory` | LOW |
| **Analysis** | 算指标 / 诊断（确定性） | `calculate_product_health`, `query_sales_metrics` | LOW |
| **Analysis / Decision Support** | 基于事实+规则给出业务资格判定 | `check_return_eligibility` | MEDIUM |
| **Knowledge** | 检索业务规则与规范 | `search_business_knowledge` | LOW |
| **Recommendation** | 给出建议，不改状态 | `calculate_restock_recommendation` | MEDIUM |
| **Action** | 改变业务状态 | `create_return_request` | HIGH / CRITICAL |

判定规则：

- 只读事实 → Query  
- 基于事实算出指标/诊断但不落库改状态 → Analysis  
- 输出业务资格类结论（eligible 等）→ **Analysis / Decision Support**（便于 Workflow 分支）  
- 检索非结构化/半结构化规则文本 → Knowledge  
- 输出「建议做什么」但不执行 → Recommendation  
- 创建/更新业务实体 → Action  

---

## 5. Tool Metadata Standard

每个 Core Tool 必须具备以下契约字段：

| 字段 | 说明 |
|------|------|
| `tool_id` | 稳定 ID，如 `T-Q-01` |
| `name` | 蛇形命名，如 `search_products` |
| `category` | Query / Analysis / Analysis-DecisionSupport / Knowledge / Recommendation / Action |
| `business_capability` | 对应的业务能力表述 |
| `purpose` | 一句话用途 |
| `roles` | `customer_service` / `operations` / 有条件 |
| `input_schema` | 关键输入；**仅业务键与用户声明，不含可覆盖系统事实的伪造字段** |
| `output_schema` | 关键输出（逻辑 JSON） |
| `data_dependency` | 逻辑实体/字段需求（非 DDL） |
| `knowledge_dependency` | none / optional / required + 类型 |
| `read_only` | true / false |
| `risk_level` | LOW / MEDIUM / HIGH / CRITICAL（Action 可引用 Risk Policy） |
| `requires_approval` | true / false（可由 Risk Policy 确定性推导） |
| `permission_context` | **仅写额外限制**；默认规则见 §5.3 |
| `idempotent` | true / false / conditional |
| `audit_required` | Write/Action 默认 true |
| `validation_rules` | 入参与前置校验 |
| `failure_cases` | 标准失败语义 |
| `scenario_mapping` | 关联 CS/OP ID |
| `v1_in_scope` | true（Core）时详写 |

### 5.1 标准失败语义（全 Tool 共用）

| `error_code` | 含义 | Agent 应做 |
|--------------|------|------------|
| `INVALID_INPUT` | 缺参/格式错误 | 请求补充信息 |
| `NOT_FOUND` | 实体不存在 | 说明未找到，勿编造 |
| `FORBIDDEN` | 超出权限范围 | 说明无权限，勿绕过 |
| `DATA_UNAVAILABLE` | 依赖数据不可用 | 明确不可用，降级或转人工 |
| `RULE_CONFLICT` | 规则冲突/无法判定 | 说明冲突，转人工 |
| `PRECONDITION_FAILED` | 状态不允许 | 说明当前状态与原因 |
| `APPROVAL_REQUIRED` | 缺审批令牌 | 进入审批节点 |
| `DEPENDENCY_ERROR` | 下游失败 | 说明系统问题，勿臆测业务结论 |

### 5.2 标准调用上下文（逻辑）

所有 Tool 调用隐含（或显式传入）：

```json
{
  "user_context": {
    "user_id": "string",
    "role": "customer_service | operations",
    "store_id": "string",
    "permissions": ["..."]
  },
  "request_id": "string"
}
```

Action 另需（在审批通过后执行时）：

```json
{
  "approval": {
    "approver_id": "string",
    "approved_at": "datetime",
    "decision": "approved",
    "comment": "string | null"
  }
}
```

### 5.3 全局默认权限规则（Global Default）

**所有 Tool 默认：**

1. 必须带 `user_context`（`user_id` / `role` / `store_id`）  
2. **默认按 `store_id` 做数据范围过滤**  
3. 按 `role` + `permissions` 做能力鉴权  
4. 客户敏感字段（手机号、详细地址等）**最小必要展示 / 脱敏**  

Tool 规格中的 `permission_context` **只描述额外限制**，不再重复抄写整套默认规则。若未写 `permission_context`，仍适用本默认。

### 5.4 系统事实优先（Anti-Injection）

| 规则 | 说明 |
|------|------|
| 可信事实源 | 订单状态、签收时间、库存、价格、类目等由 Tool/Service 从业务数据源读取 |
| 允许的输入 | 业务键（`order_id`/`sku_id`）、用户声明（`return_reason`）、可选主观描述（`product_condition`） |
| **禁止** | LLM/调用方传入 `delivered_at`、`order_status`、`available_stock` 等并覆盖库内值 |
| 冲突处理 | 若错误附带事实字段 → 忽略或 `INVALID_INPUT`，以系统读取为准 |

### 5.5 Action Risk Policy（参数 → 风险 → 审批）

**所有 Write/Action 默认 `audit_required=true`。**

对 `create_service_ticket` 等风险随类型变化的 Action，必须由确定性策略表决定：

| `ticket_type`（逻辑枚举） | risk_level | requires_approval |
|---------------------------|------------|-------------------|
| `NORMAL` / `FOLLOW_UP` | LOW | false |
| `ESCALATION` | LOW–MEDIUM | false（可配置） |
| `COMPENSATION_REQUEST` | MEDIUM | **true** |
| `REFUND_RELATED` | HIGH | **true** |
| 未知类型 | MEDIUM | **true**（安全默认） |

`create_return_request`：固定 HIGH + approval required + audit true。

---

## 6. Capability Inventory

从 Business Baseline「所需能力」抽取并归一（去重后）。`V1` = Core 必须覆盖；`P2` = Phase2。

### 6.1 客服相关能力

| Cap ID | 业务能力 | 优先 | 归入 Tool |
|--------|----------|------|-----------|
| C-CS-01 | 检索商品 | P0 | `search_products` |
| C-CS-02 | 获取商品详情 | P0 | `get_product_detail` |
| C-CS-03 | 获取规格/变体 | P0 | **并入** `get_product_detail` |
| C-CS-04 | 查询库存 | P0 | `get_inventory` |
| C-CS-05 | 查询商品状态 | P0 | **并入** `get_product_detail` |
| C-CS-06 | 获取订单详情 | P0 | `get_order` |
| C-CS-07 | 获取订单状态 | P0 | **并入** `get_order` |
| C-CS-08 | 获取履约/物流状态 | P0 | `get_shipping_status` |
| C-CS-09 | 分析履约延迟 | P0 | `analyze_fulfillment_delay` |
| C-CS-10 | 获取送达/签收时间 | P0 | **并入** `get_order` / `get_shipping_status` |
| C-CS-11 | 检索售后政策/业务知识 | P0 | `search_business_knowledge` |
| C-CS-12 | 校验退货资格 | P0 | `check_return_eligibility` |
| C-CS-13 | 创建退货申请 | P0 | `create_return_request` |
| C-CS-14 | 创建换货申请 | P0* | Phase2（见 Gaps） |
| C-CS-15 | 创建退款申请 | P0* | Phase2（见 Gaps） |
| C-CS-16 | 创建服务工单 | P1/支撑 | `create_service_ticket` |
| C-CS-17 | 检索客户反馈 | P1/支撑 | `search_customer_feedback` |
| C-CS-18 | 分析客户反馈 | P1/支撑 | `analyze_customer_feedback` |
| C-CS-19 | 查询价格/促销/算促后价 | P1 | Phase2 |
| C-CS-20 | 商品对比与推荐排序 | P1 | Phase2 |
| C-CS-21 | 取消/更新订单 | P2 | Phase2 |
| C-CS-22 | 升级转人工 | P2 | Phase2（工单可部分替代） |

\* Business 写 CS-09 含换货/退款，但同时约定 V1「至少打通退货申请」→ 换货/退款作 Phase2，记入 Gaps 说明。

### 6.2 运营相关能力

| Cap ID | 业务能力 | 优先 | 归入 Tool |
|--------|----------|------|-----------|
| C-OP-01 | 查询销售指标 | P0 | `query_sales_metrics` |
| C-OP-02 | 周期对比 | P0 | `compare_sales_period` |
| C-OP-03 | 查询商品表现 | P0 | `query_product_performance` |
| C-OP-04 | 分析滞销 | P0 | **并入** `query_product_performance`（模式/排序） |
| C-OP-05 | 计算商品健康度 | P0 | `calculate_product_health` |
| C-OP-06 | 计算库存天数 | P0 | **内化**于缺货/补货分析 Service |
| C-OP-07 | 计算缺货风险 | P0 | `analyze_stockout_risk` |
| C-OP-08 | 估计需求并计算补货建议 | P0 | `calculate_restock_recommendation` |
| C-OP-09 | 获取采购周期 | P0 | **内化**（Store 配置，非独立 Tool） |
| C-OP-10 | 销售异常分析（含判定） | P0 | `analyze_sales_anomaly` |
| C-OP-11 | 查询价格历史 | P0 支撑 | `get_price_history` |
| C-OP-12 | 查询/分析退货（支撑异常） | P0 支撑 | **并入** `query_product_performance` / `analyze_sales_anomaly` |
| C-OP-13 | 分析商品风险 | P0 支撑 | **并入** `calculate_product_health` 输出 |
| C-OP-14 | 积压/周转/清仓分析 | P1 | Phase2 |
| C-OP-15 | 调价/促销/生命周期/报告等 | P1–P2 | Phase2 |

### 6.3 明确不做 Tool 的能力

| 能力 | 原因 |
|------|------|
| 生成客服回复草稿 | Agent 生成能力 |
| 生成经营报告自然语言正文 | Agent 生成；可组合 Analysis Tool 取数 |
| 情绪识别（深度模型） | 业务 P2；非 V1 Core |
| LLM 自行计算销量/健康分 | 违反确定性计算原则 |

---

## 7. Tool Boundary Decisions

| 决策 | 结论 | 理由 |
|------|------|------|
| `get_product_variant` / `get_product_status` | 并入 `get_product_detail` | 减少碎 Tool；详情一次返回 |
| `get_order_status` | 并入 `get_order` | 状态是订单事实的一部分 |
| `get_inventory_by_product` | `get_inventory` 支持 `product_id` 或 `sku_id` | 同一查询能力 |
| `calculate_inventory_days` / `get_purchase_cycle` | 不暴露给 LLM | 内化于 Analysis/Recommendation + Inventory Calculation Service |
| Knowledge 多入口 K02–K04 | V1 仅 `search_business_knowledge` + `knowledge_type` | 避免近义 Tool |
| `create_exchange/refund_request` | Phase2 | 遵守 V1「先打通退货」 |
| `batch_offline_products` / `update_product_price` | 不做 V1 Action | 业务明确高风险延后 |
| `manage_order` 类 | **禁止** | 超级 Tool |
| `query_product_performance` | **商品表现聚合查询** | `mode` 仅为查询视角（top/slow_moving/all），**不**承担健康判定、清仓决策；决策类见 health / disposal（Phase2） |
| 销售/库存基础计算 | 统一 Calculation Service | 防多 Tool 指标漂移 |

---

## 8. Core Tool Inventory（V1）

V1 Core 共 **20** 个：

| tool_id | name | category | risk | approval | 主角色 |
|---------|------|----------|------|----------|--------|
| T-Q-01 | `search_products` | Query | LOW | No | CS + OP |
| T-Q-02 | `get_product_detail` | Query | LOW | No | CS + OP |
| T-Q-03 | `get_inventory` | Query | LOW | No | CS + OP |
| T-Q-04 | `get_order` | Query | LOW | No | CS + OP△ |
| T-Q-05 | `get_shipping_status` | Query | LOW | No | CS + OP△ |
| T-Q-06 | `search_customer_feedback` | Query | LOW | No | CS + OP |
| T-Q-07 | `get_price_history` | Query | LOW | No | OP + CS△ |
| T-A-01 | `analyze_fulfillment_delay` | Analysis | LOW | No | CS |
| T-A-02 | `query_sales_metrics` | Analysis | LOW | No | OP |
| T-A-03 | `compare_sales_period` | Analysis | LOW | No | OP |
| T-A-04 | `query_product_performance` | Analysis | LOW | No | OP |
| T-A-05 | `calculate_product_health` | Analysis | LOW | No | OP |
| T-A-06 | `analyze_sales_anomaly` | Analysis | LOW | No | OP |
| T-A-07 | `analyze_stockout_risk` | Analysis | LOW | No | OP |
| T-A-08 | `analyze_customer_feedback` | Analysis | LOW | No | CS + OP |
| T-A-09 | `check_return_eligibility` | Analysis / Decision Support | MEDIUM | No* | CS |
| T-K-01 | `search_business_knowledge` | Knowledge | LOW | No | CS + OP |
| T-R-01 | `calculate_restock_recommendation` | Recommendation | MEDIUM | No* | OP |
| T-X-01 | `create_return_request` | Action | HIGH | **Yes** | CS |
| T-X-02 | `create_service_ticket` | Action | 见 §5.5 Risk Policy | 见 §5.5 | CS + OP |

\* 判断/建议本身不审批；**据此执行的 Action** 要审批。  

**说明**：Core Tool **必须由至少一个 P0（或其 V1 最低合同）支撑**；同时**允许服务 P1**（如 `search_products` 亦可用于 CS-04），不为 P1 复制 Tool。

### 8.1 Phase2 候选（不详写契约）

`search_orders`, `get_customer_profile`, `get_return_request`, `create_exchange_request`, `create_refund_request`, `create_restock_request`, `analyze_overstock_risk`, `analyze_price_recommendation`, `get_campaign_history`, `analyze_campaign_performance`, `find_promotion_candidates`, `create_campaign`, `analyze_product_lifecycle`, `generate_product_disposal_recommendation`, `escalate_to_human`, `cancel_order`, `update_order`, `update_product_price`（若未来开放）等。

---

## 9. Tool Detailed Specifications（Core）

以下为 V1 Core 完整契约。`input`/`output` 为**逻辑 Schema**，非最终 API 代码。

---

### T-Q-01 `search_products`

| 字段 | 内容 |
|------|------|
| category | Query |
| business_capability | 检索商品 |
| purpose | 按关键词/类目/品牌/价格等返回候选商品列表 |
| roles | customer_service, operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | none |
| permission_context | （默认 §5.3）；额外：仅当前店铺商品 |
| scenario_mapping | CS-01, CS-02, CS-04(P1), OP-* 商品定位 |

**input**

```json
{
  "keyword": "string?",
  "category": "string?",
  "brand": "string?",
  "min_price": "number?",
  "max_price": "number?",
  "status": "active|all?",
  "limit": "number?"
}
```

**output**

```json
{
  "products": [
    {
      "product_id": "string",
      "name": "string",
      "brand": "string?",
      "category": "string?",
      "price": "number?",
      "status": "string"
    }
  ]
}
```

**data_dependency**：商品、类目、（可选）品牌/价格/状态。  
**validation**：至少提供一个检索条件或 keyword；`limit` 有上限。  
**failure_cases**：`INVALID_INPUT`, `FORBIDDEN`, `DATA_UNAVAILABLE`。

---

### T-Q-02 `get_product_detail`

| 字段 | 内容 |
|------|------|
| category | Query |
| business_capability | 获取商品详情（含规格/变体与销售状态） |
| purpose | 返回单个商品的完整事实视图 |
| roles | customer_service, operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | optional（说明书/FAQ 走 Knowledge，不在本 Tool 内） |
| permission_context | （默认 §5.3） |
| scenario_mapping | CS-01, CS-02, CS-08 |

**input**：`{ "product_id": "string" }` 或可解析的业务编码。  

**output（逻辑）**：`product_id`, `name`, `brand`, `category`, `description`, `status`, `specifications`, `variants[]`（含 sku_id、属性、价格、状态）, `launch_date?`。  

**data_dependency**：商品 SPU、SKU/变体、状态、上架/上市时间（供后续生命周期；本 Tool 尽量返回）。  
**failure_cases**：`NOT_FOUND`, `FORBIDDEN`, `DATA_UNAVAILABLE`。

---

### T-Q-03 `get_inventory`

| 字段 | 内容 |
|------|------|
| category | Query |
| business_capability | 查询库存 |
| purpose | 按 SKU 或商品查询可用/预留等库存事实 |
| roles | customer_service, operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | none |
| scenario_mapping | CS-02, OP-04, OP-05, OP-08 |

**input**

```json
{
  "sku_id": "string?",
  "product_id": "string?",
  "warehouse_id": "string?"
}
```

至少 `sku_id` 或 `product_id` 之一。

**output**：`sku_id`, `product_id`, `total_stock?`, `reserved_stock?`, `available_stock`, `safety_stock?`, `inventory_status`, 多 SKU 时为列表。  

**data_dependency**：库存、SKU、（可选）仓库。  
**failure_cases**：`INVALID_INPUT`, `NOT_FOUND`, `DATA_UNAVAILABLE`, `FORBIDDEN`。

---

### T-Q-04 `get_order`

| 字段 | 内容 |
|------|------|
| category | Query |
| business_capability | 获取订单详情与状态（含关键时间事实） |
| purpose | 返回订单头、明细、状态及送达/签收等时间字段（若有） |
| roles | customer_service；operations 有条件 |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| permission_context | （默认 §5.3）；额外：客户敏感字段最小必要/脱敏 |
| scenario_mapping | CS-05, CS-06, CS-08, CS-09 |

**input**：`{ "order_id": "string" }` 或 `order_no`。  

**output**：`order_id`, `order_no`, `customer_id`（可脱敏关联）, `status`, `payment_status?`, `shipping_status?`, `amounts`, `items[]`, `created_at`, `paid_at?`, `shipped_at?`, `delivered_at?` / `signed_at?`。  

**data_dependency**：订单、订单明细、商品/SKU 引用、关键业务时间戳。  
**failure_cases**：`NOT_FOUND`, `FORBIDDEN`, `DATA_UNAVAILABLE`。  
**validation**：无订单标识 → `INVALID_INPUT`（触发 Agent 向用户要单号）。

---

### T-Q-05 `get_shipping_status`

| 字段 | 内容 |
|------|------|
| category | Query |
| business_capability | 获取物流/履约状态与轨迹 |
| purpose | 返回承运商、运单、状态、事件轨迹 |
| roles | customer_service；operations 有条件 |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| scenario_mapping | CS-05(可选), CS-06 |

**input**：`{ "order_id": "string" }` 或 `shipment_id` / `tracking_no`。  

**output**：`carrier`, `tracking_number`, `status`, `last_update`, `estimated_delivery_at?`, `delivered_at?`, `events[]`。  

**data_dependency**：发货单、物流事件（可为模拟数据源）。  
**failure_cases**：`NOT_FOUND`, `DATA_UNAVAILABLE`, `FORBIDDEN`。

---

### T-Q-06 `search_customer_feedback`

| 字段 | 内容 |
|------|------|
| category | Query |
| business_capability | 检索客户反馈 |
| purpose | 按商品/时间/类型等检索反馈事实列表与基础过滤 |
| roles | customer_service, operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| permission_context | （默认 §5.3）；额外：反馈正文按角色最小必要 |
| scenario_mapping | CS-12(P1), OP-08, OP-13(P1) |

**input**：`product_id?`, `start_date?`, `end_date?`, `issue_type?`, `sentiment?`, `limit?`。  

**output**：`items[]`（id, product_id, type, category?, sentiment?, content_summary, created_at）, `total`。  

**data_dependency**：客户反馈/评价等事实（含 product_id、时间、分类字段——Database 需满足）。  

---

### T-Q-07 `get_price_history`

| 字段 | 内容 |
|------|------|
| category | Query |
| business_capability | 查询价格历史 |
| purpose | 返回商品/SKU 历史价格变更事实 |
| roles | operations；customer_service 有条件 |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| scenario_mapping | OP-08；OP-09(P1) |

**input**：`product_id` / `sku_id`, `start_date?`, `end_date?`。  

**output**：`history[]`（old_price, new_price, effective_at, change_reason?）。  

**data_dependency**：价格历史实体。

---

### T-A-01 `analyze_fulfillment_delay`

| 字段 | 内容 |
|------|------|
| category | Analysis |
| business_capability | 分析履约/发货是否延迟 |
| purpose | 基于订单时效事实与（可选）规则，判定是否延迟及严重度 |
| roles | customer_service |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | optional（履约时效政策） |
| scenario_mapping | CS-06 |

**input**：`{ "order_id": "string" }`。  

**output**：`is_delayed`, `delay_hours?`, `expected_ship_or_deliver_time?`, `actual_time?`, `severity`（none/low/medium/high）, `basis`。  

**data_dependency**：订单承诺/实际发货或送达时间、物流状态。  
**validation**：缺时效字段 → `DATA_UNAVAILABLE` 或降级输出「无法判定」，**不得**由模型猜延迟。  
**failure_cases**：含 `RULE_CONFLICT`, `DATA_UNAVAILABLE`。

---

### T-A-02 `query_sales_metrics`

| 字段 | 内容 |
|------|------|
| category | Analysis |
| business_capability | 查询销售指标 |
| purpose | 在时间窗（及可选商品范围）内返回 GMV/订单量/销量/AOV 等；**计算委托 Sales Calculation Service** |
| roles | operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| permission_context | （默认 §5.3） |
| scenario_mapping | OP-01, OP-04, OP-05, OP-08 |

**input**：`start_date`, `end_date`, `product_id?`, `category_id?`。  

**output**：`gmv`, `orders`, `units`, `aov`, `period`。  

**data_dependency**：订单、订单明细。  
**原则**：指标由确定性计算产生；与其他销售类 Tool **共用** Sales Calculation Service，禁止私有公式漂移。

---

### T-A-03 `compare_sales_period`

| 字段 | 内容 |
|------|------|
| category | Analysis |
| business_capability | 销售周期对比 |
| purpose | 对比两段时期的销售指标与变化率 |
| roles | operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| scenario_mapping | OP-01, OP-08 |

**input**：`current_start`, `current_end`, `previous_start?`, `previous_end?` 或 `compare_mode`（wow/mom/yoy）。  

**output**：`current`, `previous`, `change_rate`, `metrics_breakdown?`。  

---

### T-A-04 `query_product_performance`

| 字段 | 内容 |
|------|------|
| category | Analysis |
| business_capability | 查询商品表现（聚合事实，含视角切换） |
| purpose | **提供商品表现聚合事实**（销量/销售额/增长/库存/退货率等）；`mode` 只切换排序/过滤视角，**不是**滞销决策、健康判定或清仓决策 Tool |
| roles | operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | optional（慢销阈值仅用于过滤，不作处置决策） |
| permission_context | （默认 §5.3） |
| scenario_mapping | OP-02(P1), OP-03, OP-08 |

**input**：`start_date`, `end_date`, `mode`=`top|slow_moving|all`, `limit?`, `category_id?`。  

**output**：`products[]`（product_id, sales, gmv, growth_rate?, inventory?, return_rate?, rank_hint?）。  

**边界**：不输出「应清仓/应下架」类决策；该类属 Recommendation/Phase2。销售基础量来自 Sales Calculation Service。  
**data_dependency**：订单明细、库存、退货（若有）。

---

### T-A-05 `calculate_product_health`

| 字段 | 内容 |
|------|------|
| category | Analysis |
| business_capability | 计算商品健康度 |
| purpose | 按可配置权重计算分维分数与总分，并标注数据完整度 |
| roles | operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | required/optional（评分标准 Store 规则） |
| scenario_mapping | OP-07, OP-03 |

**input**：`product_id`, `evaluation_period_days?`。  

**output**

```json
{
  "score": 68,
  "level": "attention",
  "dimensions": {},
  "data_completeness": { "used": 8, "configured": 10, "missing": ["traffic", "conversion"] },
  "risk_factors": [],
  "basis": "string"
}
```

**data_dependency**：销售、库存、利润、退货、反馈等核心维；流量/转化为可选。  
**原则**：分数确定性计算；缺失维必须出现在 `missing`；禁止模型直接打分。

---

### T-A-06 `analyze_sales_anomaly`

| 字段 | 内容 |
|------|------|
| category | Analysis |
| business_capability | 销售异常判定与诊断支持 |
| purpose | 先按可配置基线/阈值判定是否异常，再汇总多事实证据供归因 |
| roles | operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | optional |
| scenario_mapping | OP-08 |

**input**：`product_id?`, `period`, `baseline_policy?`。  

**output**：`is_anomaly`, `anomaly_basis`（基线/阈值/偏差）, `sales_change?`, `evidence[]`, `possible_causes[]`（含 evidence，由规则/启发式排序，**不是**模型空想）。  

**data_dependency**：销售、库存、价格历史、退货、反馈、活动（可选流量）。  
**原则**：`is_anomaly` 不得由 LLM 主观认定；无流量时仅基于已有事实证据。

---

### T-A-07 `analyze_stockout_risk`

| 字段 | 内容 |
|------|------|
| category | Analysis |
| business_capability | 计算缺货风险 |
| purpose | 基于库存与历史销量估计消耗，输出缺货风险清单 |
| roles | operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | optional（库存政策） |
| permission_context | （默认 §5.3） |
| scenario_mapping | OP-04 |

**input**：`forecast_days`（或 `horizon_days`）, `product_ids?`, `category_id?`。  

**output**：`high_risk_products[]`（product/sku, current_stock, avg_daily_sales_est, days_of_inventory, estimated_stockout_date?, risk_level）。  

**data_dependency**：库存、销售；安全库存/补货周期配置。  
**原则**：V1 为历史销量估计，非完整 forecasting；**日均销/可维持天数/预计缺货日**必须来自 **Inventory Calculation Service**，与 `calculate_restock_recommendation` 共用，禁止两套算法。

---

### T-A-08 `analyze_customer_feedback`

| 字段 | 内容 |
|------|------|
| category | Analysis |
| business_capability | 分析客户反馈（统计/聚合） |
| purpose | 对反馈做分类计数与 Top issues；可含受控分类结果 |
| roles | customer_service, operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| scenario_mapping | CS-12(P1), OP-08, OP-13(P1) |

**input**：同检索过滤条件 + `product_id?` 时间窗。  

**output**：`total_feedback`, `top_issues[]`（issue, count, ratio?）, `samples?`。  

**原则**：与 CS-12/OP-13 共享反馈事实；**不**要求先落「CS-12 分析结果表」。

---

### T-A-09 `check_return_eligibility`

| 字段 | 内容 |
|------|------|
| category | **Analysis / Decision Support** |
| business_capability | 校验退货资格 |
| purpose | 基于系统读取的订单/商品事实 + 业务规则，确定性输出资格三态结论 |
| roles | customer_service；operations 有条件 |
| read_only | true |
| risk_level | MEDIUM |
| requires_approval | false（**不执行**售后；最终批准/拒绝在 Action 前由审批人确认） |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | **required**（售后/法定/店铺规则） |
| permission_context | （默认 §5.3）；额外：客服售后读权限 |
| scenario_mapping | CS-08, CS-09 |

**input（仅键与用户声明；禁止注入系统事实）**

```json
{
  "order_id": "string",
  "item_id": "string?",
  "return_reason": "string",
  "product_condition": "string?"
}
```

**禁止作为可信输入覆盖系统库**：`delivered_at` / `signed_at` / `order_status` / `category` / `within_window` 等。此类事实由 Tool 按 `order_id`（及 item）自行读取（见 §5.4）。

**output（三态决策）**

```json
{
  "decision": "eligible | ineligible | undetermined",
  "reason_code": "WITHIN_RETURN_WINDOW | RETURN_WINDOW_EXPIRED | INSUFFICIENT_FACTS | RULE_CONFLICT | ...",
  "explanation": "string",
  "rule_sources": [{ "layer": "legal|platform|store", "ref": "string" }],
  "required_evidence": [],
  "missing_facts": [],
  "facts_used": {
    "order_status": "string?",
    "delivered_or_signed_at": "datetime?",
    "product_category": "string?"
  }
}
```

| `decision` | 含义 |
|------------|------|
| `eligible` | 基于已有事实与规则，**确定符合** |
| `ineligible` | 基于已有事实与规则，**确定不符合** |
| `undetermined` | 事实不足或规则冲突，**无法判断**（≠ 不能退） |

**data_dependency**：订单、商品/类目、送达/签收时间等（系统读取）。  
**failure_cases**：缺关键事实 → 优先返回 `decision=undetermined` + `missing_facts`，或 `DATA_UNAVAILABLE`；**不得**把「信息不足」编码为 `ineligible`。规则冲突 → `undetermined` 或 `RULE_CONFLICT`。  
**validation**：遵守 §5.4 系统事实优先。

---

### T-K-01 `search_business_knowledge`

| 字段 | 内容 |
|------|------|
| category | Knowledge |
| business_capability | 检索业务知识/规则 |
| purpose | 统一知识检索入口（售后/客服/库存/运营/物流等） |
| roles | customer_service, operations |
| read_only | true |
| risk_level | LOW |
| requires_approval | false |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | required（本 Tool 即知识入口） |
| scenario_mapping | CS-06, CS-08, CS-09, CS-10(P1), OP-05, OP-07 等 |

**input**

```json
{
  "query": "string",
  "knowledge_type": "after_sales|customer_service|inventory|operations|logistics|pricing|promotion|general",
  "platform": "default",
  "layer": "legal|platform|store|any?"
}
```

**output**：`results[]`（content, source, section?, layer?, score?）。  

**原则**：返回带层级来源，便于解释「法定 / 平台 / 店铺」。实现（向量库等）不在本文锁定。

---

### T-R-01 `calculate_restock_recommendation`

| 字段 | 内容 |
|------|------|
| category | Recommendation |
| business_capability | 计算补货建议（历史销量需求估计） |
| purpose | 输出建议补货量与原因；**不创建采购单** |
| roles | operations |
| read_only | true |
| risk_level | MEDIUM |
| requires_approval | false（建议本身）；若后续 `create_restock_request` 则要审批 |
| idempotent | true |
| audit_required | false |
| knowledge_dependency | optional/required（库存/采购政策） |
| permission_context | （默认 §5.3） |
| scenario_mapping | OP-05 |

**input**：`product_id` / `sku_id`, `horizon_days?`。  

**output**：`recommended_quantity`, `current_stock`, `avg_daily_sales_est`, `safety_stock?`, `lead_time_days?`, `estimated_stockout_date?`, `reasons[]`, `method`: `"historical_sales_estimate"`。  

**原则**：标注方法为历史销量估计；**avg_daily_sales_est / estimated_stockout_date 等与 `analyze_stockout_risk` 共用 Inventory Calculation Service**。  
**data_dependency**：库存、销售、lead time/安全库存配置。

---

### T-X-01 `create_return_request`

| 字段 | 内容 |
|------|------|
| category | Action |
| business_capability | 创建退货申请 |
| purpose | 在审批通过后创建退货/售后申请单据 |
| roles | customer_service |
| read_only | false |
| risk_level | HIGH |
| requires_approval | **true** |
| idempotent | conditional（必须 `request_id` / idempotency_key） |
| audit_required | **true** |
| knowledge_dependency | none（前置流程需要） |
| permission_context | （默认 §5.3）；额外：客服写售后 + 审批人必填（§5.2） |
| scenario_mapping | CS-09 |

**input**

```json
{
  "order_id": "string",
  "item_id": "string",
  "quantity": "integer",
  "reason": "string",
  "eligibility_ref": "string?",
  "request_id": "string",
  "approval": { "approver_id": "string", "approved_at": "datetime", "decision": "approved", "comment": "string?" }
}
```

**V1（RETURN）必填**：`order_id`、`item_id`（对应 `order_item_id`）、`quantity`（`> 0` 且 ≤ 该行可退数量）、`request_id`、`approval`。  
**output**：`return_request_id`, `status`, `created_at`。  

**validation**：无 approval → `APPROVAL_REQUIRED`；缺 `item_id`/`quantity` 或 `quantity` 非法 → `VALIDATION_ERROR`；资格未通过且无强制标记 → `PRECONDITION_FAILED`；超可退数量 → `PRECONDITION_FAILED`。  
**data_dependency**：售后单（含 `order_item_id` + `quantity`）、审计、幂等键、审批元数据。  
**audit**：记录操作人、审批人、时间、对象、参数（含 quantity）、结果。  
**failure_cases**：含重复提交时返回同一业务单（幂等）。

---

### T-X-02 `create_service_ticket`

| 字段 | 内容 |
|------|------|
| category | Action |
| business_capability | 创建服务工单 |
| purpose | 创建客服/运营跟进工单（投诉、跟进、升级摘要载体） |
| roles | customer_service, operations |
| read_only | false |
| risk_level | **由 §5.5 Risk Policy 按 `ticket_type` 确定性映射** |
| requires_approval | **由 §5.5 映射** |
| idempotent | conditional（`request_id`） |
| audit_required | **true**（Write/Action 默认） |
| permission_context | （默认 §5.3） |
| scenario_mapping | CS-09 支撑, CS-10(P1), CS-11(P2) |

**input**：`ticket_type`（`NORMAL`/`FOLLOW_UP`/`ESCALATION`/`COMPENSATION_REQUEST`/`REFUND_RELATED`）, `order_id?`, `customer_id?`, `product_id?`, `priority?`, `summary`, `request_id`；若 Policy 要求审批则附 `approval`。  

**output**：`ticket_id`, `status`, `created_at`, `applied_risk_level`, `approval_applied`。  

**data_dependency**：工单实体（Database 需提供；若与售后单合并须在 DB 设计说明）。  
**validation**：未知 `ticket_type` → 按 §5.5 安全默认（MEDIUM + 需审批）。

---

## 10. Scenario → Capability → Tool 覆盖矩阵

### 10.0 P0 覆盖语义（重要）

> **「P0 场景完整覆盖」≠「P0 场景全部业务语义一次性实现」。**

验收口径：

- **必须覆盖**：Business Baseline 为该场景规定的 **V1 最低可交付能力合同**  
- **允许延后**：同场景中明确 Phase2 / Gaps 的能力（如 CS-09 换货/退款）  

因此 CS-09 的 P0 合同 = **退货申请链路打通**；换货/退款见 Gap-01，不视为「P0 矩阵失败」。

### 10.1 P0 全覆盖（按 V1 最低合同）

#### 客服 P0

| 场景 | 所需能力 | Tool | 覆盖 |
|------|----------|------|------|
| CS-01 | 检索商品 | T-Q-01 `search_products` | ✅ |
| CS-01 | 获取商品详情 | T-Q-02 `get_product_detail` | ✅ |
| CS-01 | 获取规格/变体 | T-Q-02（并入） | ✅ |
| CS-02 | 检索商品 | T-Q-01 | ✅ |
| CS-02 | 查询库存 | T-Q-03 `get_inventory` | ✅ |
| CS-02 | 查询商品状态 | T-Q-02（并入） | ✅ |
| CS-05 | 获取订单详情 | T-Q-04 `get_order` | ✅ |
| CS-05 | 获取订单状态 | T-Q-04（并入） | ✅ |
| CS-05 | 获取履约状态 | T-Q-05 `get_shipping_status` | ✅ |
| CS-06 | 获取订单 | T-Q-04 | ✅ |
| CS-06 | 获取物流状态 | T-Q-05 | ✅ |
| CS-06 | 分析履约延迟 | T-A-01 `analyze_fulfillment_delay` | ✅ |
| CS-06 | 履约规则（知识） | T-K-01 | ✅ |
| CS-08 | 获取订单 | T-Q-04 | ✅ |
| CS-08 | 获取商品详情 | T-Q-02 | ✅ |
| CS-08 | 获取送达/签收时间 | T-Q-04 / T-Q-05 | ✅ |
| CS-08 | 校验退货资格 | T-A-09 `check_return_eligibility` | ✅ |
| CS-08 | 检索售后政策 | T-K-01 | ✅ |
| CS-09 | 创建退货申请（V1 最低合同） | T-X-01 `create_return_request` | ✅ |
| CS-09 | 创建换货/退款申请 | — | ⚠️ 非 V1 最低合同 / Gap-01 |
| CS-09 | 工单支撑 | T-X-02 | ✅ |

#### 运营 P0

| 场景 | 所需能力 | Tool | 覆盖 |
|------|----------|------|------|
| OP-01 | 查询销售指标 | T-A-02 `query_sales_metrics` | ✅ |
| OP-01 | 周期对比 | T-A-03 `compare_sales_period` | ✅ |
| OP-03 | 查询商品表现/滞销 | T-A-04 `query_product_performance` | ✅ |
| OP-03 | 健康度（可复用） | T-A-05 | ✅ |
| OP-04 | 查询库存 | T-Q-03 | ✅ |
| OP-04 | 查询销售 | T-A-02 | ✅ |
| OP-04 | 缺货风险 | T-A-07 `analyze_stockout_risk` | ✅ |
| OP-05 | 库存/销售 | T-Q-03, T-A-02 | ✅ |
| OP-05 | 补货建议 | T-R-01 `calculate_restock_recommendation` | ✅ |
| OP-05 | 采购周期 | 内化配置 | ✅ |
| OP-07 | 商品健康度 | T-A-05 `calculate_product_health` | ✅ |
| OP-07 | 知识/评分规则 | T-K-01 | ✅ |
| OP-08 | 销售/对比 | T-A-02, T-A-03 | ✅ |
| OP-08 | 库存 | T-Q-03 | ✅ |
| OP-08 | 价格历史 | T-Q-07 | ✅ |
| OP-08 | 反馈 | T-Q-06, T-A-08 | ✅ |
| OP-08 | 异常分析 | T-A-06 `analyze_sales_anomaly` | ✅ |

### 10.2 示例组合（非 Workflow 详设）

**CS-08 退货资格**

```text
get_order → get_product_detail → search_business_knowledge → check_return_eligibility
→（LLM 解释 + 草稿）→ 若执行则审批 → create_return_request
```

**OP-08 销量异常**

```text
query_sales_metrics → compare_sales_period → get_inventory → get_price_history
→ search_customer_feedback / analyze_customer_feedback → analyze_sales_anomaly
→（LLM 组织诊断叙述）
```

**OP-05 补货**

```text
get_inventory → query_sales_metrics → analyze_stockout_risk
→ calculate_restock_recommendation
（后两者共用 Inventory Calculation Service）
→（审批人确认；create_restock_request 为 Phase2）
```

---

## 11. Tool → Data Dependency（逻辑，非 DDL）

| 逻辑实体/需求 | 主要 Tool | 备注 |
|---------------|-----------|------|
| Product / Category | T-Q-01, T-Q-02 | 含 status、launch/上架时间 |
| ProductVariant/SKU | T-Q-02, T-Q-03 | |
| Inventory | T-Q-03, T-A-07, T-R-01 | available/reserved/safety |
| Order / OrderItem | T-Q-04, T-A-02… | 含 delivered/signed 时间 |
| Shipment / Tracking events | T-Q-05, T-A-01 | 可模拟 |
| Return / After-sales request | T-X-01, T-A-09 | |
| Customer feedback / Review | T-Q-06, T-A-08 | product_id, time, category |
| Price history | T-Q-07 | |
| Service ticket | T-X-02 | 可独立或并入售后域 |
| Sales aggregates | 由 Order 计算 | 不必先建指标表 |
| Store config（安全库存、lead time、异常阈值、健康分权重） | T-A-05/06/07, T-R-01 | 配置源由 DB/配置设计定 |
| Knowledge docs（分层） | T-K-01 | Knowledge Design |
| Audit log（逻辑） | T-X-* | 原则必有；表形态后定 |

---

## 12. Risk / Approval / Audit Mapping

| Tool | risk | approval | audit |
|------|------|----------|-------|
| 所有 Query / Knowledge | LOW | No | No |
| Analysis（普通） | LOW | No | No |
| `check_return_eligibility` | MEDIUM | No（不改状态） | No |
| Recommendation | MEDIUM | No（建议） | No |
| **所有 Action（默认）** | 见各 Tool / §5.5 | 见各 Tool / §5.5 | **Yes** |
| `create_service_ticket` | §5.5 按 `ticket_type` | §5.5 | **Yes** |
| `create_return_request` | HIGH | **Yes** | **Yes** |

工作流侧（Workflow Design）应根据 `requires_approval=true` 插入 Human Approval 节点；未带 approval 的 Action 调用必须失败。  
资格 Tool 返回 `undetermined` 时，应走「补充信息 / 转人工」，不得当作 `ineligible`。

---

## 13. Permission Context Requirements

| 要求 | 说明 |
|------|------|
| 全局默认 | 见 **§5.3**：`user_context` + store scope + 角色鉴权 + 敏感字段最小必要 |
| Tool 附加 | 各 Tool 的 `permission_context` **只写额外限制** |
| 客服 | 订单/客户/售后为主；敏感字段脱敏 |
| 运营 | 销售/库存/商品分析为主；跨客明细按最小必要 |
| 审批人 | Action 执行时校验 `approver_id`（V1 可模拟） |

完整 RBAC 矩阵不在本文展开（与 Business 约定一致）。

---

## 14. Error / Failure Contract

见 §5.1。补充约定：

1. Tool 失败时返回结构化 `error_code` + `message` + `missing_fields?`，禁止用「成功假数据」吞掉失败。  
2. Agent 收到 `DATA_UNAVAILABLE` / `NOT_FOUND` / `FORBIDDEN` 时，遵守业务 2.6：说明、补充、降级或转人工。  
3. `check_return_eligibility`：事实不足 → `decision=undetermined`（或等价错误），**不得**将不足编码为 `ineligible`，**不得**默认 `eligible`。  
4. 违反 §5.4（注入系统事实）→ `INVALID_INPUT` 或忽略注入字段。

---

## 15. Tool Composition Rules

| 规则 | 说明 |
|------|------|
| 先事实后规则 | 资格类：先 Query，再 Knowledge，再 Decision Support |
| 先建议后动作 | Recommendation/Eligibility → 审批 → Action |
| 禁止一工具打通 | 不得用单一 Tool 串联查+判+写 |
| 草稿在图外 | 回复草稿在 Agent 节点生成，不封装为 Tool |
| 复用分析 | OP-03/07/08 共用 performance/health/anomaly；计算走 Calculation Service |
| 复用库存估计 | stockout 与 restock 共用 Inventory Calculation Service |

节点编排细节留给 Workflow Design。

---

## 16. Open Gaps（不得自行改业务）

| Gap ID | 描述 | 建议处理 |
|--------|------|----------|
| Gap-01 | CS-09 文案含换货/退款；V1 最低合同仅退货申请 | **不视为 P0 覆盖失败**；换货/退款 Phase2。若要求 P0 必须含退款，回 Business Baseline |
| Gap-02 | `create_restock_request` 未进 Core | OP-05 V1 以建议+人工确认为主；执行 Action 为 Phase2 |
| Gap-03 | 流量/转化实体未在能力层保证 | 已由业务降级约定；health/anomaly 标注完整度 |
| Gap-04 | ~~工单与售后是否同表~~ | **已关闭**：Database V1.1 已分表（`after_sales_requests` / `service_tickets`）；契约保持 `create_service_ticket` 独立 |
| Gap-05 | 详细权限矩阵未建 | 符合基线；§5.3 已给默认规则 |
| Gap-06 | `escalate_to_human` 无独立 Tool | P2；V1 用工单+人工流程表达 |

---

## 17. V1 Scope & Non-Goals

### In Scope

- 20 个 Core Tool 契约（V1.1 **不扩充数量**）  
- P0 场景按 **V1 最低合同** 的 Capability → Tool 覆盖  
- Core Tool 可由 P0 支撑并**顺带服务 P1**  
- 风险/审批/审计/失败/默认权限/系统事实优先/计算复用落地到契约  

### Non-Goals

- 数据库 DDL / 库产品选型  
- 向量库与 Embedding 选型  
- LangGraph 状态机详设  
- 完整 RBAC 产品  
- Phase2 Tool 详规  
- 批量改价/下架等禁止类 Action  
- 将「信息不足」实现为「确定不可退」  

---

## 18. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1 | 2026-09-11 | 首版 Capability Contract；20 Core Tools；P0 矩阵；Gaps |
| V1.1 | 2026-09-11 | 定向小修：资格三态；系统事实优先；全局权限默认；Action Risk Policy；Calculation Service 复用；performance 边界；P0=最低合同语义；§12–18 收尾对齐 |
| V1.1 Frozen | 2026-09-12 | 正式冻结；T-X-01 补齐 `quantity` + RETURN 行项目必填；Gap-04 关闭（与 DB 分表对齐） |

---

## 附录 A — 审查清单（供人工验收）

1. 是否存在「场景有需求但无 Tool」？（按 V1 最低合同；Gap-01 除外）  
2. 是否存在「无场景支撑的 Tool」？  
3. 是否存在职责过大的超级 Tool？  
4. 风险 / 审批 / 审计边界是否与业务原则一致？  
5. 是否锁定了 MySQL/PostgreSQL/具体向量库？应为否  
6. 是否把回复草稿做成了 Tool？应为否  
7. Open Gaps 是否诚实、未偷改业务？  
8. `check_return_eligibility` 是否为三态且禁止事实注入？  
9. 销售/库存公共计算是否声明 Calculation Service 复用？  

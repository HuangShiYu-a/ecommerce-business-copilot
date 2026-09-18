# E-commerce Business Copilot — Knowledge Seed 元数据契约 V1.0（K3）

> 文档性质：**Knowledge 轨元数据契约**——定义 seed 元数据的字段、取值与约定；是 S3.5 导入器与 S4 检索侧的输入契约。**不**含正文内容（正文属 K4/K6）  
> 版本：**V1.0**  
> 状态：**Draft**（Knowledge 窗口产出；待用户评审 + S3 侧确认）  
> 上游（只读）：[`synthetic-data-design-v1.md`](./synthetic-data-design-v1.md) **V1.0.5**（§9 清单 / §6.1 类目 / conflict 契约）· [Database §13.21](database-design-v1.md) **V1.2.3 Frozen** · [RAG V1.0](rag-design-v0.2.md)（§3/§4）· AGENTS §15  
> 配套：K5（seed 文件格式 + K-B 切块约定）另行成文；本契约只定**语义**，不定义文件序列化细节  
> 约束：不改写任何 Frozen 契约；数值只进 StoreConfig；发现缺口登记 Gap，不得静默改契约

---

## 0. 本文回答什么 / 非本文

| 本文 | 非本文 |
|------|--------|
| 每篇 seed 文档的元数据字段与取值域 | 正文内容（K4/K6） |
| 生命周期、store_id、section、scope、治理约定 | 文件落盘格式（K5） |
| 10 篇文档的已解析元数据登记表 | 导入器代码（S3.5） |
| seed → DB 的映射职责 | embedding 调优 |

---

## 1. 文档级元数据字段（对齐 DB §13.21 `knowledge_documents`）

| 字段 | 类型 | 取值 / 约定 | 来源 |
|------|------|-------------|------|
| `doc_id` | string | `KD-<域>-<NN>`；10 篇固定（见 §8） | S2 §9 |
| `title` | string | 简短、可检索 | DB title |
| `knowledge_type` | enum | 8 值：`after_sales`/`customer_service`/`inventory`/`operations`/`logistics`/`pricing`/`promotion`/`general`；V1 用 4 种 | RAG §2.1 / T-K-01 |
| `layer` | enum **单值** | `legal`/`platform`/`store`；一篇一个 | RAG §3.1 / S2 §9 |
| `platform` | string | 默认 `default`（模拟平台标识，Business §1.6） | DB platform |
| `store_id` | BIGINT | `0`=全局哨兵；`STORE_01`/`STORE_02` 逻辑店 ID（§3） | DB §13.21 |
| `status` | enum | `ACTIVE`/`DRAFT`/`INACTIVE`；V1 种子只用 `ACTIVE` | DB |
| `version` | string | V1 种子统一 `1.0` | DB / B4-a |
| `effective_from` | date | ACTIVE 文档 ≤ `as_of_date`(2026-09-17) | S2 §1.1 |
| `effective_to` | date / null | `null`=长期有效；EXP 夹具 ≤ `as_of_date` | S2 §1.1 |
| `source_uri` | string / null | 权威篇必填；模拟篇可空 | DB / RAG §3.4 |
| `created_at` / `updated_at` | timestamp | 导入器生成 | DB |

---

## 2. 生命周期与时钟（S2 §1.1）

**当前有效谓词（冻结，DB §13.21 半开区间，禁止改写）：**

```sql
status = 'ACTIVE'
AND effective_from <= now()
AND (effective_to IS NULL OR now() < effective_to)
```

- 种子统一按 **`as_of_date = 2026-09-17`** 书写有效窗；检索/评测时钟约定见 S2 §1.1（as_of 注入或固定系统日）。
- 三种态：**ACTIVE 在窗内**（P0-Core + conflict 对）、**ACTIVE 过期**（EXP 夹具，`effective_to ≤ as_of`，测**时间分支**）、INACTIVE（V1 不造）。
- EXP 夹具必须是 `status=ACTIVE` 但 `effective_to ≤ as_of`——只触发时间窗过滤，不混入 status 分支。
- S4 断言须声明时钟（as_of 注入 **或** 固定系统日 = as_of_date），禁止混用。

---

## 3. store_id 隔离与全局哨兵

| 类别 | store_id | 文档 |
|------|----------|------|
| **全局**（平台/法定层） | `0`（哨兵，DB §13.21） | KD-AS-01 / KD-AS-02 / KD-AS-03 / KD-LG-01 / KD-AS-EXP-01 |
| **店铺**（STORE_01 层） | `STORE_01` | KD-AS-04 / KD-OP-01 / KD-INV-01 / KD-AS-CONF-01 / KD-AS-CONF-02 |

- 检索过滤 = **当前店 ∪ 全局**（RAG §4.3），由服务层依据 `user_context.store_id` 注入；LLM/Agent 不得通过入参覆盖店铺隔离。
- **导入映射**：seed 逻辑店 ID → Canonical 实际 store id（`STORE_01`→S3 生成 id）；`0` 保持 `0`。此映射是 S3.5 导入器职责（§9）。
- V1 不造 STORE_02 店级文档（STORE_02 仅承载隔离/缺配置 SC；知识隔离测试不在 P0 范围）。

---

## 4. section 注册表（chunk 级子类，不扩 knowledge_type 枚举）

> RAG D1：子类用 `section`/tags/metadata；`section` 非封闭枚举。新键在此登记，与 RAG §2.2 示例键（return/exchange/refund/damaged_item…）区分。

| knowledge_type | section 键 | 用于 | 状态 |
|----------------|------------|------|------|
| after_sales | `return` | KD-AS-01 / KD-AS-04 / CONF-01 / CONF-02 / EXP-01 | 复用 RAG 示例 |
| after_sales | `non_returnable` | KD-AS-02 | **新增注册** |
| after_sales | `condition` | KD-AS-03 | **新增注册** |
| logistics | `delivery` | KD-LG-01 | **新增注册** |
| logistics | `delay` | KD-LG-01 | **新增注册** |
| operations | `health_dimensions` | KD-OP-01 | **新增注册** |
| inventory | `replenishment_policy` | KD-INV-01 | **新增注册** |

- `section` 是 **chunk 级**字段：一篇文档可含多 section（如 KD-LG-01 有 `delivery` + `delay` 两片）。
- 键用小写蛇形；一意一段（一条款 ≈ 一 chunk，RAG §5）。

---

## 5. scope / 适用标签（JSONB 落点 + KD-AS-04↔CONF 互斥）

**结构**（seed 文档元数据；作用：R2「适用范围不符排除」的过滤输入）：

```yaml
scope:
  category_codes: []     # 空 = 全类目适用；否则仅列出的类目 code（§6.1）
  include_tags: []       # 命中任一 tag 才适用
  exclude_tags: []       # 命中任一 tag 即排除
```

**落点**：文档级 `scope` 由导入器**复制进该文档每个 chunk 的 `metadata` JSONB**（DB chunks.metadata；RAG §4.2「易变 tags、适用类目列表等 JSONB」）。生命周期真相**只**存 document 列，不冗余到 chunk（RAG §4.2）。

**各文档 scope 分配：**

| 文档 | category_codes | include_tags | exclude_tags | 效果 |
|------|----------------|--------------|--------------|------|
| KD-AS-01/02/03/EXP、KD-LG-01 | — | — | — | 全局适用 |
| KD-AS-04 | 全类目（空） | — | `[apparel-conflict-test]` | **常规商品**；冲突产品被 R2 排除 |
| KD-OP-01 / KD-INV-01 | 全类目（空） | — | — | STORE_01 适用 |
| KD-AS-CONF-01 / 02 | `[apparel]` | `[apparel-conflict-test]` | — | **仅** conflict 产品 |

**KD-AS-04 ↔ CONF 互斥（SC-CS08-007 确定性，V1.0.5 §9 补充约定）：**

- CONF 对只命中 `apparel-conflict-test`；KD-AS-04 显式排除该 tag。
- 效果：conflict 产品的资格查询经 R2 过滤后**只剩两篇矛盾店规**（7 日 vs 15 日），R5 判定干净；其它 apparel 的 CS-08 eligible 用例不受 CONF 对影响。

**product-type tag 注册表（窄于类目的商品适用标签；S2 §6.1 conflict tag 的扩展）：**

| tag | 含义 | 服务 | 状态 |
|-----|------|------|------|
| `apparel-conflict-test` | apparel 下冲突测试产品（S2 §6.1 已固化） | SC-CS08-007（R5） | 已定 |
| `apparel-intimate` | apparel 下贴身衣物（平台不可退，KD-AS-02 依据） | CS-08 按类目 ineligible | **用户 2026-09-18 采纳** |

- 该注册表是**产品侧**约定：S3.1 造数时按 tag 标注对应商品。`apparel-intimate` 需至少 1 件带 tag 商品以支撑 KD-AS-02 条款（否则该条款 V1 无数据支撑，规则 inert）；冲突产品用 `apparel-conflict-test`，两者互不重叠。
- 本 tag 需同步 S3 侧（P2/S3.1 造数依据）。

---

## 6. 治理字段（source_type 等，非 DB 列）

| 字段 | 取值 | 用于 | 落点 |
|------|------|------|------|
| `source_type` | `official` / `internal_simulated` | 权威 vs 模拟（Business §1.6 / RAG §3.4） | seed 元数据 / manifest |
| `source_uri` | string / null | 权威篇必填真实来源 | **DB 列**（documents.source_uri） |
| `source_title` / `retrieved_at` | 可选 | 溯源补充 | seed 元数据（导入器可忽略） |

- **KD-AS-01 强制 `source_type=official` + 非空 `source_uri`**；其余 9 篇 `internal_simulated`（模拟规则，Business §1.6 已授权），`source_uri` 可空。
- 禁止：AI 自造规则标注 `official`；正文写 lead_time/阈值等 Config 数值。

---

## 7. 版本策略（DB B4-a）

- V1 种子全部 `version=1.0`；发布新版 = 旧行 `status→INACTIVE` + 插入新行（新 version、新生效窗）。
- 本 seed **不造多版本**（B4-a 语义留给 S4 侧生命周期测试可选扩展）。

---

## 8. 已解析元数据登记表（10 篇，K6 与导入器的单源）

> 有效窗：ACTIVE 篇 `effective_from=2026-01-01, effective_to=null`；EXP 篇 `effective_from=2026-01-01, effective_to=2026-08-31`。全部 `status=ACTIVE, version=1.0`。

| doc_id | title（主题） | knowledge_type | layer | platform | store_id | section | scope |
|--------|---------------|----------------|-------|----------|----------|---------|-------|
| KD-AS-01 | 七日无理由退货底线 | after_sales | legal | default | `0` | return | 全局 |
| KD-AS-02 | 例外商品/不可退类目 | after_sales | platform | default | `0` | non_returnable | 全局 |
| KD-AS-03 | 完好要求与凭证 | after_sales | platform | default | `0` | condition | 全局 |
| KD-AS-04 | 店铺补充售后政策 | after_sales | store | default | STORE_01 | return | exclude `apparel-conflict-test` |
| KD-LG-01 | 发货时效与物流异常处理 | logistics | platform | default | `0` | delivery / delay | 全局 |
| KD-OP-01 | 健康维度说明与类目例外 | operations | store | default | STORE_01 | health_dimensions | 全局（STORE_01） |
| KD-INV-01 | 库存/备货文字政策 | inventory | store | default | STORE_01 | replenishment_policy | 全局（STORE_01） |
| KD-AS-EXP-01 | 已过期（生命周期夹具） | after_sales | platform | default | `0` | return | 全局 |
| KD-AS-CONF-01 | 冲突对 A：签收 7 日内可退 | after_sales | store | default | STORE_01 | return | `[apparel]` + include `apparel-conflict-test` |
| KD-AS-CONF-02 | 冲突对 B：签收 15 日内可退 | after_sales | store | default | STORE_01 | return | `[apparel]` + include `apparel-conflict-test` |

**source_type**：KD-AS-01 = `official`；其余 = `internal_simulated`。

---

## 9. 导入器映射职责（seed → DB，S3.5 实现契约）

| seed 项 | → DB | 说明 |
|---------|------|------|
| `doc_id` / `title` 等正式列 | `knowledge_documents` 同名列 | 1:1 |
| `store_id`（逻辑） | `knowledge_documents.store_id` | `STORE_01`→Canonical 实际 id；`0`→`0` |
| `section` | `knowledge_chunks.section` | 按 chunk 归属 |
| `scope` | 每 chunk `metadata.scope` | **文档级复制到全部 chunk**（§5） |
| `source_type` 等扩展字段 | 可选择性入 chunk metadata 或忽略 | 非 DB 正式列 |
| 正文 | `knowledge_chunks.content` | 切块（K5） |
| `embedding` | `vector(N)` | S3.5 **stub**（占位 1536，RAG Q-emb Open） |
| 时间戳 | `created_at`/`updated_at` | 导入器生成 |

**容错声明**：`KD-AS-EXP-01`（过期）与 `KD-AS-CONF-01/02`（冲突对）是 **eval 夹具**，非数据错误；导入器/校验不得报错或「修复」。

---

## 10. 校验清单（K3 自检，K6 落盘前过一遍）

1. 10 篇 doc_id 齐全；`knowledge_type`/`layer`/`section` 均在注册集内。
2. ACTIVE 篇有效窗含 `as_of_date`；EXP 篇 `effective_to ≤ as_of_date` 且 `status=ACTIVE`。
3. `store_id` 隔离正确（全局 `0` / STORE_01）；无 STORE_02 店级文档。
4. scope 互斥成立：KD-AS-04 `exclude apparel-conflict-test`，CONF 对 `include apparel-conflict-test`。
5. KD-AS-01：`source_type=official` + 非空 `source_uri`；正文无 Config 数值。
6. 数值旋钮（lead_time/阈值/权重）未进任何正文。

---

## 11. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-18 | K3 首版：字段/生命周期/store_id/section 注册表/scope 互斥/治理/登记表/导入映射/校验清单 |

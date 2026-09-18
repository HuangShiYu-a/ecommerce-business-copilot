# E-commerce Business Copilot — Knowledge → S3 轨整合通知 V1.0

> 文档性质：**Knowledge 轨 → S3 轨的手工对接通知**（非契约修改、非 Generator 代码）  
> 版本：V1.0 · 日期：2026-09-18 · 发起方：Knowledge 窗口  
> 目的：告知 S3 轨 Knowledge 侧已交付的全部输入与对接动作；S3 据此推进 P2–P7
> 请 S3 窗口重点阅读：[K3 元数据契约](./knowledge-seed-contract-v1.md)（V1.0）· [K5 seed 格式](../data/knowledge/seed/README.md) · S2 V1.0.5（§6.1/§9/§8.2）

---

## 1. Knowledge 侧已交付（S3 可消费）

| 交付 | 位置 | 说明 |
|------|------|------|
| **10 篇 seed 正文** | [`data/knowledge/seed/KD-*.md`](../data/knowledge/seed/) | 7 P0-Core + EXP 夹具 + CONFLICT 对；共 **28 chunks** |
| **manifest** | [`data/knowledge/seed/manifest.yaml`](../data/knowledge/seed/manifest.yaml) | 非 DB 列治理字段（source_title/notes 等） |
| **K3 元数据契约** | [`docs/knowledge-seed-contract-v1.md`](./knowledge-seed-contract-v1.md) | 导入器/S4 检索的输入契约 |
| **K5 seed 格式** | [`data/knowledge/seed/README.md`](../data/knowledge/seed/README.md) | front matter + `## [section]` 切块约定 |

**10 篇清单与关键元数据（单源：K3 §8）：**

| doc_id | layer | store_id | section | scope |
|--------|-------|----------|---------|-------|
| KD-AS-01 | legal | 0 | return | 全局（official，已溯源消保法 §25） |
| KD-AS-02 | platform | 0 | non_returnable | 全局 |
| KD-AS-03 | platform | 0 | condition | 全局 |
| KD-AS-04 | store | STORE_01 | return | **exclude `apparel-conflict-test`** |
| KD-LG-01 | logistics→platform | 0 | delivery / delay | 全局 |
| KD-OP-01 | operations→store | STORE_01 | health_dimensions | STORE_01 |
| KD-INV-01 | inventory→store | STORE_01 | replenishment_policy | STORE_01 |
| KD-AS-EXP-01 | platform | 0 | return | 全局（**已过期**，夹具） |
| KD-AS-CONF-01/02 | store | STORE_01 | return | **include `apparel-conflict-test`** |

---

## 2. S3 需对接的动作（按阶段）

### P2 · S3.1 Master

1. **新增 product-type tag：`apparel-intimate`**（K3 §5 注册）——请为 STORE_01 创建 **≥1 件 `apparel` 商品带该 tag**，作为 KD-AS-02「贴身衣物不可退」条款的数据支撑；普通 apparel 商品不带此 tag，避免影响 CS-08 eligible 用例。
2. **conflict 产品**（已有约定，S2 §6.1）：`apparel` 下带 `apparel-conflict-test` tag 的唯一产品；**不与** `apparel-intimate` 重叠。
3. 其余按 S2 §6.1 8 类目 + 角色表正常生成。

### P3 · S3.2 交易主链

4. **SC-CS08-007 订单**：conflict 产品下一单，`signed_at` = as_of 前 **(7, 15) 天**（如 2026-09-07），且**除退货窗口外其余资格条件全满足**（订单状态有效、类目一般可退等），使 RULE_CONFLICT 唯一来源是窗口矛盾。

### P5 · S3.4 Scenario 绑定

5. SC-CS08-007 按 **`runtime_eval`** 绑定：仅挂前置 ID（conflict 产品 + 订单 + 两篇文档），**不断言进程**；RULE_CONFLICT 断言归 S4/harness。

### P6 · S3.5 Knowledge 导入器

6. 按 **K3 + K5** 实现（embedding stub 即可），关键映射：
   - front matter 正式列 → `knowledge_documents` 同名列；
   - `store_id` 逻辑 ID → Canonical 实际 id（`STORE_01`→实际；`0`→`0`）；
   - `## [section]` 标题 = chunk 边界，`chunk_index` 导入器按顺序分配；
   - 文档 `scope` → **复制进每 chunk 的 `metadata.scope`**（JSONB）；
   - manifest 未知字段忽略。
7. 10 篇全部可导入；`KD-AS-01` 已 official 溯源，可核对 `source_uri`。

### P7 · S3.6 校验

8. **夹具容错（必须）**：`KD-AS-EXP-01`（过期）与 `KD-AS-CONF-01/02`（冲突对）是**故意构造的 eval 夹具**，不得判为数据错误，**不得**当作「同 doc 重叠 ACTIVE 窗（DB-G13）」处理（三篇是不同 doc_id 的独立文档）。
9. KD-AS-04 与 CONF 对的 scope **互斥**（exclude vs include 同一 tag）——校验可抽查。

---

## 3. S3 侧读 K3 时重点（避免返工）

- **section 注册表**：7 个键（return / non_returnable / condition / delivery / delay / health_dimensions / replenishment_policy），导入器应按此校验。
- **生命周期**：ACTIVE 篇 `effective_from=2026-01-01, effective_to=null`；EXP 篇 `effective_to=2026-08-31` 且 `status=ACTIVE`（只触发时间分支）。
- **数值禁令**：seed 正文无 Config 数值（已自检），导入不涉 Config。

---

## 4. 待 S3 确认/回报

- [ ] P2 创建 `apparel-intimate` 商品数量与 ID 确认
- [ ] P3 conflict 订单 `signed_at` 与其余资格条件确认
- [ ] P6 导入器按 K3/K5 就绪，10 篇导入通过

---

## 5. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-18 | Knowledge → S3 整合通知首版（交付清单 + 分阶段对接动作 + 契约要点） |

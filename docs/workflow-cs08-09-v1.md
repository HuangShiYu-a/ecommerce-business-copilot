# WF-CS08-09 V1.0.1 — 退货资格判定 + 可选创建退货申请

> 文档性质：**业务 Workflow 契约**（Vertical Slice；非 LangGraph 实现代码）  
> 版本：**V1.0.1**  
> 状态：**V1.0.1 Frozen**  
> 方法依据：[workflow-design-spec-v1.md](./workflow-design-spec-v1.md)  
> 上游（只读）：Business V1.1 · Tool V1.1 Frozen · Database V1.2.3 Frozen · RAG V1.0 Frozen  

---

## 0. Contract 对齐声明

| 层 | 对齐要点 |
|----|----------|
| **Business** | **CS-08** = 退货资格判断；**CS-09** = 售后处理/创建退货申请。本文件是跨场景竖切，**不改写**场景 ID 定义。 |
| **Tool** | 组合：`get_order` → `get_product_detail` → `search_business_knowledge` → `check_return_eligibility` →（可选）审批 → `create_return_request`；草稿非 Tool。 |
| **Database** | 事实：orders / order_items / products；写：after_sales_requests + audit；RETURN 需 `order_item_id` + `quantity`。 |
| **RAG** | CS-08：**强制**在 Eligibility 前取得 `after_sales` 当前有效规则；正式三态不得由 LLM 读 RAG 产生。 |

**命名：** `WF-CS08-09` = Workflow 竖切名；Business 场景仍称 CS-08 / CS-09。

---

## 1. Scope

### In Scope

```text
查询业务事实 + 检索当前有效退货规则
  → 确定性资格三态（eligible / ineligible / undetermined）
  → 结果呈现
  →（仅 eligible）客服确认是否提交申请
  → 高风险审批
  → create_return_request + Audit
  → 完成摘要
```

### Out of Scope

- 换货 / 仅退款建单（Tool Gap-01 / Phase2）  
- 退款金额核算、物流异常主路径（CS-06）、质量鉴定全流程  
- 自动批准高风险售后、LLM 自由裁定资格  

---

## 2. 为何需要 Workflow（Spec R1）

多步骤 + 强制知识顺序 + 三态分支 + 补查/重跑 + 确认 + 审批 + Action → 非「单次 Tool 问答」。

---

## 3. 正式结论来源（Spec R4）

| 结论 | 唯一来源 |
|------|----------|
| `eligible` / `ineligible` / `undetermined` | **T-A-09 `check_return_eligibility`** |
| 是否创建售后单 | **T-X-01**（仅审批通过后） |

LLM **不得**输出正式资格结论。

---

## 4. 主路径

```text
客服输入
  → N0 Intent & Input Validation
  → 订单是否可唯一定位？
        否 → 请求补充 → 回 N0
        是 → N1 Load Order Facts（get_order）
  → 资格判断所需履约/签收时间事实是否完整？
        否 → N1b Load Shipping Status（get_shipping_status）
        是 → 跳过 N1b
  → N2 Load Product Facts（get_product_detail）
  → N3 Load Return Rules（search_business_knowledge, after_sales）【强制】
  → N4 Check Return Eligibility（check_return_eligibility）
  → 【CE】三态分支（见 §5）
```

**说明：** 「履约/签收时间事实完整」指 Eligibility 所需时间类事实（如 `signed_at` / `delivered_at` 等），不把条件绑死在单一字段名（实现映射见 Technical）。

---

## 5. 分支

### 5.1 eligible

```text
N5 Result Presentation
  → N6 CS Confirm Submit（客服确认是否提交申请）
  → 【CE】cancelled → END
        confirmed → N7 Human Approval
  → 【CE】rejected → END
        approved → N8 create_return_request + Audit
  → N9 Completion Summary → END
```

### 5.2 ineligible

```text
N5 Result Presentation → END
```

不得进入 N6–N8。

### 5.3 undetermined

```text
N5 Result Presentation
  → 是否存在可补充 / 可补查信息？
        是 → 补槽或补查（如 N1b / 补 reason）→ 重入 N4（或按缺项回 N1）
        否 → Human Intervention → END
```

`undetermined` **≠** 「不允许退货」（对齐 T-A-09 / Business）。

---

## 6. Node 职责（Spec R3）

| Node | 业务职责 | Tool / 机制 |
|------|----------|-------------|
| N0 | 任务是否为退货资格；提取订单标识；入口校验 | LLM 可抽槽；路由宜规则/分类优先 |
| N1 | 加载订单及行、状态、关键时间等事实 | `get_order` |
| N1b | 关键履约事实不足时补查物流 | `get_shipping_status`（条件） |
| N2 | 加载商品/类目等 | `get_product_detail` |
| N3 | 加载当前有效退货规则 | `search_business_knowledge` |
| N4 | 正式三态结论 | `check_return_eligibility` |
| N5 | 结果呈现（依据、缺失项、可选对客草稿） | LLM（非 Tool） |
| N6 | **客服**确认是否提交退货申请 | UI / LLM 协助（非 C 端买家页） |
| N7 | 高风险 Action 审批 | HITL + `approval` 元数据 |
| N8 | 创建退货申请 | `create_return_request` + Audit |
| N9 | 完成摘要 | LLM + Workflow（Technical 可决定是否独立 Graph 节点） |

**Conditional Edge 不是 Node。**

---

## 7. 三种 Human（Spec R9）

| 类型 | 节点/时机 | 用途 |
|------|-----------|------|
| Human Intervention | undetermined 且无法补查 | 信息不足、规则冲突、能力不可用 |
| Business Confirmation | N6 | 客服决定是否提交申请 |
| Approval | N7 | 是否允许执行 T-X-01 |

操作人与审批人可为同一客服（Business 允许），但**节点语义必须分开**。

**与 WF-CS06 对照：** 本 WF 的 Approval **授权本图内 Action**；CS-06 的 Approval **授权方案后移交**，不在本图写资金单。详见 [workflow-cs06-v1.md](./workflow-cs06-v1.md) §10 与 [workflow-cross-review-v1.md](./workflow-cross-review-v1.md) §5。

编排层路由：资格三态直接用 Tool `decision`（`eligible|ineligible|undetermined`）。实现可将该字段同步到通用 **`route_status`**（值不变），不必再发明第二套枚举。

---

## 8. State 原则（Spec R6；从 N8 反向检查）

### 应保留（逻辑字段，非 DDL）

```text
request_id, user_id, role, store_id
order_id, order_item_id, product_id?
order_status, signed_at / delivered_at（及必要履约摘要）
eligibility, eligibility_reason / reason_code, eligibility_ref?
knowledge_reference（id/version/layer 等，非全量 chunk）
quantity, reason
cs_confirm, approval_status / approval metadata
action_status, error_code, current_step?
```

### 不应进入 State

- PostgreSQL 连接/会话  
- 完整 RAG chunks 原文  
- 无后续用途的大型查询副本  

### N8（T-X-01）合同输入（必须上游能提供）

`order_id`、`item_id`（order_item）、`quantity`、`reason`、`request_id`、`approval{…}`；建议带 `eligibility_ref`。

---

## 9. RAG 位置（Spec R8）

```text
N3（强制 after_sales，当前有效文档）→ N4
```

- `store_id` 由服务层按 `user_context` 注入，LLM 不得覆盖。  
- N3→N4 规则如何注入 Analysis：**业务只要求 N3 已发生且 N4 出正式三态**；内部实现属 Technical Design。

---

## 10. LLM 边界

| 允许 | 禁止 |
|------|------|
| 意图/抽槽、解释、草稿、摘要、协助确认意图 | 伪造事实、正式三态、解决规则冲突当正式结论 |
| | 绕过 undetermined / N6 / N7、直接调用 Action |

---

## 11. 失败与恢复（Spec R7）

| 情况 | 行为 |
|------|------|
| 订单不存在 / Query 失败 | 停止；说明；不硬跑 N4 出 eligible |
| 关键时间事实缺失 | N1b；仍不足 → N4 倾向 undetermined |
| Knowledge 空/不可用 | 不编造规则；undetermined / 不可用 → 人工 |
| 规则冲突且无法按 R1–R5 消解 | undetermined / RULE_CONFLICT → 人工 |
| 跨店 / 无权限 | FORBIDDEN；不泄漏 |
| 无 approval 调 T-X-01 | APPROVAL_REQUIRED |
| 资格未过仍建单 | PRECONDITION_FAILED |
| 数量非法 / 超可退 | VALIDATION_ERROR / PRECONDITION_FAILED |
| 重复提交 | 幂等返回已有单 |

---

## 12. Spec Checklist 自检（摘要）

| # | 结果 |
|---|------|
| R1–R12 / Checklist 1–15 | ✅ 已覆盖（见全文） |
| 边界 | ✅ 不扩换货退款/物流主路径 |
| Cross-Contract | ✅ 与四基线对齐；未改 Frozen 正文 |

---

## 13. 非目标（本文件）

LangGraph StateGraph 代码、Seed 数据、Eval 用例详表（另阶段）。

---

## 14. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-15 | 初版：按 Workflow Spec 与四契约定稿候选；跨 CS-08→CS-09 竖切 |
| V1.0.1 | 2026-09-16 | Freeze Gate：Approval 与 CS-06 对照；`decision` 可映射 `route_status` |
| V1.0.1 Frozen | 2026-09-16 | 用户确认冻结；业务正文未改 |

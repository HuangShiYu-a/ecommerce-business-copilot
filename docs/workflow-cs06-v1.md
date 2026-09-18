# WF-CS06 V1.0.1 — 发货 / 物流异常识别与处理建议

> 文档性质：**业务 Workflow 契约**（非 LangGraph 实现代码）  
> 版本：**V1.0.1**  
> 状态：**V1.0.1 Frozen**  
> 方法依据：[workflow-design-spec-v1.md](./workflow-design-spec-v1.md)  
> 上游（只读）：Business V1.1 · Tool V1.1 Frozen · Database V1.2.3 Frozen · RAG V1.0 Frozen  

---

## 0. Contract 对齐声明

| 层 | 对齐要点 |
|----|----------|
| **Business** | 查订单 → 承诺/实际时效 → 物流轨迹 → **判断异常** → **查异常处理规则** → 话术/建议；赔付/补偿/异常退款需人工确认。 |
| **Tool** | `get_order`、`get_shipping_status`、`analyze_fulfillment_delay`（正式延迟/异常分析；`knowledge_dependency: optional`）、`search_business_knowledge`；缺时效字段不得由模型猜延迟。 |
| **Database** | orders（含 `promised_ship_at` / `promised_delivery_at` 等）、shipments、shipment_events、knowledge；§23 CS-06 含 T-K-01。 |
| **RAG** | CS-06：在**需要处理建议**时检索 `logistics`；**不同于** CS-08「强制规则前置再判定」。 |

---

## 1. Scope

### In Scope

```text
加载履约/物流事实
  → 确定性延迟/异常分析（T-A-01）
  → NORMAL | ANOMALY | UNDETERMINED 分支
  →（仅异常）加载物流处置规则 → 结果呈现（建议/草稿）
  →（仅高风险赔付类建议）Human Approval
  → 结束或移交其他售后 Workflow（本 WF 不内嵌退款/退货超级流程）
```

### Out of Scope

- 退货资格（CS-08）与创建退货单（CS-09）主路径  
- V1 内直接执行赔付/退款资金 Action（可审批后**移交**对应流程）  
- 用 RAG/LLM **替代** `analyze_fulfillment_delay` 做正式异常判定  

---

## 2. 为何需要 Workflow（Spec R1）

多事实加载 + 确定性分析 + 按结果分支 + 条件性知识 + 条件性 HITL → 适合独立 Workflow。  
（对比：纯「查一下物流单号」可接近 CS-05 轻量路径，本 WF 面向异常研判与建议。）

---

## 3. 正式结论来源（Spec R4）

| 结论 | 来源 |
|------|------|
| 是否延迟/履约异常及严重度等 | **T-A-01 `analyze_fulfillment_delay`** |
| 如何向客户解释、如何处置（SOP） | **T-K-01**（异常分支）+ LLM 组织话术 |
| 是否批准高风险补偿方案 | **HITL Approval**（不自动执行资金类 Action） |

### 编排层状态映射（Technical 须写清）

Tool 输出含 `is_delayed`、`severity`、`basis`，以及 `DATA_UNAVAILABLE` 等失败语义。  
本 Workflow 路由使用编排状态：

```text
NORMAL | ANOMALY | UNDETERMINED
```

由服务层根据 T-A-01 结果与失败码映射（业务层不要求 LLM 映射）。  
编排 State 字段名统一为 **`route_status`**（取值同上）。历史草稿中的 `anomaly_status` 视为**同义别名**，实现只写 `route_status`。

---

## 4. 主路径（相对「先 RAG 再分析」的纠正）

**正确形态（Spec R8）：**

```text
Facts → Analysis → Branch →（ANOMALY 时）Handling Rules → Advice
```

**禁止形态：**

```text
Facts → RAG → 用规则文本让 LLM 判定是否延迟
```

```text
客服输入
  → N0 Intent & Input Validation
  → 订单是否可唯一定位？
        否 → 澄清 → 回 N0
        是 → N1 Load Fulfillment Facts
              ├── get_order
              └── get_shipping_status
  → 分析所需关键时效/履约事实是否完整？
        否 → Recovery（补查）或 Human / UNDETERMINED
        是 → N2 Fulfillment Delay Analysis（analyze_fulfillment_delay）
  → 【CE】NORMAL | ANOMALY | UNDETERMINED
```

N1 **允许一个 Node 多个 Tool**（Spec R3）：订单 + 物流同属「履约事实」。

---

## 5. 分支

### 5.1 NORMAL

```text
N4 Result Presentation
  → 说明当前无明确履约异常（及依据摘要）
  → END
```

**不强制**调用 T-K-01（无异常则通常无需处置 SOP）。

### 5.2 ANOMALY

```text
N3 Load Logistics Handling Rules
  → search_business_knowledge（knowledge_type=logistics，当前有效）
  → N4 Result Presentation
       （异常事实 + 分析依据 + 处理建议 + 可选客服草稿）
  → 是否涉及赔付 / 补偿 / 异常退款等高风险方案？
        否 → END
        是 → N5 Human Approval
              → 通过后：移交对应售后/资金流程或人工执行（本 WF 不内嵌完整退款 Action）
              → 拒绝 → END
```

### 5.3 UNDETERMINED

```text
N4 Result Presentation（说明不确定原因）
  → 原因分类：
        缺关键事实 → Recovery 补查 → 条件允许则重入 N2
        规则冲突（若分析侧返回）→ Human Intervention
        系统/依赖不可用 → 降级说明 / Human
```

禁止 LLM 在事实不足时断言「包裹丢失」「严重延误」等正式结论。

---

## 6. Recovery

```text
N1 后或 N2 返回 DATA_UNAVAILABLE / 无法判定
  → 尝试补全承诺时效、轨迹事件等仍缺失的可读事实
  → 重入 N2
  → 仍不足 → UNDETERMINED / Human
```

---

## 7. Node 职责

| Node | 业务职责 | Tool / 机制 |
|------|----------|-------------|
| N0 | 意图（物流/发货异常研判）、订单定位、入口校验 | LLM 可抽槽 |
| N1 | 加载履约判断所需事实 | `get_order` + `get_shipping_status` |
| N2 | 确定性延迟/异常分析 | `analyze_fulfillment_delay` |
| N3 | 异常处置规则（仅 ANOMALY 路径） | `search_business_knowledge` |
| N4 | 结果呈现（结论、依据、建议、草稿） | LLM（非 Tool） |
| N5 | 高风险赔付/补偿方案审批 | HITL |

**Conditional Edge 不是 Node。**

---

## 8. State 原则

### 建议保留

```text
request_id, user_id, role, store_id
order_id
order_status
carrier, tracking_number?
shipping_status
shipped_at, delivered_at, estimated_delivery_at, promised_delivery_at?
last_shipping_event_at?（或等价「最后物流事件时间」语义）
route_status（NORMAL|ANOMALY|UNDETERMINED；别名 anomaly_status 废弃，实现只用本字段）
severity, delay_hours?, analysis_basis / anomaly_reason
knowledge_reference?（异常分支）
handling_recommendation?
human_required, approval_status?
error_code, current_step?
```

### 不应进入 State

- DB 会话、全量轨迹原文（可保留摘要/最后事件）、全量 RAG chunks  

`promised_delivery_at` 等承诺时效：Business/DB 要求参与 CS-06，State/分析输入须可获取。

---

## 9. RAG 位置（与 CS-08 对比）

| | CS-08 / WF-CS08-09 | CS-06 / 本 WF |
|--|--------------------|---------------|
| 规则角色 | 正式资格判定的**必要输入** | 异常成立后的**处置/话术** |
| 调用时机 | N3 **强制**在 N4 前 | N3 在 **ANOMALY** 后 |
| 正式判定 Tool | T-A-09 | T-A-01 |

---

## 10. 三种 Human（本 WF）

| 类型 | 时机 |
|------|------|
| Human Intervention | 事实不足且无法补查、冲突、能力不可用 |
| Business Confirmation | 本 V1 主路径通常不强制（无「提交建单」闸门） |
| Approval | 建议涉及赔付/补偿/异常退款时 |

**与 WF-CS08-09 对照（ON-1 收口）：**

| | CS-06 Approval | CS-08-09 Approval |
|--|----------------|-------------------|
| 批什么 | 高风险**处置方案**（赔付/补偿/异常退款建议） | 是否允许执行 **T-X-01** |
| 通过后 | **移交**售后/资金流程或人工执行；本 WF **无**资金 Action | **本 WF 内** `create_return_request` + Audit |
| 无 Action 时 | 不得假装已改库 | 无审批不得调 T-X-01 |

同一词 **Approval**，两种落点；实现不得做成同一个 Graph 节点模板。

---

## 11. LLM 边界

| 允许 | 禁止 |
|------|------|
| 抽槽、解释 T-A-01 结果、组织建议与草稿 | 伪造物流/时效事实 |
| | 用 RAG 文本自行裁定「是否延迟」正式结论 |
| | 无审批执行资金类写库 |

---

## 12. 失败与恢复

| 情况 | 行为 |
|------|------|
| NOT_FOUND 订单 | 停止并说明 |
| 缺时效字段 | DATA_UNAVAILABLE / UNDETERMINED；Recovery；禁止臆测 |
| 物流数据缺失 | 降级分析或 UNDETERMINED |
| Knowledge 不可用（异常分支） | 仍可呈现分析事实；处置建议标注「规则不可用」并人工 |
| FORBIDDEN | 隔离拒绝 |

---

## 13. Spec Checklist 自检（摘要）

| 项 | 结果 |
|----|------|
| 正式结论来源 T-A-01 | ✅ |
| RAG 不前置替代分析 | ✅ |
| NORMAL 不强制知识 | ✅ |
| 赔付 Approval 且不扩超级 Action | ✅ |
| Node≠单 Tool（N1 多 Tool） | ✅ |
| 边界清晰（不吞 CS-08/09） | ✅ |

---

## 14. 非目标

LangGraph 实现、物流 Seed 明细、Eval 用例全文（另阶段）。

---

## 15. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-15 | 初版：Facts→Analysis→按需 Rules；对齐 Business/Tool/DB/RAG；纠正「先 RAG 再判定」 |
| V1.0.1 | 2026-09-16 | Freeze Gate：`route_status` 为编排字段；Approval 与 CS-08-09 对照（移交 vs 本 WF Action） |
| V1.0.1 Frozen | 2026-09-16 | 用户确认冻结；业务正文未改 |

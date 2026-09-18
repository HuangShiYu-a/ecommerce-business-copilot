# E-commerce Business Copilot — Workflow Design Specification V1.0

> 文档性质：**Workflow 设计方法与审查规范**（非 LangGraph 实现、非 DDL）  
> 版本：**V1.0**  
> 状态：**V1.0 Frozen**（方法规范；变更须用户批准新版本。不负责 LangGraph / ORM / Embedding）  
> 上游（只读）：Business V1.1 · Tool V1.1 Frozen · Database V1.2.3 Frozen · RAG V1.0 Frozen · [AGENTS.md](../AGENTS.md)  
> 约束：不得改写上游 Frozen 核心定义；冲突须上报用户。

---

## 1. 定位

Workflow 回答：**多步骤业务任务如何推进**（顺序、分支、循环、补查、人工、Action）。

不回答：LangGraph API、ORM、Embedding 选型（属 Technical Design）。

```text
Business → Tool → Database → RAG
        → ★ Workflow Spec（本文）+ 各场景 Workflow 文档
        → Technical Design → Implementation
```

---

## 2. 十二条设计规则

| # | 规则 | 摘要 |
|---|------|------|
| R1 | 多步骤才上 Workflow | 简单查询可为 Intent→Tool→Response |
| R2 | 先任务后 Tool | 禁止先排 Tool 再硬拼流程 |
| R3 | Node = 业务步骤 | 一 Node 可多 Tool / 零 Tool；Node ≠ Tool |
| R4 | 正式结论有明确来源 | 资格/延迟/缺货/补货量等不得由 LLM 裁定 |
| R5 | Conditional Edge 只看结构化 State | 禁止「LLM 感觉」作业务分支 |
| R6 | State 只留后续所需 | 非 DB 会话、非全量 RAG 原文；含 `request_id`/`user`/`store_id` |
| R7 | 正常路径 + 异常路径 | 对齐 Tool 失败语义（如 `DATA_UNAVAILABLE`、`RULE_CONFLICT`） |
| R8 | RAG 位置由任务决定 | 资格型可强制规则前置；异常型可「判定后按需取处置规则」 |
| R9 | 三种 Human | Intervention / Business Confirmation / Approval |
| R10 | Action 在确认与审批之后 | 高风险写库 + Audit；禁止 LLM 直写 |
| R11 | Workflow 有边界 | 不做成万能超级流程；跨场景用移交或竖切命名 |
| R12 | 定稿前 Contract Review | Business↔Tool↔DB↔RAG↔本 Workflow |

---

## 3. 定稿前 Checklist（15 项）

1. Task 是否清晰？  
2. 入口 Input 最少要什么？  
3. Facts 从哪来？  
4. Rules vs Config 是否分清？  
5. Formal Result 由哪个 Tool/服务产生？  
6. Node 是否按业务步骤拆（非 Tool 列表）？  
7. State 是否从终点 Action/分支反向检查？  
8. Conditional Edge 依据是否结构化？  
9. Recovery（补查/重跑）是否有？  
10. Human Intervention 何时触发？  
11. Business Confirmation 是否需要？  
12. Approval 是否覆盖高风险 Action？  
13. Action 是否改变状态且带 Audit？  
14. 失败/冲突/能力不可用路径？  
15. 边界：什么不属于本 Workflow？

---

## 4. Frozen Workflow 索引

| ID | 文档 | 类型 | 状态 |
|----|------|------|------|
| WF-CS08-09 | [workflow-cs08-09-v1.md](./workflow-cs08-09-v1.md) | 资格判断 + 可选 Action | **V1.0.1 Frozen** |
| WF-CS06 | [workflow-cs06-v1.md](./workflow-cs06-v1.md) | 异常分析 + 按需规则 + 建议 | **V1.0.1 Frozen** |
| WF-OP05 / OP-04 / OP-07 / OP-08 / OP-03 | [workflow-ops-p0-v1.md](./workflow-ops-p0-v1.md) | P0 运营分析/推荐合集 + 全场景 WF 索引 | **V1.0.2 Frozen** |
| Cross-Review | [workflow-cross-review-v1.md](./workflow-cross-review-v1.md) | 七 WF 横向审查 + Freeze Gate | **V1.0.1 Frozen** |

> Design Coverage：**≈7** 个 WF；P1/P2 仅见 ops 合集 **§G 索引**。  
> 变更须用户批准新版本；实现不得静默改契约。下一步：**Data Requirements**（见 Cross-Review §7）。

---

## 5. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-15 | 首版：12 规则 + Checklist；索引 CS-08/09 与 CS-06 |
| V1.0.1 | 2026-09-15 | 索引挂接 Ops P0 合集文档；明确 ≈7 WF 收口 |
| V1.0.2 | 2026-09-15 | 索引 Cross-Workflow Review；总审通过候选，Freeze 待用户确认 |
| V1.0.3 | 2026-09-16 | 索引 Freeze Gate 完成；方法十二条未改 |
| V1.0 Frozen | 2026-09-16 | 用户确认冻结；方法十二条未改 |

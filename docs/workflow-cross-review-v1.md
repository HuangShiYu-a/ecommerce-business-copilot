# Workflow Cross-Review V1.0.1 — 七 WF 横向架构审查

> 文档性质：**Cross-Workflow Contract Hygiene / 总审查记录**（非实现、非造数）  
> 版本：**V1.0.1**  
> 状态：**V1.0.1 Frozen / Accepted**  
> 审查范围：
>
> | ID | 文档 | Frozen 版本 |
> |----|------|-------------|
> | WF-CS06 | [workflow-cs06-v1.md](./workflow-cs06-v1.md) | V1.0.1 Frozen |
> | WF-CS08-09 | [workflow-cs08-09-v1.md](./workflow-cs08-09-v1.md) | V1.0.1 Frozen |
> | WF-OP05 / OP-04 / OP-07 / OP-08 / OP-03 | [workflow-ops-p0-v1.md](./workflow-ops-p0-v1.md) | V1.0.2 Frozen |
> | Spec | [workflow-design-spec-v1.md](./workflow-design-spec-v1.md) | V1.0 Frozen |
>
> 方法依据：[workflow-design-spec-v1.md](./workflow-design-spec-v1.md)  
> 上游（只读）：Business V1.1 · Tool V1.1 Frozen · Database V1.2.3 Frozen · RAG V1.0 Frozen · [AGENTS.md](../AGENTS.md)

---

## 0. 审查结论（先看）

| 判定 | 说明 |
|------|------|
| **总体** | ✅ **通过**；Freeze Gate **已完成** |
| **是否大改单 WF** | ❌ 不需要 |
| **是否新增 WF** | ❌ 不需要 |
| **是否改 Frozen Business/Tool/DB/RAG** | ❌ 不需要 |
| **阻塞 Freeze 的契约级缺陷** | **未发现** |
| **ON-1～5** | ✅ 已收口（见 §8）；ON-2/ON-3 降级 Technical，不改 Frozen Tool |
| **下一步** | **Data Requirements**（§7）→ Dataset / Generator → OP-05 竖切实现 |

```text
单 WF Review ✅
      ↓
Cross-Workflow Review ✅
      ↓
Freeze Gate ✅
      ↓
Workflow Phase Freeze ✅ ← 当前
      ↓
Data Requirements → Dataset / Generator → Implementation（OP-05 优先）
```

---

## 1. 七 WF 一张表（横向总览）

| WF | 模式 | Formal Result | 路由状态族 | RAG | Confirmation | Approval | Action V1 | 主要移交 |
|----|------|---------------|------------|-----|--------------|----------|-----------|----------|
| **CS-08-09** | 资格→写 | T-A-09 三态 | `eligible` / `ineligible` / `undetermined` | **强制前置** after_sales | ✅ N6 | ✅ N7 | ✅ T-X-01 | — |
| **CS-06** | 异常→建议 | T-A-01 | `NORMAL` / `ANOMALY` / `UNDETERMINED` | **异常后** logistics | 通常否 | 条件（赔付方案） | ❌（移交） | → CS-08/09 / 人工资金 |
| **OP-05** | 计算→推荐 | T-R-01 | `HAS_RECO` / `NO_RECO` / `UNDETERMINED` | 可选 inventory 解释 | ✅ | ❌ V1 | ❌ Gap-02 | ← OP-04 |
| **OP-04** | 计算→风险 | T-A-07 | `HAS_RISK` / `NO_RISK` / `UNDETERMINED` | 可选解释 | ❌ | ❌ | ❌ | → OP-05 |
| **OP-07** | 评分→建议 | T-A-05 | level / completeness 策略 | 可选 operations 文字 | ❌ | ❌ | ❌ | — |
| **OP-08** | 异常→诊断 | T-A-06 | `NORMAL` / `ANOMALY` / `UNDETERMINED` | 不参与判定 | ❌ | ❌ | ❌ | → OP-09/10（索引） |
| **OP-03** | 候选→增强 | T-A-04 + 可选 T-A-05 | `HAS_CANDIDATES` / `EMPTY` / `UNDETERMINED` | 可选文字 | ❌ | ❌ | ❌ | → OP-06/12（索引） |

**判定：** 形态故意不同（符合「共享原则 ≠ 共享节点模板」）；Human / Action 按业务需要出现，无「为了 HITL 而 HITL」。

---

## 2. 审查轴 ① — Calculation / 算法是否唯一

| 共享服务 | 消费者 | 口径约束 | 审查结果 |
|----------|--------|----------|----------|
| **Inventory Calculation Service** | OP-04 T-A-07、OP-05 T-R-01（及 DOI/日均销/缺货日） | DB §12A units | ✅ 合集 §A.4 已强制；无第三套算法入口 |
| **Sales Calculation Service** | OP-03/07/08（及 T-A-02/03/04 销售量） | §12A GMV/orders/units/AOV | ✅ 已声明；CS 侧订单事实不另造销售口径 |
| **Health Scoring** | OP-07 主用；OP-03 可选复用 | 权重 StoreConfig | ✅；与「滞销风险」语义已拆开（Gap-OP03） |
| **Fulfillment Delay Analysis** | CS-06 T-A-01 | 承诺时效 + 轨迹 | ✅ 独立域；不与销售 anomaly 混名 |
| **Return Eligibility** | CS-08-09 T-A-09 | 事实+规则三态 | ✅ 唯一正式资格源 |

**禁止（Freeze 后实现仍须守）：** 为「方便」在某个 WF 内复制日均销公式；用 LLM 重算 health/anomaly/eligibility。

---

## 3. 审查轴 ② — Tool Result ≠ Route State

### 3.1 统一原则（全项目）

```text
Tool / Service 输出结构化业务结果
        ↓
编排层（非 LLM）映射 **`route_status`**
        ↓
Conditional Edge 只读 `route_status` / 其他结构化字段
```

### 3.2 各族对照（允许异名，禁止异义）

| 族 | 成员 | Tool 侧锚点 | 说明 |
|----|------|-------------|------|
| **决策三态** | CS-08-09 | `decision` 直接作路由 | 特例：Tool 决策态 = 路由态（eligible…）；**undetermined ≠ ineligible** |
| **异常三态** | CS-06、OP-08 | `is_delayed` / `is_anomaly` → NORMAL\|ANOMALY\|UNDETERMINED | 同构；映射表归 Technical |
| **有无结果** | OP-04/05/03 | 列表非空 / 建议量>0 / 候选非空 | HAS_* / NO_* / EMPTY；阈值已在 Tool 内消化（如 high_risk 入列） |
| **评分策略** | OP-07 | `level` + `data_completeness` | 非布尔三态；分支看结构化字段 |

### 3.3 `UNDETERMINED` 统一语义（横向钉死）

| 含义 | 是 | 否 |
|------|----|----|
| 事实/配置/依赖不足，**无法给出正式业务结论** | ✅ | |
| 等价于「不合格 / 无风险 / 不补货 / 无异常」 | | ❌ |
| 可由 LLM「感觉还能判」硬出正式结论 | | ❌ |

CS-08 的 `undetermined` 与 Ops/CS-06 的 `UNDETERMINED` **同族语义**。实现：资格三态写入 `route_status`（小写与 Tool `decision` 一致即可）；异常/运营族用大写枚举。允许大小写随族；**禁止**第二套并行字段名（已废弃 `anomaly_status`）。

### 3.4 「风险」一词消歧

| 用语 | 归属 | 勿混淆为 |
|------|------|----------|
| 条目 `risk_level`（缺货） | Tool 输出字段 | 路由态 `HAS_RISK` |
| `HAS_RISK` | 路由：清单非空 | 滞销/健康风险 |
| health `level` / `risk_factors` | Tool 健康信号 | 滞销风险等级 / 缺货 risk_level |
| Tool 元数据 `risk_level` LOW/MEDIUM/HIGH | Action/工单风险策略 | 业务缺货等级 |

**判定：** ✅ 语义已可 Freeze；实现字典须遵守上表。

---

## 4. 审查轴 ③ — RAG 是否滥用

| WF | knowledge_type | 时机 | 是否进入 Formal Result | 结果 |
|----|----------------|------|------------------------|------|
| CS-08-09 | after_sales | **判定前强制** | 规则为 T-A-09 **输入**；三态仍只由 T-A-09 出 | ✅ |
| CS-06 | logistics | **ANOMALY 后** | 否（处置/话术） | ✅ |
| OP-05 | inventory 可选 | 建议后解释 | 否 | ✅ |
| OP-04 | inventory 可选 | 分析后解释 | 否 | ✅ |
| OP-07 | operations 可选 | 评分后说明/例外 | 否；权重在 StoreConfig | ✅ |
| OP-08 | 不参与判定 | — | 否 | ✅ |
| OP-03 | 可选 clearance 文字 | 候选后 | 否 | ✅ |

**Config vs RAG：** 安全库存 / lead time / 健康权重 / 异常阈值 → **StoreConfig**；RAG 禁止补数值。✅

---

## 5. 审查轴 ④ — 三种 Human 是否统一

| WF | Intervention | Business Confirmation | Approval | 备注 |
|----|--------------|----------------------|----------|------|
| CS-08-09 | undetermined 无法补查等 | ✅ 是否提交申请 | ✅ 是否执行 T-X-01 | 完整 HITL 范型 |
| CS-06 | 冲突/不可用等 | 通常否 | 条件：赔付类**方案** | Approval **不**等于已有资金 Action；通过后**移交** |
| OP-05 | 配置/数据不足等 | ✅ 是否采纳建议 | V1 无 | Confirmation ≠ 改写计算真相 |
| OP-04/07/08/03 | 按需 | 否 | 否 | 只读分析 |

**钉死：**

```text
Intervention  = 流程无法可靠继续（缺事实/冲突/不可用）
Confirmation = 人对「是否采纳/是否提交」的业务决定（可不改库）
Approval      = 对「是否允许执行高风险 Action」的授权
无 Action ⇒ 不虚构 Approval（OP-05 V1）
有方案需批但无本 WF Action ⇒ Approval 后移交（CS-06）
```

**判定：** ✅ 与 Spec R9 / Tool 审批模型一致。

---

## 6. 审查轴 ⑤ — State / Failure / Handoff

### 6.1 State 公共最小集（所有 WF）

```text
request_id
user_id, role          ← 来自 user_context，禁止 LLM 臆造
store_id               ← 同上；跨店 FORBIDDEN
route_status（或等价决策态）
error_code?, current_step?
```

**禁止入 State：** DB 会话、全量 RAG chunks、无用大结果集原文。

**CS 特有：** `order_id` 及履约/资格字段。  
**OP 特有：** `horizon_days` / `product_id`/`sku` scope、分析摘要、recommendations 等。

### 6.2 Failure 语义对齐

| error 族 | 期望行为（七 WF 一致） |
|----------|------------------------|
| `NOT_FOUND` | 停止说明；不硬出正式结论 |
| `DATA_UNAVAILABLE` | Recovery 或 UNDETERMINED；禁止臆测补全 |
| `FORBIDDEN` | 隔离拒绝 |
| Knowledge 不可用 | 资格类 → 难出 eligible；分析类 → 仍可出 Formal，解释降级 |
| `APPROVAL_REQUIRED` / 无批调 Action | 仅写路径（CS-08-09） |

### 6.3 跨 WF Handoff（允许的边）

```text
OP-04 ──(生成补货建议)──► OP-05
CS-06 ──(退货/售后主路径)──► CS-08-09
CS-06 ──(资金赔付执行)──► 人工 / Phase2（本批无资金 Action）
OP-03 ──(清仓/下架)──► OP-06 / OP-12（索引；Phase2）
OP-08 ──(调价/促销)──► OP-09 / OP-10（索引；Phase2）
CS-10（索引）──► CS-08-09（禁止超级售后流吞并）
```

**禁止：** 在单一 Graph 内嵌「万能售后/万能运营」超级流程（Spec R11）。

**判定：** ✅ handoff 边界清楚。

---

## 7. 审查轴 ⑥ — Data Requirements 反推清单（收口输入）

> 服从 AGENTS §15：由 Workflow 反推；Scenario 引用统一底座；本阶段**只列需求，不造数**。

### 7.1 统一底座（多 WF 共用）

| 域 | 最小需要 | 服务 WF |
|----|----------|---------|
| stores + store_configs | lead_time、safety、health 权重、anomaly 阈值、slow_moving 过滤 | OP-04/05/07/08/03 |
| products / skus | 含 cost 可选（支撑 health 利润维） | OP-03/07 等 |
| inventory | 多 SKU 梯度（缺货/健康/积压对照） | OP-04/05/03 |
| orders / order_items | §12A 可算销量时间线 | 全体 OP + CS |
| shipments + events + promised_* | 履约时效 | CS-06；CS-08 签收 |
| after_sales + quantity | 退货率、资格 | CS-08-09；OP-03/07/08 |
| price_history | 调价证据 | OP-08 |
| customer_feedback | 归因/健康 | OP-08/07 |
| knowledge（当前有效） | after_sales、logistics、operations、inventory 短文本 | CS-08、CS-06、OP-07、可选 OP-04/05/03 |

### 7.2 Scenario / Eval 对照样本（按 WF）

| WF | 至少需要的案例类型 |
|----|-------------------|
| CS-08-09 | eligible / ineligible / undetermined（缺签收）；确认取消；审批拒绝；成功建单 |
| CS-06 | NORMAL / ANOMALY / UNDETERMINED（缺时效）；Knowledge 不可用仍出分析 |
| OP-05 | HAS_RECO / NO_RECO；指定 SKU 跳过预筛；Confirmation 采纳/拒绝 |
| OP-04 | 清单非空 vs 空；移交 OP-05 |
| OP-07 | 全维 / 缺可选维 / 缺核心维 completeness |
| OP-08 | 达阈值异常 vs 未达；价格/库存/反馈证据；禁止口授阈值覆盖 |
| OP-03 | 慢销 vs 热销；有/无 health 增强；**无** T-A-04.profit 假设 |

### 7.3 已登记 Gaps（Data/实现勿假装已关闭）

| Gap | 影响 |
|-----|------|
| Gap-OP05-Action | 无采购建单；Confirmation 为止 |
| Gap-OP03-Profit-Surface | 利润不经 T-A-04；经 health 或降级 |
| Tool Gap-01/02/06 等 | Phase2；索引 Yes ≠ Tool 就绪 |

---

## 8. Open Notes — Freeze Gate 收口

| ID | 原问题 | Gate 处理 | 状态 |
|----|--------|-----------|------|
| ON-1 | CS-06 Approval 后移交 vs CS-08 Approval→本 WF Action | 写入 CS-06 §10 对照表、CS-08-09 §7 对照句；本文 §5 仍为原则 | **Closed** |
| ON-2 | OP-05 Confirmation 是否必须 approver / 是否审计 | WF 钉死：V1 无 Action ⇒ 无 Approval、不要求 Tool `approver_id`；角色与日志 → Technical；**不改 Frozen Tool** | **Closed → Technical** |
| ON-3 | OP-07 `level` 未在 Tool 穷尽 | WF 只消费 T-A-05 输出枚举，不发明新等级；**不改 Frozen Tool** | **Closed → Technical** |
| ON-4 | CS-06 `anomaly_status` vs OP-08 `route_status` | 全项目编排字段统一 **`route_status`**；`anomaly_status` 为废弃别名 | **Closed** |
| ON-5 | Draft / 版本元数据不一致 | 文头与修订记录对齐；**已 Frozen** | **Closed** |

**Frozen 版本（已执行，版本号保持、只改状态）：**

| 文档 | Freeze 时版本标签 |
|------|-------------------|
| Workflow Spec | **V1.0 Frozen** |
| WF-CS06 | **V1.0.1 Frozen** |
| WF-CS08-09 | **V1.0.1 Frozen** |
| Ops P0 合集 | **V1.0.2 Frozen** |
| Cross-Review | **V1.0.1 Frozen** |

不把 Ops 人为改回 V1.0 只为整齐。

---

## 9. Spec R1–R12 合集抽检

| 规则 | 七 WF | 备注 |
|------|-------|------|
| R1 | ✅ | 简单场景在 Ops §G 已排除 |
| R2–R3 | ✅ | Node≠Tool；多 Tool Node 存在 |
| R4–R5 | ✅ | Formal Source + 结构化 CE |
| R6 | ✅ | State 公共集 + 禁全量 RAG |
| R7 | ✅ | Recovery / UNDETERMINED |
| R8 | ✅ | CS-08 强制前置 vs 其余按需 |
| R9–R10 | ✅ | Human 三分；Action 在批后 |
| R11 | ✅ | handoff 非超级流 |
| R12 | ✅ | 本文即横向 Contract Review |

---

## 10. Freeze Gate 清单与 Freeze 执行记录

### 10.1 Gate 清单（本回合）

| # | 项 | 结果 |
|---|----|------|
| 1 | ON-1～5 契约可读性收口 | ✅ |
| 2 | `route_status` 横向统一 | ✅ |
| 3 | Approval 两种落点写清 | ✅ |
| 4 | 文头版本与修订记录对齐（仍 Draft） | ✅ |
| 5 | 未改 Business / Tool / DB / RAG Frozen | ✅ |
| 6 | 未新开 WF、未进 Data/造数 | ✅ |

### 10.2 Freeze 执行记录（2026-09-16）

1. ✅ §8 表中文档状态改为 **Frozen**（版本号保持上表）。  
2. ✅ 本文状态改为 **Frozen / Accepted**。  
3. ✅ 同步 `AGENTS.md` 与协作规则：Workflow 移入 Frozen。  
4. ✅ **未**改 Business / Tool / DB / RAG Frozen。  
5. 下一阶段：开 **Data Requirements**（以 §7 为提纲）。  
6. 实现竖切：`OP-05` 优先，再 `CS-08-09` 或 `CS-06`。

---

## 11. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-15 | 首版：七 WF 横向审查；结论通过、可 Freeze；Open Notes 非阻塞；Data 反推清单 |
| V1.0.1 | 2026-09-16 | Freeze Gate：ON-1～5 收口；`route_status`；Approval 对照；版本表；Gate 清单通过 |
| V1.0.1 Frozen | 2026-09-16 | 用户确认冻结；Ops §G.3 卫生已对齐 |

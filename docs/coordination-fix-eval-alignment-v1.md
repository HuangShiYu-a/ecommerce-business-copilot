# 修复窗口 ↔ 评测窗口 语义对齐说明 V1.1

> 文档性质：**跨窗口协调交接**（非冻结契约；**双向**协调参考，两窗口开工前阅读）
> 版本：V1.1
> 日期：2026-09-27（V1.1 更新 2026-09-28）
> 作者：修复窗口（主线 `docs/fix-plan-audit-v1.md`）；评测窗口补充状态更新
> 读者：双方
>
> **状态更新（2026-09-28，V1.1）**：修复窗口阶段 0~7 **全部落地提交**（`09bc470` 阶段 1 + `3d6ca03`
> 阶段 2~7）；评测窗口以 `docs/evaluation-plan-v1.md` **V1.2.3** 对齐最终语义（CS-08 already_exists
> 两路径 + resume 保护、CS-06 在途超期→ANOMALY、CS-08 成功态口径、OP-03 候选非空、M6 补 H4 否定句、
> Correctness 160→175）。本文档升级为**双向**协调参考。

---

## 0. 一句话概括

本窗口负责**审计缺陷修复**，已完成阶段 1（H4+H1），对 **CS-08 退货流程等行为做了语义变更**；这些变更与评测窗口 M1~M8 的既有假设存在 7 处冲突。**请在阶段 3（M2 谓词 / M6 表 / eval_metrics / latency 埋点）开工前，先读本文档并对齐 §4 的 5 处新语义。**

---

## 1. 本窗口（修复窗口）工作范围与当前状态

**主线**：`docs/fix-plan-audit-v1.md` —— 修复全量审计发现的 15 项缺陷（H1~H4 / M1~M5 / L1~L6），分 7 个 Gate 阶段实施。

**已完成**：
| 阶段 | 内容 | 结果 |
|---|---|---|
| 0 | 基线核查 | pytest 160 / eval_g3 3/4（补货确认为已知 live 抖动）/ eval_g5 2/2，无残留 |
| 1 | **H4** 审批文本否定句判定 + **H1** CS-08 already_exists 短路 | 全量 pytest **163**（+3 测试）；eval_g3 3/4 同基线；无残留 |

**阶段 1 涉及文件（当前未提交）**：
`copilot/context.py`、`copilot/agent/react.py`、`copilot/agent/toolkit.py`、`copilot/agent/workflows.py`、`copilot/agent/orchestrator.py`、`copilot/tests/test_react.py`、`copilot/tests/test_workflow.py`、`scripts/eval_g3.py` + 新文档 `docs/fix-plan-audit-v1.md`

**后续阶段（会继续触及共享/被评测复用的文件，需相互知会）**：
| 阶段 | 改动 | 涉及文件 |
|---|---|---|
| 2 | H2：在途超期→ANOMALY | `calc/fulfillment.py`、`tools/fulfillment_delay.py`、`sc_runner.py` |
| 3 | H3+L4：可退数量/健康度 returns 状态过滤 | `tools/create_return_request.py`、`calc/product_health.py` |
| 4 | M1：slow_moving 窗口口径 | `calc/slow_moving.py` |
| 5/6 | 文档对齐 + L 批小修 | 若干 |

---

## 2. 并行窗口（评测窗口）工作范围（据 evaluation-plan-v1.md）

**主线**：实施 M1~M8 评测指标（tool_sel / multihop / rag_gold 数据集 + `eval_metrics.py` + react.py latency 埋点）。

**已完成**：阶段 2（提交 `7e7812f`：三份 gold 数据集 + 方案 A 共享数据解耦，Correctness 恢复 160 全绿）。

**待开工**：阶段 3 —— M2 每 workflow 业务结果谓词（8 个）+ M6 安全判定表 + eval_metrics 离线判定函数 + react.py latency 埋点。

---

## 3. 详细冲突点（7 条）

### 🔴 C1：react.py 同文件改动 + 未提交 H4（最高优先）
- **矛盾点**：本窗口阶段 1 在 `react.py` 改了 `resolve_approval_text`（+ import `approval_text_decision`），**未提交**；评测窗口阶段 3 计划在**同一文件**加 latency 计时/token 采集（eval 计划 §5「代码改动面：react.py latency 计时 1 处」）。
- **风险**：本窗口未提交改动是"弱状态"，评测窗口任何 git 写操作（`add -A`/`commit -a`/`checkout .`/`stash`）都可能**收走或回滚**它。先例：本窗口对 `data/scenarios/eval/scenarios.yaml` 的改动已被评测窗口工作流回滚。
- **建议**：本窗口会尽快提交阶段 1；评测窗口动 react.py 前先 `git status` 确认无对方未提交改动；latency 埋点做成独立 helper/装饰器，不改 `model_node`/`tools_node` 函数体结构。

### 🔴 C2：CS-08 `already_exists` 新语义 vs 评测旧假设（最深的语义冲突）
- **矛盾点**：本窗口 H1 后，CS-08 重复申请**短路返回 `already_exists`（不 interrupt、不调 T-X-01）**。评测计划有 **3 处旧假设**：

| 评测计划位置 | 旧假设 | 与新语义的矛盾 |
|---|---|---|
| §2.4「workflow 类 SC 第二跳自动 resume approved」 | 每次申请都 interrupt | 已有退货单时第一跳不 interrupt → 第二跳 resume 打在无挂起 interrupt 的图上，可能报错/空转 |
| §5「同订单重跑天然幂等返回原单」 | 重跑走完建单返回原单 | 现在重跑不建单、返回 already_exists，注释已过时 |
| M2 Side Effects「T-X-01 成功 + audit 存在 + 幂等」（§3.2） | 幂等=重放返回原单 | 现在重复申请不调 T-X-01，「幂等」含义=不重复触发建单 |

- **建议**：M2 CS-08 谓词按新语义写（见 §4.1）；harness 自动 resume 前检查 `__interrupt__` 是否存在。

### 🟠 C3：工作树未提交改动可能被误收
- **矛盾点**：本窗口 8 个文件未提交；评测窗口若用 `git add -A`/`commit -a` 会把这些收进评测提交（归因混乱），或用 `checkout .` 回滚。
- **建议**：双方只 `git add <具体文件>`，不用 `-A`；动共享文件前先 `git status`。

### 🟠 C4：「160 测试」口径漂移
- **矛盾点**：本窗口阶段 1 新增 3 条测试 → 全量 **163**；评测计划 §1.1/§1.2/§6 及提交说明仍写 **160**。
- **建议**：下次评测报告/简历回填用 163（或最新 pytest 实数）；措辞改「160+」避免硬编码。

### 🟡 C5：sc_runner 复用契约（H2 前瞻）
- **矛盾点**：阶段 2 本窗口会改 `run_cs06` 给 `fulfillment_delay` 传 `as_of`；评测计划 §5 复用 sc_runner 派生逻辑，若直接 import `run_cs06`/`map_cs06` 需感知签名变化。
- **已核实**：`map_cs06` 输出结构（NORMAL/ANOMALY/UNDETERMINED）不变；现有 SC-CS06 data 断言不翻转。
- **建议**：`run_cs06` 的 as_of 用默认参数向后兼容；评测新增在途超期 case 时按 §4.2 新语义写期望。

### 🟡 C6：SC-CS08-006 与「scenarios.yaml 冻结纪律」
- **矛盾点**：本窗口曾尝试给 SC-CS08-006 加 `expected_route`（被回滚，已暂缓）；评测计划 §2 明示「scenarios.yaml 是已冻结的 SC 资产（**不重塑**）」。
- **结论**：本窗口**确认不再硬改 scenarios.yaml**；「已有退货」语义断言改由专门测试与 M2 谓词承载。
- **建议**：评测窗口阶段 3 写 CS-08 M2 谓词时，把 SC-CS08-006（预置已成功售后）纳入覆盖，验证 already_exists 语义。

### 🟡 C7：slow_moving 数值变化（M1 前瞻）
- **矛盾点**：阶段 4 本窗口会修 slow_moving 窗口口径（`SKU_01_SLOW_01` units 6→4，纠正含 CANCELLED 的统计）；评测 M1/M2 若引用 slow_moving 数值会受影响。
- **已核实**：SC-OP03 只断言 `HAS_CANDIDATES` 路由，不引用数值 → 不翻车。
- **建议**：OP-03 谓词用「候选清单非空/命中 SKU」而非精确 units 数值。

---

## 4. 语义对齐要点（5 处新语义，评测窗口须采用）

### 4.1 CS-08 退货流程（H1 已完成，最重要）
- **新语义**：订单已有成功退货单（APPROVED/COMPLETED/PROCESSING）时，`cs08_return_workflow` **短路**返回：
  ```
  {decision, reason_code, explanation, existing_return,
   status: "already_exists", message: "订单 X 已有退货申请（ASR...），不再重复创建"}
  ```
  不触发 `interrupt`、不调用 `T-X-01`。
- **判定影响**：M2 CS-08 谓词的 Side Effects = 「每订单**有且仅有一次** T-X-01 建单」；重复申请断言 `result.status == "already_exists"` 且 `approval_required == false`。
- **harness 影响**：CS-08 重跑 case 不要假设必 interrupt；resume 前检查挂起。

### 4.2 物流履约判定（H2，阶段 2 将实施）
- **新语义**：已发货、未送达、且 `promised_delivery_at < AS_OF_DATE` → **ANOMALY（overdue_in_transit）**（原为 NORMAL/in_transit）。
- **判定影响**：188 单在途超期将翻转；M2 CS-06 谓词若涉及在途超期 case，期望用 ANOMALY。

### 4.3 可退数量口径（H3，阶段 3 将实施）
- **新语义**：可退数量 `SUM` 只算成功态（APPROVED/COMPLETED/PROCESSING），REJECTED/CANCELLED/PENDING **不再扣减**。
- **判定影响**：M2 CS-08 若断言可退数量，需用成功态口径。

### 4.4 slow_moving 窗口口径（M1，阶段 4 将实施）
- **新语义**：窗口销量只统计窗口内有效订单（含状态过滤），排除窗口外/非有效状态订单。
- **判定影响**：慢销候选的 units 数值变化（SKU_01_SLOW_01 6→4）；候选集合一般不变。

### 4.5 审批文本判定（H4 已完成）
- **新语义**：审批文本确认/拒绝走 `context.approval_text_decision`——**拒绝词优先**（不同意/不确认/不用）**+ 疑问句守卫**；「不同意」→ rejected。
- **判定影响**：M6 Approval Bypass Rate 测试的文本输入需覆盖否定句；该修复使 bypass=0% 的叙事更可信（互补）。

---

## 5. 需要评测窗口配合的事项（协作纪律）

1. **动共享文件前对齐**：`react.py`（latency）、`sc_runner.py`、`data/scenarios/eval/scenarios.yaml`、`scripts/eval_g3.py` 属两窗口共用，改动前先 `git status` + 读本文档 §3。
2. **提交隔离**：只 `git add` 自己的文件，不用 `-A`；不要回滚对方未提交改动。
3. **M2 谓词按 §4 语义**：CS-08（4.1）、CS-06（4.2）、OP-03（4.4）谓词设计采用新语义。
4. **harness resume 保护**：workflow 类 SC 第二跳 resume 前检查 `__interrupt__`。
5. **数字口径**：Correctness 层测试数更新为 **175**（当前 HEAD pytest 实数，勿硬编码 160/163）。

---

## 6. 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| V1.0 | 2026-09-27 | 初版：修复窗口 → 评测窗口语义对齐（7 冲突点 + 5 新语义 + 协作纪律） |
| V1.1 | 2026-09-28 | **状态收尾（双向化）**：修复窗口 0~7 全部提交（`09bc470`/`3d6ca03`）；评测窗口 V1.2.3 对齐最终语义；协调文档升级为双向参考；数字口径 163→175 |

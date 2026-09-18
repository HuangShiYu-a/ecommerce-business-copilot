# E-commerce Business Copilot — S3 Generator 实施规划 V1.1

> 文档性质：**S3 Generator 实施规划** —— 分阶段、含风险/改动量/难度/阻碍项分析与过门评估；非 Generator 代码、非灌库、非改 Frozen
> 版本：**V1.1**
> 状态：**已实施完成**（2026-09-18，S3.0–S3.7 + 收口全部过门；dev+eval 双世界生成；待 S4 导入验证）
> 上游（只读）：[`synthetic-data-design-v1.md`](./synthetic-data-design-v1.md) **V1.0.5**（Generator 说明书）· Database V1.2.3 Frozen · RAG V1.0 Frozen · [AGENTS.md](../AGENTS.md) §15
> 约束：服从 S2 §15 子阶段定义与验收门；发现与 Frozen 冲突停止并上报；不扩 scope

---

## 0. 本规划回答什么

| 问题 | 本文 | 非本文 |
|------|------|--------|
| S3 分几个阶段、每阶段实施什么 | ✅ | — |
| 每阶段风险 / 改动量 / 难度 / 阻碍项 | ✅ | — |
| 实施顺序与过门评估 | ✅ | — |
| 已拍板的实施决策点 | ✅ | — |
| Generator 代码 | ❌ | S3 实施时逐步产出 |
| 灌库 / 接 DB / Tool 路由验证 | ❌ | S4 |
| 改 Frozen 契约 | ❌ | 仅登记 Gap |

---

## 1. S3 关键前提（先读）

1. **零基础设施依赖**：S3 只产出 `data/generated/dev|eval/canonical/` 下的表级文件（CSV 起步，Parquet 可选）；**不需要** PostgreSQL/pgvector、Docker、LLM/Embedding API（S3.5 embedding 可 stub）。风险面远小于后续接库、接 Tool 阶段。
2. **唯一外部依赖 = S3.5 的 Knowledge 稿**：用户已决定在**独立窗口**并行产出 K-A P0-Core 正文（与业务数据生成同步），本仓库不自行生成 Knowledge 正文。S2 §9 的元数据契约（`layer` 单值 / `platform` / `store_id` / `effective_from`/`to` 相对 as_of / `status`）是两份窗口之间的接口：按该契约产出即可被 S3.5 导入。
3. **K-A 不在本实施序列内**：S3.5 在最低 P0-Core 稿到位前只能 stub 导入接口并记录「稿件阻塞」（S2 §15.4-3）。

---

## 2. S3 实施项总览（风险 / 改动量 / 难度 / 阻碍项）

| 阶段 | 实施内容 | 风险 | 改动量 | 难度 | 主要阻碍项 |
|------|----------|------|--------|------|------------|
| **S3.0 骨架**（含环境引导） | 目录结构（S2 §10）、CLI、`profiles.yaml`（dev/eval/full）、seed/as_of 读入、空 generate、退出码 0 | 低 | 小 | 低 | 零代码零 git，需先引导工程与版本控制（决策点 1/2） |
| **S3.1 Master** | Store/Staff/Warehouse/Category/Product/SKU + 13 角色标签 + StoreConfig（§5 默认值、STORE_02 缺配置构造） | 中 | 中 | 低–中 | 角色→参数初值（决策点 3）；StoreConfig 各 key JSON 形态；稳定 ID 方案 |
| **S3.2 交易主链** | Customer/Address 快照 → Order/Item（90 天 §12A）→ Shipment/Event（CS-06 三构造）→ Inventory 快照（策略 B 反推） | **高** | **大** | **中–高** | 角色→具体参数钉死；多时间戳强一致；策略 B 反推不得与销量叙事矛盾 |
| **S3.3 派生事实** | AfterSales / Feedback / PriceHistory / Campaign | 中 | 中 | 中 | 跨实体一致性：退货量 ≤ 购买、反馈 ≥ 送达、最新价 = 现价 |
| **S3.4 Scenario 绑定** | `scenarios.yaml` + 稳定 ID / inject（**仅 data 型 26 条**） | 中–高 | 中 | 中 | 32 条 SC 引用可解析；STORE_02 缺配置 SC 销量事实齐备；data/runtime 边界不越界 |
| **S3.5 Knowledge 导入** | `knowledge/seed` → documents/chunks（embedding 可 stub） | **依赖外部** | 小 | 低–中 | 用户 Knowledge 稿（分轨窗口）；`layer` 单值元数据契约 |
| **S3.6 校验骨架** | schema/FK、§12A、角色叙事、SC data 前置、ISO 隔离、Knowledge 生命周期 | 中 | 中 | 中 | 校验边界（只验数据不验 Tool）；P0 失败阈值 |
| **S3.7 eval 切片** | 同 seed + manifest 过滤导出 `generated/eval/` | 低 | 小 | 低 | 依赖 S3.4 / S3.6 过门 |

**风险排序（高→低）：** S3.2 ≫ S3.4 > S3.1/S3.3/S3.6 > S3.0/S3.7；S3.5 为「依赖型」风险（复杂度低，但被外部输入卡脖子）。

---

## 3. 三大实施阻碍项

### 3.1 角色 → 具体参数钉死（S3.1 / S3.2 前置）

13 个角色目前只有**叙事级**描述（R_HOT「近 30 天高 units」、R_STOCKOUT「available 很低」）。S3.2 之前必须转成具体生成参数区间（单量曲线、库存数值、分布/抽样规则）。这是 S3 最大的实现决策点，且必须保证：角色只是「生成标签」，**不变成预写死的风险结论列**（契约红线）。处理方式见决策点 3。

### 3.2 S3.5 依赖外部 Knowledge 稿

S3.5 是独立旁路模块，晚于主链开发即可。建议 S3.0–S3.4 期间把 S2 §9 的**元数据契约**当两份窗口间的接口锁死；用户 Knowledge 窗口按契约产出，本侧导入器即可消费。未到稿前 S3.5 以 stub 交付并记录「稿件阻塞」。

### 3.3 S3.6 校验边界：只验数据，不验 Tool

S3.6 只验证「数据层面路由**前置事实**齐备」（如 SC-OP05-001 所需：SKU 存在 + 有库存行 + 窗口内有销量 + 该店有 lead_time 配置），**不验证真实 `route_status`** —— 那依赖尚未存在的 Calculation Service，属 S4。此边界必须在 S3 阶段讲清，避免被误当成「能验证 Tool 正确性」。

---

## 4. 分阶段实施规划（过门制）

按 S2 §15.2 验收门执行；S3.2 内部拆三小段以降低单次改动面。

| 阶段 | 内容 | 过门条件（核查评估点） |
|------|------|------------------------|
| **P1 · S3.0 骨架** | 环境引导 + 目录 + CLI + profiles/seed/as_of | CLI 退出码 0；路径符合 S2 §10；dev/eval/full 可读入 |
| **P2 · S3.1 Master** | 主数据 + 角色 + Config（含 STORE_02 缺配置构造） | FK 自洽；两店隔离 ID；P0 StoreConfig keys + **Health 五核心维**正确；每角色 ≥1 SKU |
| **P3 · S3.2 交易主链**（内部 3.2a 订单 / 3.2b 物流 / 3.2c 库存，各带 mini-gate） | 90 天销售主链 + 三态物流 + 策略 B 快照 | 时间序抽样通过；R_STOCKOUT 等角色叙事可辨；无 Movement；mini-gate 依次过 |
| **P4 · S3.3 派生事实** | 售后 / 反馈 / 价格史 / 促销 | quantity 符合 §12A；反馈 ≥ 送达；价格史在 as_of 前且最新价 = 现价 |
| **P5 · S3.4 Scenario 绑定** | `scenarios.yaml` + 稳定 ID（仅 data 型） | 全部 data-SC 引用可解析；runtime_eval 仅挂前置 ID、不断言进程 |
| **P6 · S3.5 Knowledge 导入** | 导入器 + metadata 契约（embedding stub） | P0-Core ACTIVE 在 as_of 窗内；expired 可过滤；不改 DB 谓词；未到稿则记「稿件阻塞」 |
| **P7 · S3.6 校验骨架** | 数据层校验 + 报告 | 无 P0 级失败（S2 §11 清单，Movement 跳过） |
| **P8 · S3.7 eval 切片** | 同 seed + manifest 过滤 | eval 含全部黄金 SC 引用对象；与 dev 同 seed |
| **P9 · 收口** | dev+eval canonical 最终版 + 与 S4 交接边界声明 | 各表齐全、seed 可复现、明确「不导入、不建库」（属 S4） |

**阶段门禁规则（引用 S2 §15.4）：**
1. 每阶段结束：对照上表验收门做**核查与评估**（人工确认）。
2. **未过门不得进入下一阶段**（允许门内修 bug 重跑）。
3. 发现与 Frozen 冲突：停止扩 scope → 登记 → 用户拍板；不得静默改契约迁就脏数据。

**S3 实施状态（2026-09-18）**：P1–P9 **全部过门**；dev（21 表 / 21850 行）+ eval（21 表 / 226 行）双世界生成，validate 均 gate=PASS；53 项门禁测试通过、可复现；`data/generated/README.md` 为 S4 交接运行注记。

---

## 5. 已采纳的实施决策点（2026-09-17，用户拍板）

| # | 决策点 | 采纳方案 |
|---|--------|----------|
| 1 | Git / 仓库引导 | **是**：S3.0 前 `git init`；`.gitignore` 排除 `data/generated/` 等产物；代码以 `data/generator/` 为 Python package |
| 2 | Python 环境 | 独立 conda env（如 `ecommerce-agent`）；Python 3.10–3.12，以本机 Anaconda 可用版本为准 |
| 3 | 角色参数表 | **S3.1 结尾预置**「角色 → 参数区间」初值；S3.2 校验调参 |
| 4 | Canonical 输出格式 | **CSV 起步**（便于直接查看），Parquet 可选 |
| 5 | 时区存储 | **UTC 存储 + 按店本地（Asia/Shanghai）解释** |
| 6 | S3.5 等待策略 | **导入器先行**（契约 + stub embedding），Knowledge 稿到位再灌 |

---

## 6. 明确不做 / 后置（防 scope 蔓延护栏）

`profile=full`、Inventory 策略 A（进销存流水）、`runtime_eval` harness、embedding 调优、课设 Hive/S5 导出 —— 均**后置**，S3 不碰。

---

## 7. 与 S4 的交接边界（S3 完成后）

**S3 已交付（2026-09-18）**
- `data/generated/dev|eval/canonical/`（21 张表，DB §13 列级一致；dev 21850 行 / eval 226 行）
- `data/scenarios/eval/scenarios.yaml`（33 条黄金 SC：nature / expected_route / 引用）
- `data/generated/dev|eval/validate_report.json`（S3.6 校验，均 gate=PASS、无 P0 失败）
- `data/generated/README.md`（S4 交接运行注记）

**S4 负责（S3 不做）**
- 导入 PG / 建库 / 接 Tool / Calculation Service
- 真实 `route_status` 验证（SC 期望路由 → 跑 Tool 断言）
- `runtime_eval` SC 的 harness（HITL / 故障注入 / 知识 mock；RULE_CONFLICT 断言归 S4）
- embedding 生成（S3.5 为 stub，chunks 无 embedding 列）
- 权限矩阵 / 审计 / 审批（实现层）

**刻意后置（不在 V1 S3）**：profile=full、Inventory 策略 A（进销存流水）、embedding 调优、runtime harness、课设 Hive/S5 导出。

**双项目边界**：课设仓库可复制 `canonical` + 同一 generator；Agent 不依赖 Hive（AGENTS §15）。

---

## 8. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-17 | 首版：S3 分阶段实施规划、风险/改动量/难度/阻碍项分析、过门制、实施决策点落定 |
| V1.1 | 2026-09-18 | S3 实施完成：P1–P9 全部过门；dev+eval 双世界生成、validate PASS；§7 扩展为 S4 交接边界声明 |

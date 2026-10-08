# E-commerce Business Copilot — 项目修复规划 V2（V1.3 终稿）

> 文档性质：**实施前方案**（分析/规划，非代码改动）
> 版本：**V1.3**
> 日期：2026-10-08
> 状态：**Done（P0~P7 全部实施完成并验收）**
> 范围：**统一修复**（不按投递分轮），全量问题 S1→S4 顺序解决
> 上游：三轮审查（设计文档 / 实现代码 / 测试评测）+ 并行核对窗口意见（已逐条吸收）+ 作者独立复核
> 关联：docs/agent-plan-b-react-v1.md（D9 授权边界）、docs/evaluation-plan-v1.md（M1~M8 冻结）、docs/agent-runtime-v2-spec-v1.md（Spec B5 已同步 V0.3）、AGENTS.md（跨窗口纪律）
> V1.0→V1.1 变更：① 记录全部决策拍板（P0-3=方案 B；P0-1/P0-2=HTTP 入口 token 版；D-1=以实跑为准；P2-7=解决；文档同步=授权；实施节奏=统一不分工期）；② 逐问题补全「修复操作 / 风险阻碍 / 涉及文件与现状」；③ 新增一手核实点：docker-compose（5434/ec/ec_secret）、runtime_schema（session 表 10 列无 token）、predicates.FACTS（全 None 关键词）、M4 gold 读取路径、M7 定义未实现观察；④ P2-3 定性修正；⑤ R-1 精确化（Ollama 为查询期依赖）。
> V1.1→V1.2 变更（吸收并行审查窗口 4 项意见 + 作者复核）：① **D-1 补 M8 报告提交**（`--mode baseline` → `reports/m8_*.json`，README M8 表"85%→100%/81.8%→100%"同样需要报告背书）；② **P0-1/P0-2 钉死会话创建契约 = option b+**（懒创建于首次调用、服务端签发 token 且每个响应回传、既有会话 store/user 以服务端为准、审批/切换需 token 且 user==owner、首轮为信任引导如实声明）；③ P2-7a 措辞修正为"M2（M3 走 Trace Invariant 不依赖 check_facts，已核实；M7 本轮未实现）"；④ P0-2 补 `copilot/api/static/index.html`（store 下拉每次携带 store_id，HTTP 路径客户端可控的现实入口）与 `web/api.py:26` 复用点。

---

## 0. 决策记录（全部已拍板）

| 决策点 | 结论 |
|---|---|
| 实施节奏 | **统一修复**，不按投递分轮；S1→S4 按依赖顺序全部完成 |
| P0-3 | **方案 B**：能力切换并入 pending→confirm 两步确认 |
| P0-1 / P0-2 | **推荐设计（已采纳）**：HTTP 入口 token + 服务端会话锁定 + 审计双字段（详见 §5.2） |
| 会话创建契约 | **option b+（已定，见 §5.2）**：懒创建于首次调用 + 服务端签发 token 且每个响应回传 + 既有会话 store/user 以服务端为准 + 审批/切换需 token 且 user==owner + 首轮为无认证下的信任引导（README 如实声明） |
| D-1 | **以实跑为准**；简历/README 与 `reports/*.json` 严格一致 |
| P2-7 | **解决**：check_facts 值校验 + M4 doc_id 判定；接受数字可能略降 |
| 文档同步 | **授权**：修复后文档必须与实施/真实状态一致（Spec B5、计数、README、Business §1.4、react.py 文档串） |
| 实施边界 | 见 §3（9 条不做） |

---

## 1. 结论摘要

三轮审查 + 并行核对 + 独立复核后确认：**P0 三件套（审批代批 / store 信任边界 / 文本能力自提升）与 D 组数字背书均为真实缺陷，严重度判断准确**；P2-3 定性已据实下调；R-1 精确为"运行期依赖 Ollama"。方案整体可采纳，按 S1→S4 统一实施。

---

## 2. 实施目标（可验收）

1. **安全边界诚实且经得起追问**：审批凭证化（代批需持有会话 token）、store/user 服务端锁定、能力切换统一"请求→确认"两步；README 补 demo 边界声明（D9 措辞）。
2. **数字可背书**：README/简历 M1~M8 == `reports/*.json` 实跑；`baseline.py` 无硬编码；评测计划（含 M7）与实现状态口径对齐。
3. **评测判定站得住**：check_facts 值校验生效、M4 用 doc_id 判定，判定器强度与简历"Task Success / 多维评测"表述匹配。
4. **可复现**：README 补全 `docker compose → import → embed → pytest → eval` 链路；密钥/地址收敛到 env。
5. **工程卫生**：P2 全部收口、工作树干净、文档漂移清零、P1 缺陷项（500/连接泄漏/超时）修复。
6. **回归全绿**：环境就绪后 204 项全过；每项修复有对应测试。

---

## 3. 实施边界（不做，防越界）

1. **不做完整认证/RBAC/管理员审批制**——用"会话凭证(token)+所有权绑定+审计双字段"替代，语义仍是单用户 demo。
2. **不改 Frozen 契约业务定义**（Business/Tool/Database/RAG/Workflow 核心口径不动）；只做已授权的文档同步。
3. **不做架构级重构**：`react.py` 分层、双入口适配层合并（P1-1a）、路由映射三处去重（P1-3）、legacy 删除——记为"未来项"，本轮不碰。
4. **不新增未实现工具/能力**（search_products/query_sales_metrics 等 20 Core 缺口）。
5. **不改评测指标定义**（M1~M8 冻结）；P2-7 属于实现修正（判定器/标识方式），不触碰指标语义。
6. **不引入新基础设施**（Redis/Kafka/第二库/CI）。
7. **不扩 V1 范围**（C 端/Admin/流式数仓）。
8. **守跨窗口纪律**：定向 git add；改共享文件（react.py/context.py/toolkit.py/api 入口）前先 `git status` 确认。
9. **本轮不实现 M7 指标本体**（计划已定义 P0.5、代码未实现）——只做文档口径对齐；是否实现另议。

---

## 4. 问题全量清单 + 执行顺序

| 顺序 | 编号 | 问题 | 级别 | 核实 |
|---|---|---|---|---|
| S1 | R-1 | 环境不可复现（Docker PG+Ollama **查询期**依赖） | 可复现 | ✅ 已读 |
| S2 | P0-1 | 审批可代批（入口无凭证 + approver_id 错位） | P0 | ✅ 代码实读 |
| S2 | P0-2 | store_id/user_id 客户端可控 | P0 | ✅ 代码实读 |
| S2 | P0-3 | 文本能力自提升（方案 B） | P0 | ✅ 代码实读 |
| S3 | P2-7a | check_facts 断言弱（bool/int 值不校验；FACTS 仅关键词） | P2 | ✅ 代码实读 |
| S3 | P2-7b | M4 相关性=标题字符串相等 | P2 | ✅ 代码实读 |
| S3 | D-1 | M2=78/78 无报告背书；baseline.py 硬编码 | 背书 | ✅ 报告实读 |
| S3 | D-2 | 测试计数漂移（175 vs 204） | 背书 | ✅ 已读 |
| S4 | P2-4 | 文档漂移（Spec B5 / react.py 文档串 / Business §1.4） | P2 | ✅ 已读 |
| S4 | R-1d | README 复现链路 + demo 边界声明 | 文档 | — |
| S4 | P2-1 | 配置未收敛（明文口令/硬编码） | P2 | ✅ 已读 |
| S4 | P2-2 | 写路径：手写主键/audit 撞键/item 归属未校验 | P2 | ✅ 已读 |
| S4 | P2-3 | 3 处裸 except:pass（1 处文档化降级）→ 收敛+日志 | P2 | ✅ 修正后属实 |
| S4 | P2-5 | `--set safety` 死选项 | P2 | ✅ 已读 |
| S4 | P2-6 | web/app.py 未提交 | P2 | ✅ git |
| S4 | P1-2 | react.py 工具调用无 try/except → 500 | P1 | ✅ 已读 |
| S4 | P1-4 | db.py 无超时/autocommit；web/api.py 连接泄漏 | P1 | ✅ 已读 |

---

## 5. 逐问题详析（问题 / 根因 / 修复操作 / 风险阻碍 / 涉及文件与现状）

### 5.1 S1 · R-1 环境基线（所有验证的前提）

- **问题/根因**：204 项测试中约 46 项纯函数无依赖，其余依赖 Docker PG(5434)+dev/eval 数据；RAG 测试（`test_rag.py` 10 项）与 M4 评测在**查询期**依赖 Ollama（`copilot/rag.py:80` `search_knowledge` 内 `embed_texts`——非仅摄取阶段，`test_rag.py:1` docstring 自证）。本机 Docker 未启动、5432 有另一 PG（端口漂移）、Ollama 未启动。
- **修复操作**：`docker compose -f db/docker-compose.yml up -d` → `python db/import_data.py --profile dev` / `--profile eval` → `python db/embed_knowledge.py`（Ollama bge-m3）→ 全量 `pytest` 确认 204 全绿。
- **涉及文件与现状**：`db/docker-compose.yml`（5434→容器 5432、`pgvector/pgvector:pg16`、ec/ec_secret/ec_copilot、卷 ec_pgdata，`down -v` 可重置）；`db/import_data.py`（`--profile dev|eval`、默认 port 5434）；`db/embed_knowledge.py`（写 5434）；`data/generated/dev|eval/canonical/*.csv` 已入库；`copilot/config.py:8` `DB_DSN` 硬编码（见 P2-1）；`.env` 有 key、注释 GBK 乱码。
- **风险阻碍**：Docker Desktop 未运行；Ollama 需拉 bge-m3；数据导入幂等/可重置；**此步最依赖真实环境，应最先做**。

### 5.2 S2 · P0 三件套

#### P0-1 审批可代批（推荐设计已采纳）

- **问题/根因**：`copilot/api/app.py:35-41` `resume` 裸收 + `:69-101` 无鉴权；`copilot/agent/toolkit.py:230` `approver_id=ctx.user_id` 取当前调用者；Business §2.4 / Spec §4.4"本人二次确认"从未被绑定。
- **修复操作**：① `runtime.session` 增加 `session_token` 列（DDL）；② `/api/session` 创建即落库 `{owner_user_id, store_id, token}` 并返回 token；③ `/api/agent` 收到 `resume`/`capability_replay` 时校验 `token 匹配 且 user==owner`，否则 403；④ workflow 工具 interrupt 值携带 `operator_user_id`，建单/审计落 `initiator_user_id`+`approver_id` 双字段；⑤ 新增测试（错 token / 他人 user resume → 拒绝）。
- **涉及文件与现状**：`copilot/api/app.py:62-67`（`/api/session` 只返回 uuid 不落库）、`:69-101`（`/api/agent` 无校验）；`copilot/runtime/store.py:21-34`（`create_session` 无 token）；`db/runtime_schema.sql:8-19`（session 表 10 列，**无 token 列**）；`copilot/agent/toolkit.py:216-231`（interrupt 值无 operator 字段）；`copilot/tools/create_return_request.py:96-97,104`（`requested_by=ctx.user_id`、`approver_id=approval[...]` 已分列，来源不可信）；`web/api.py`（进程内路径，**不需要 token**——HTTP 边界校验原则）。
- **风险阻碍**：DDL 需重建 dev 库或 ALTER；单用户 demo 下 owner 校验恒真（诚实性靠文档声明）；写路径改动需环境实测建单/幂等/审计。
- **不推翻 M6 声明**：M6"审批绕过 0%"测图内部（LLM 无法绕过 interrupt），"代批"在图外部 API 入口——面试两层分开讲。

#### P0-2 store_id/user_id 客户端可控

- **问题/根因**：`api/app.py:38-39` store_id/user_id/workspace_mode 全在请求体；`react.py:491-494` 直接用客户端 session。跨店查询（D7 方向 A，`tool.py:134-155`）是**设计**；"客户端能声明店号"是**缺口**（前缀守卫 `tool.py:87-108` 只拦引用店≠ctx 店）。
- **修复操作**：与 P0-1 合并——`/api/agent` 的 store_id/user_id 取自服务端会话记录，忽略请求体；workspace_mode 保持客户端可控但只走确认路径（P0-3）；web 路径同步从服务端会话取 store（进程内一致）。
- **涉及文件与现状**：`api/app.py:35-41,71-72`（直接用请求字段拼 session）；`web/api.py:61-79`（session 由调用方拼装）；`runtime/store.py:37-43`（`get_session` 可复用）；`db/runtime_schema.sql:8-19`（session 已有 user_id/store_id 列）；**`copilot/api/static/index.html:26-29,70,85,100-112`（store 下拉每次请求携带 store_id——HTTP 路径"客户端可控"的现实入口，token 设计须传播到此 JS 客户端：创建/每个响应回传 token、后续请求携带）**；`web/api.py:26`（会话列表已查 store_id，S2 可复用为服务端 store 来源）。
- **会话创建契约（已定：option b+）**：① 会话**懒创建于首次调用**（`/api/agent` 收到未知 session_id 或 `/api/session` 显式创建），服务端生成 `session_token`（`secrets.token_hex(16)`）与 `owner_user_id`/`store_id` 一并落 `runtime.session`；② **每个 `/api/agent` 响应回传 `session_token`**（客户端存储；即使首响应为 approval_required 也能拿到 token 供 resume）；③ 既有会话的后续调用必须携带匹配 token，store_id/user_id 以服务端记录为准（请求体忽略）；④ `resume`/`capability_replay` 额外要求 `user==owner`；⑤ **首轮 store/user 为客户端声明**（无认证下的信任引导），README demo 边界如实声明；⑥ web 路径（NiceGUI 进程内）不强制 token，属进程内信任边界，但会话记录同样经 runtime/store 落库保持一致。
- **风险阻碍**：改双入口 + UI 会话恢复（`web/app.py` load_conversation/会话列表）+ **static JS 客户端（index.html）**；**Spec B5 文档矛盾需同步**（`agent-runtime-v2-spec-v1.md:41`"跨 store 读取一律 FORBIDDEN" vs 方向 A）；首轮声明语义必须在 README 讲清。

#### P0-3 文本能力自提升（方案 B）

- **问题/根因**：`context.py:79-95 capability_domain_switch` + `react.py:254-259`：无 pending 时"确认意图+显式域"一句话直切 + `capability_replay` 重跑，绕过"提议→确认"。
- **修复操作（方案 B）**：命中"切换到运营"且无 pending → **不直切**，置 `capability_pending={domain, original_message}` → 下一轮用户输入确认词（复用 `capability_text_decision`）才切；同步改 `test_react.py:327 test_capability_domain_switch` 与 `:422 test_resolve_text_switch_no_pending_explicit_domain` 断言为"两步语义"；新增"第二步确认才切"测试。
- **涉及文件与现状**：`copilot/context.py:79-95`（直切）；`copilot/agent/react.py:236-262`（`resolve_text_action` 末段）；`test_react.py:327,422`（断言直切成功）；`:137-162` 审批文本路径不受影响。
- **风险阻碍**：改 2 个现有断言；需确认审批文本确认（`test_resolve_text_approval_confirm_reject`）不回退。

### 5.3 S3 · 评测强化与数字背书

#### P2-7a check_facts 断言弱

- **问题/根因**：`judgments.py:50-78 check_facts`——`bool`/`int/float` 值只查 label 出现、**不校验值**；当前 `predicates.py:183-203` 的 `FACTS` 全部是 `None` 值（仅关键词出现），故 M2 的 Final Answer Fidelity 实际是"答案含结论关键词"，数值/布尔分支空转。
- **修复操作**：① check_facts 增加值校验（数字解析比对、布尔语义判定），非 None 值必须匹配；② 按需把关键 SC 的 FACTS 升级为带值事实（如风险等级/异常布尔，标注工作）；③ 单测补值校验用例。
- **涉及文件与现状**：`copilot/eval/judgments.py:50-78`；`copilot/eval/predicates.py:183-208`（全 None 关键词）；`test_eval_judgments.py:206`。
- **风险阻碍**：**强化后 M2 通过率可能下降**（更真实）——已接受，与 D-1 一次重跑联动（**核实**：`check_facts` 仅被 M2 谓词 cs06/cs08 调用，`predicates.py:25,39,57,59`；M3 走 Trace Invariant `judge_m3_trace` 不依赖 check_facts；M7 本轮未实现，故实际受影响指标为 **M2**）；offline Phase A（fake 预设正确行为）应仍 100%（验证 harness 自洽）。

#### P2-7b M4 相关性=标题字符串相等

- **问题/根因**：`judgments.py:176-193 judge_m4_retrieval`——`hit5 = bool(acceptable_docs & {r["title"]...})` 用**标题字符串**判定；gold 与检索同用标题，"知道答案再查"近似，标题歧义失真。
- **修复操作**：`data/eval-cases/rag_gold.yaml`（30 条，M4 专用，读者仅 `runner.run_offline_m4`——已确认）的 `acceptable_docs` 改为 `acceptable_doc_ids`（或 id+title 双字段）；judgments 与 runner 用 `search_knowledge` 返回的 `document_id`（`rag.py:69-72` 已带）比对；gold 重标。
- **涉及文件与现状**：`data/eval-cases/rag_gold.yaml`（标题列表）；`copilot/eval/judgments.py:176-193`；`copilot/rag.py:56-73`（`_select_rows` 已输出 document_id）；`data/eval-cases/rag_gold_v1.yaml`（Correctness 冻结副本，**不动**）。
- **风险阻碍**：gold 重标 30 条；迁移纪律（改共享数据须同一提交内枚举读者+重跑+记修订，`evaluation-plan-v1.md:61-65`）。

#### D-1 / D-2 数字背书与计数

- **问题/根因**：README/简历 M2=78/78 无报告背书（`reports/eval_metrics_m2m3_20260930_182727.json` 最好 75/78=96.15%）；`baseline.py:52` 硬编码 78/78/36/36；docs/AGENTS=175 vs HEAD=204。波动序列有实据：61/78→75/78→修复后 78/78。
- **修复操作**：① `baseline.py` 改读报告或实跑，去占位；② **live 重跑**（含 P2-7 强化后判定）出最终真实数字 → 提交 `reports/*.json`；③ **`--mode baseline` 实跑 M8 并提交 `reports/m8_*.json`**——README M8 对比表"能力覆盖率 85%→100%、Task Success 81.8%→100%"是简历最强的架构叙事，同样需要报告 JSON 背书（当前 `reports/` 仅 2 份 M1/M2/M3/M4 报告，无 M8；`eval_metrics._baseline()` 目前只打印不落盘）；④ 同步 README/简历；⑤ 计数统一为"当前 HEAD 的 pytest 实数"。
- **涉及文件与现状**：`copilot/eval/baseline.py:47-54`（react 侧字典硬编码）；`reports/`（2 份 JSON：M2 61/78 与 75/78；无 M8 报告）；`AGENTS.md §18.5`（"当前 175"过期）；`evaluation-plan-v1.md`（头部 175）；`README.md:27-28`（写 78/78/204）。
- **风险阻碍**：live 随机性（可能 76/78）；依赖 S1 环境与 Ollama；**M2 最终值以实跑为准，简历措辞随之定**。

### 5.4 S4 · 文档与卫生组

| 项 | 修复操作 | 涉及文件与现状 | 风险 |
|---|---|---|---|
| P2-4 文档漂移 | Spec B5 改"读放开+source_store、写 FORBIDDEN"；react.py:1 文档串改"ReAct 默认"；Business §1.4 架构图更新 | `agent-runtime-v2-spec-v1.md:41`、`react.py:1`、`business-scenarios-v1.md:36-48` | 已授权；改后与代码一致 |
| P2-1 配置收敛 | `config.py` 的 DB_DSN/AS_OF_DATE 支持 env 覆盖，缺省回落；`rag.py:18` OLLAMA_URL 同；`.env.example` 补注释 | `config.py:5,8`、`rag.py:18`、`.env`(GBK 乱码) | 低 |
| P2-2 写路径 | audit 独立 ID 语义（避免 `next_id+1` 与业务表共空间）；`:61-64` 校验 `item.order_id==order_id` | `create_return_request.py:86,104,61-64`（已有 LOCK TABLE 防并发） | 需环境实测建单/幂等/审计 |
| P2-3 静默降级 | 3 处裸 except（`react.py:231/260/289`）加日志或显式注释；保留文档化降级 | `react.py:231,260,289` | 低 |
| P2-5 死选项 | `--set safety` 接线（跑 `safety_scenarios.run_structural_safety`）或删选项 | `scripts/eval_metrics.py:86,98` | 低 |
| P2-6 工作树 | `web/app.py` 未提交改动——**实施前先 `git status` 确认无他窗口改动**，再确认提交或回退（定向 add） | git `M web/app.py`（UI 空态重构中，并行窗口在改；`web/api.py:26` 会话 store 徽章可复用） | 跨窗口纪律 |
| P1-2 | `react.py:374 t.invoke(args)` 加 try/except → 结构化 error（对齐 `tool.py` 语义）；`api/app.py` 补兜底（与 `web/api.py:93-98` 一致） | `react.py:374-376`、`api/app.py:69-101` | 需回归工具调用路径 |
| P1-4 | `db.py` connect 加 timeout/autocommit 显式；`web/api.py:23` 修复连接泄漏 | `db.py:12-16`、`web/api.py:21-27` | 低 |
| R-1d | README 补全复现链路 + demo 边界声明（D9 措辞） | `README.md` | 低 |

**补充观察（记录不实施）**：评测计划定义 M7（P0.5）但代码未实现（eval 模块仅 m1/m3/m2/m4+latency+M6 结构性+M8）——简历未声称 M7，仅需文档口径对齐。

---

## 6. 阻碍项总表

| # | 阻碍 | 影响 | 缓解 |
|---|---|---|---|
| 1 | 环境（Docker 未起 / 5434 端口漂移 / Ollama 未起 / bge-m3 未拉） | S1 卡住则 S3 重跑无法进行 | S1 最先做；Ollama 起不来则 D-1 先用报告现值、P2-7 离线部分仍可推进 |
| 2 | P0-1 的 DDL（session_token 列） | 需重建 dev 库或 ALTER | 本项目可 `down -v` 重建；文档记录迁移 |
| 3 | P2-7 强化 + D-1 重跑会改变最终数字 | 简历措辞需随之定 | 以实跑为准，先出数再改简历 |
| 4 | 双入口 + UI 会话逻辑改动面（P0-1/P0-2） | 可能破坏 UI | 每步回归 + web/api 双入口冒烟 |
| 5 | 跨窗口协作（工作树未提交 web/app.py；共享文件） | 收走/回滚他人改动 | 每步前 git status；定向 add |

---

## 7. 执行顺序与门禁（S1→S4）

- **S1 环境基线** → 门禁：`pytest` 204 全绿。
- **S2 P0 三件套** → 门禁：P0 新增/更新测试通过 + 全量回归绿 + web/api 双入口冒烟。
- **S3 评测与背书** → 门禁：offline Phase A 自洽 100% + live 重跑出最终数字 + 报告提交 + baseline 无硬编码。
- **S4 文档与卫生** → 门禁：全量回归绿 + 文档与代码一致 + 工作树干净 + README 复现链路完整。

每步小步提交（定向 git add），遵循 AGENTS.md"小步、可验证、不扩 scope"。

---

## 8. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-10-08 | 首稿：三轮审查整合 + P0/D 组详析 + 目标/边界 + S1~S4 顺序 |
| V1.1 | 2026-10-08 | **决策全部拍板**（P0-3 方案 B、P0-1/P0-2 HTTP token 版、D-1 实跑为准、P2-7 解决、文档同步授权、统一实施）；逐问题补全操作/风险/文件现状；新增一手核实（docker-compose / runtime_schema / FACTS / M4 gold / M7 未实现观察）；P2-3 修正；R-1 精确化 |
| V1.2 | 2026-10-08 | 吸收并行审查窗口 4 项意见（作者逐条复核）：① D-1 补 M8 报告提交与 README M8 表背书；② 钉死会话创建契约 option b+（懒创建 + token 每响应回传 + 服务端锁定 + resume 需 token&owner + 首轮信任引导）；③ P2-7a 措辞修正为 M2（核实 check_facts 仅 M2 用、M3 走 Trace Invariant、M7 未实现）；④ P0-2 补 index.html 客户端与 web/api.py:26 复用点；⑤ P2-6 补实施前 git status 纪律 |
| V1.3 | 2026-10-08 | **P0~P7 全部实施完成并验收（Done）**：① P0 环境基线（Docker PG+Ollama+dev 数据，212 基线）；② P1 方案 B 两步切换；③ P2 会话凭证 option b+（HTTP 入口 token + 服务端锁定 + 审计双字段）；④ P3 check_facts 值感知 + M4 doc_id；⑤ P4 数字背书（live 重跑 M1 135/135·M2 78/78·M3 36/36·M4 22/22，M8 报告入库，README/简历同步）；⑥ P5 文档同步（Spec B5/react.py 文档串/Business §1.4/README 复现链路+demo 边界）；⑦ P6 卫生收口（配置收敛/写路径加固/日志/safety 接线/连接泄漏）；⑧ P7 最终验收（212 回归 + 12 项冒烟全过 + 文档一致性 11/11 + 统一提交）。验收记录见 §9 |

---

## 9. 验收记录（P0~P7，2026-10-08）

| 阶段 | 门禁判定 | 关键证据 |
|---|---|---|
| P0 环境基线 | ✅ | 204→212 基线全绿；Docker PG(5434)/Ollama bge-m3/dev 数据就绪；双入口导入冒烟 |
| P1 两步切换 | ✅ | test_react 29 过；211 回归；"切换到运营"不再直切（方案 B） |
| P2 会话凭证 | ✅ | 6 新测试过；211→212 回归；**端到端冒烟：代批错 token→403、自批持 token 建单+审计双字段** |
| P3 判定强化 | ✅ | 评测单测 29 过；offline Phase A 100%（M4 22/22 与历史一致）；212 回归 |
| P4 数字背书 | ✅ | **live 重跑 M1 135/135·M2 78/78·M3 36/36·M4 22/22·MRR 0.833**；M8 legacy 18/22 vs ReAct 78/78；报告入库（git add -f，reports/ 被 ignore）；README/简历口径同步；计数 175→212 |
| P5 文档同步 | ✅ | Spec B5/react.py 文档串/Business §1.4/README 复现链路+demo 边界/db README；212 回归 |
| P6 卫生收口 | ✅ | 配置 env 覆盖实测；写路径加固（item 归属+audit 独立 ID）；日志收敛；safety 接线（Block 100%/Exec 0/Bypass 0）；连接泄漏修复；**P1-2 GraphInterrupt 回归当场定位修复**；212 回归 |
| P7 最终验收 | ✅ | 212 回归；**冒烟 12/12**（token/store 锁定/两步切换/跨店标注/代批 403/审计双字段）；**文档一致性 11/11**（README↔报告↔代码）；统一提交 |

**最终指标（当前 HEAD，2026-10-08）**：212 项测试全绿；M1 135/135·M2 78/78·M3 36/36·M4 Hit@5 22/22/MRR 0.833/拒答 6/6/冲突 2/2；M5 P50 2.0~2.5s / P95 4.1~4.8s；M6 Block 100%/Unauthorized Execution 0%/Approval Bypass 0%；M8 Coverage 85%→100%、Task Success 81.8%→100%（world=dev，报告 `reports/eval_metrics_20261008_212207.json` + `reports/m8_20261008_213542.json`）。

# E-commerce Customer Service & Operations Copilot Agent

面向**内部客服 / 运营人员**的电商业务 Copilot：一个由 LLM 编排、确定性工具裁定事实、HITL 兜底高风险操作的业务 Agent。
核心架构故事：**从 Intent Router（12 意图闭集 + Registry 固定映射）演进为 LLM Tool-Orchestrator（LLM 看工具目录自主编排 + 确定性工具产出结论）**。

## 技术栈

Python / LangGraph（自建 StateGraph ReAct 循环）/ DeepSeek / PostgreSQL + pgvector / FastAPI / NiceGUI / bge-m3

## 架构（5 模块）

```
① Agent Runtime    自建 StateGraph ReAct（model→tools→条件路由→finalize），AgentState 四分区，
                   working_context 实体覆盖规则，PostgresSaver 断点续跑
② Business Tools   10 直连 + 2 审批 workflow + request_capability（能力协商），Workspace Mode 目录过滤
③ RAG/Knowledge    23 篇多格式文档 → 章节结构切块 → bge-m3 1024 维 → pgvector；
                   生命周期/scope/store 过滤 + 权威等级冲突消解 + 生成式答案带引用
④ Workflow/HITL    CS-08 退货 / OP-05 补货：资格三态 → interrupt 人审 → Action + 审计 + 幂等
⑤ Eval/Observability  本仓库评测体系（下）
```

## V1 Demo 安全边界（诚实声明）

单用户 Demo，**无真实认证 / RBAC**（生产形态由 **Auth / RBAC 在 Agent 外部**完成硬过滤，LLM 无法改变能力边界）：

- 会话创建（首轮）由客户端声明 `store_id` / `user_id` 并**服务端锁定**（`runtime.session` 持会话凭证 `session_token`）；
- 审批确认 / 能力切换需持有该会话凭证（proof of possession，**非认证**）；
- 能力切换（Workspace Mode）为「请求 → 用户确认」两步，LLM 只建议不授权；
- 跨店读放开并标注 `source_store`，跨店写 FORBIDDEN。

## 评测（四层）

> 可复现：DeepSeek-chat / temperature=0 / as_of=2026-09-17 / 数据集 v1.2.3 / world=dev / live repeat=3。
> 判定函数纯函数化 + fake LLM 离线 100% 验证后再上 live（三模式预热后正式样本计 P95）。
> 数字均出自提交报告 `reports/eval_metrics_20261012_200656.json`（M1~M5）与 `reports/m8_20261012_205725.json`（M8），metadata 记完整 commit SHA + worktree=clean + world=dev；旧报告见 `*_HISTORICAL.json`。

### Correctness — 功能正确性
- **212 项自动化测试通过**（当前 HEAD 实测；确定性断言 + SC 26 业务场景 + M6 结构性安全）
- SC 26 条 data 场景确定性全过；G2/G3/G5/G6 live 场景验证

### Effectiveness — 效果
| 指标 | 结果 |
|---|---|
| Tool Plan Accuracy（M1，严格判定：multi_tool 必需全调） | **100%**（135/135，45/45 case-stable） |
| Task Success（M2，业务结果+约束+副作用+答案保真四层谓词） | **100%**（78/78，26 SC × repeat 3） |
| Conditional Multi-hop / Early Stop（M3，轨迹不变量+条件判定） | **100%**（36/36，12 场景 × repeat 3） |
| RAG Hit@5（M4，22 可答问题 doc 级判定） | **100%**（22/22） |
| RAG MRR@10（M4） | **0.833** |
| RAG Correct Abstention / Conflict Resolution（M4） | 6/6 / 2/2 |

### Performance — 性能（M5，per-workload P95）
| Workload | P50 | P95 |
|---|---|---|
| 工具调用（M1） | 2.3s | 5.2s |
| 任务完成（M2） | 2.6s | 4.7s |
| 条件多跳（M3） | 2.8s | 6.0s |

> per-workload P95（各自样本池排序）；warm 图、单机 Demo 环境，含模型 API 网络耗时，不代表生产性能。

### Safety — 安全（M6，结构性 + 测试证据）
- **Unauthorized Execution Rate = 0%**（runtime 对目录外工具强制拦截）
- **Approval Bypass Rate = 0%**（T-X-01 不暴露给 LLM，审批必经 interrupt）
- **Block Rate = 100%**（越权尝试全部被拦截）
- Missing-slot Hallucination：缺参必反问，不编造标识符（R4 红线）

### 架构演进对比（M8：Legacy Router vs ReAct，同 benchmark）
| 维度 | Legacy（Intent Router，live LLM 路由） | ReAct（Tool-Orchestrator） |
|---|---|---|
| Coverage（可处理场景，同 26 集） | 22/26（85%，含 4 个 LLM 路由传参崩溃） | **26/26（100%）** |
| 业务结果通过率（共同 22 场景 × 3，同分母 66） | 54/66（81.8%） | **66/66（100%）** |
| Conditional Multi-hop | N/A（结构性无） | **36/36（100%）** |

> M8 同口径说明：legacy 为 live LLM 路由（非确定性），3× 为独立运行（fresh thread）；4 个不支持 SC 为 LLM 路由传参导致的 datetime 崩溃（真实缺陷）。react 侧业务通过率由官方 M2 全谓词报告推导（facts_on=True ⊇ facts_on=False，更严）。表述纪律：同场景系统版本对比，非严格因果实验。

## 快速开始

```bash
# 1) 起 PG + pgvector（宿主 5434）
docker-compose -f db/docker-compose.yml up -d

# 2) 建表（两份 DDL）+ 导入 dev 数据 + 知识向量（需 Ollama bge-m3 运行，localhost:11434）
docker exec -i ec-copilot-pg psql -U ec -d ec_copilot -v ON_ERROR_STOP=1 < db/schema.sql
docker exec -i ec-copilot-pg psql -U ec -d ec_copilot -v ON_ERROR_STOP=1 < db/runtime_schema.sql
python db/import_data.py --profile dev
python db/embed_knowledge.py

# 3) 起界面（二选一）
python -m web.main                        # NiceGUI 工作台 http://127.0.0.1:8000
python -m copilot.api.app                 # FastAPI + 静态页 http://127.0.0.1:8000

# 4) 测试与评测
python -m pytest                          # 212 项（当前 HEAD 实测）
python scripts/eval_metrics.py --mode offline       # 离线 Phase A（fake 自洽 100%）
python scripts/eval_metrics.py --mode live --repeat 3 --out reports/eval_metrics_<ts>.json
python scripts/eval_metrics.py --mode baseline      # M8 legacy vs ReAct
```

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

## 评测（四层）

> 可复现：DeepSeek-chat / temperature=0 / as_of=2026-09-17 / 数据集 v1.2.3 / live repeat=3 取均值。
> 判定函数纯函数化 + fake LLM 离线 100% 验证后再上 live。

### Correctness — 功能正确性
- **204 项自动化测试通过**（确定性断言 + SC 26 业务场景 + M6 结构性安全）
- SC 26 条 data 场景确定性全过；G2/G3/G5/G6 live 场景验证

### Effectiveness — 效果
| 指标 | 结果 |
|---|---|
| Tool Plan Accuracy（M1） | **100%**（135/135，45/45 case-stable） |
| Task Success（M2） | **100%**（78/78，26 SC × repeat 3） |
| Conditional Multi-hop / Early Stop（M3） | **100%**（36/36） |
| RAG Hit@5（M4） | **100%**（22/22） |
| RAG MRR@10（M4） | **0.833** |
| RAG Correct Abstention / Conflict Resolution（M4） | 6/6 / 2/2 |

### Performance — 性能（M5，池化样本）
| Workload | P50 | P95 |
|---|---|---|
| 工具调用（M1） | 2.0s | 4.6s |
| 任务完成（M2） | 2.1s | 4.1s |
| 条件多跳（M3） | 2.4s | 4.4s |

### Safety — 安全（M6，结构性 + 测试证据）
- **Unauthorized Execution Rate = 0%**（runtime 对目录外工具强制拦截）
- **Approval Bypass Rate = 0%**（T-X-01 不暴露给 LLM，审批必经 interrupt）
- **Block Rate = 100%**（越权尝试全部被拦截）
- Missing-slot Hallucination：缺参必反问，不编造标识符（R4 红线）

### 架构演进对比（M8：Legacy Router vs ReAct，同 SC 26 业务结果）
| 维度 | Legacy（Intent Router） | ReAct（Tool-Orchestrator） |
|---|---|---|
| Coverage（可处理场景） | 85%（22/26，含 4 个 datetime 崩溃） | **100%**（26/26） |
| Task Success（业务口径） | 81.8%（18/22） | **100%**（78/78） |
| Conditional Multi-hop | N/A（结构性无） | **100%**（36/36） |

## 快速开始

```bash
docker-compose -f db/docker-compose.yml up -d        # PG + pgvector
C:/Users/HSY20/.conda/envs/ecommerce-agent/python.exe -m web.main   # NiceGUI 界面 http://127.0.0.1:8000
C:/Users/HSY20/.conda/envs/ecommerce-agent/python.exe scripts/eval_metrics.py --mode offline  # 评测
```

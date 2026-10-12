# 简历项目文案定稿（P8 最终数字，2026-10-12）

> 所有数字对应提交报告 `reports/eval_metrics_20261012_200656.json`（M1~M5）与
> `reports/m8_20261012_205725.json`（M8），可逐项复现。可直接粘贴进简历 PDF。

---

## 电商客服与运营 Copilot Agent（个人项目｜独立完成）　2026.07-至今
**技术栈：Python / LangGraph（自建 StateGraph ReAct） / DeepSeek / PostgreSQL + pgvector / FastAPI / NiceGUI / bge-m3**

- **项目介绍**：面向电商内部客服/运营的旁路 Copilot。将传统闭集 Intent Router 重构为 LLM 驱动的
  Tool-Orchestrator（LLM 看过滤后的工具目录自主编排 + 确定性工具裁定 + HITL 审批），完成
  "固定路径执行 → 动态编排"的架构演进；同一 benchmark 上业务覆盖率由 85%（22/26）提升至 100%（26/26）。

- **Agent Runtime**：自建 LangGraph StateGraph ReAct 循环（model→tools→条件路由→finalize）；
  四分区 AgentState + working_context 实体覆盖实现跨轮引用；PostgresSaver 断点续跑；
  能力切换为「请求 → 用户确认」两步（LLM 只建议、用户拍板，防一句话自提升）。

- **Tool / 安全边界**：10 直连业务 Tool + 2 审批 Workflow + 1 能力协商 Meta-Tool，按 Workspace Mode
  过滤目录；高风险写 Tool（建退货单/补货执行）不暴露给 LLM、收进 Workflow 内部（R4/R5/R10）；
  HTTP 入口会话凭证绑定 store/user，未授权代批被拒；安全评测未授权执行率与审批绕过率均为 0%。

- **Workflow / HITL**：退货流程「资格三态 → interrupt 人审 → 确认 → Action + 审计 + 幂等」，补货建议同构；
  正式结论（资格/风险/补货量）一律由确定性工具裁定，LLM 只解释不裁定。

- **RAG / Knowledge**：23 篇多格式知识 → 章节切块 → bge-m3（1024 维）→ pgvector；生命周期/Scope 过滤 +
  legal/platform/store 权威等级冲突消解 + 生成式答案带引用；Hit@5 = 100%（22/22 可答问题），MRR = 0.83。

- **Evaluation / 评测体系**：构建 M1~M8 多维评测（正确性/效果/性能/安全四层），判定纯函数化 +
  离线 fake 自洽验证 + JSON 报告留档（复现元数据：model / temp / world / git_commit / 工作树状态）；
  212 项单元/集成/回归测试通过。

- **Evaluation / 测试结果**：规则驱动合成业务数据（可复现、world=dev）上——Tool Plan 135/135
  （45 场景×3，严格判定 multi_tool 全调）、Task Success 78/78（26 业务场景×3，业务结果+约束+副作用+
  答案保真四层谓词）、条件多跳 36/36（12 场景×3，轨迹不变量+条件判定）；自动执行链路 P95 4.7~6.0s
  （per-workload、单机 Demo 含模型 API 网络耗时）；同口径下业务结果通过率 81.8%→100%（共同 22 场景×3）。

> 注：单用户 Demo，业务数据为规则驱动合成（固定 seed 可复现）；V1 无真实认证/RBAC，生产形态由 Auth/RBAC
> 在 Agent 外部硬过滤；所有数字对应提交报告，可复现。

---

## 面试追问速查（口径对应）

| 数字 | 口径 |
|---|---|
| Tool Plan 135/135 | 45 场景×3 次 live；严格判定（multi_tool 必需全调）、arg 正确性为独立诊断 |
| Task Success 78/78 | 26 业务场景×3，业务结果+约束+副作用+答案保真四层谓词 |
| 条件多跳 36/36 | 12 场景×3，轨迹不变量+条件（risk_level 来自工具结构化结果），不测答案事实 |
| Hit@5 22/22 | 22 条可答问题（doc 级判定），非全库召回声明 |
| P95 4.7~6.0s | per-workload（M1 5.2/M2 4.7/M3 6.0），warm 图、单机 Demo、含 API 网络 |
| 越权执行/绕过 0% | 结构性（目录过滤+T-X-01 不暴露+interrupt 必经）+ 测试证据，非行为统计 |
| M8 81.8%→100% | 共同 22 场景×3、facts_on=False 同分母；同场景版本对比，非严格因果实验 |
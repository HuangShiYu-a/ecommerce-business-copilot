# 开发环境备忘（Draft，非业务定稿）

> 性质：环境与基础设施备忘，**不是** Business Contract。  
> 业务文档不锁定数据库产品；本备忘仅记录当前机器条件与倾向，供 Database Design 决策时使用。

## 当前已具备

- Windows 11
- Anaconda / Python
- Node.js + Vue（Vite）
- Docker Desktop
- Git
- MySQL（可用于其他学习项目）
- PostgreSQL + pgvector + pgAdmin

## V1 倾向（待 Database Design 正式决策）

倾向评估：

```text
PostgreSQL
├── 电商业务数据
└── pgvector（知识检索向量）
```

相对 `MySQL + 独立向量库`：基础设施更少，适合当前项目规模。  
**最终是否采用，须在 Tool + Database 设计定稿时写清决策理由后锁定。**

## 明确不作为 V1 启动条件

- 不为 Agent 开发强制迁移 WSL/Linux（部署期再考虑）
- V1 不装 Redis / Kafka
- 不把 Hadoop / Hive / Spark 绑进本项目主环境
- 使用独立 conda 环境（如 `ecommerce-agent`），不用 base

## 真正需要新增的

- 项目级 Python 依赖（FastAPI、LangChain、LangGraph、ORM、驱动、测试等）
- LLM / Embedding API 与 `.env`（密钥不入库）
- Docker Compose 编排（若采用容器化数据库）

修订：随 Database Design 定稿后，可升级为正式《Environment & Runtime》文档。

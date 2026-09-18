# db — PostgreSQL (pgvector) 开发库

S4 的数据库层：Docker 编排 + DDL + 导入脚本。

## 连接信息

| 项 | 值 |
|---|---|
| 宿主端口 | `5434`（5432=本机 PG、5433=另一 Docker 栈，均被占用） |
| 库名 | `ec_copilot` |
| 用户 / 密码 | `ec` / `ec_secret` |
| 连接串 | `postgresql://ec:ec_secret@localhost:5434/ec_copilot` |
| 客户端 | pgAdmin / DBeaver 等直接连 `localhost:5434` 即可 |

## 常用命令

```bash
# 启动 / 停止 / 重置（-v 清空数据卷 = 一键重置）
docker-compose up -d
docker-compose down
docker-compose down -v

# 应用 DDL（建表，幂等）
docker exec -i ec-copilot-pg psql -U ec -d ec_copilot -v ON_ERROR_STOP=1 < db/schema.sql

# 导入 canonical（默认先 TRUNCATE 再导）
python db/import_data.py --profile dev
python db/import_data.py --profile eval
```

## 约定

- 24 张表（public 业务 22 + knowledge 知识 2），DB §13 列级一致；id 显式（canonical 提供）
- 空串 → NULL；created_at/updated_at 走 DB 默认；JSONB 由文本隐式转
- `knowledge.knowledge_chunks.embedding` 为 vector(1536) **stub**（S3.5 未生成，导入留 NULL，S4 后续补）
- `inventory_movements` / `service_tickets` / `audit_logs` 建表但不导入（策略 B / 运行时产物）

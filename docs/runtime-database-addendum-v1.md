# E-commerce Business Copilot — Runtime Database Addendum（Spec-2）

版本：V1.0 · 状态：定稿 · 日期：2026-09-19

**文档定位**：Agent Runtime V2 的持久化设计。是 Database V1.2.3 的**追加层**（新增 `runtime` schema + 表），**不修改现有 25 张业务表**。对应《Agent Runtime V2 Spec》§14 的落地细节。

---

## 1. 定位与边界

### 1.1 与现有 DB 的关系

```
public schema   ← 业务表 22 张（含 audit_logs / staff_users / store_configs，不动）+ LangGraph checkpoint 表（自动建）
knowledge schema ← 知识表 2（不动）
runtime schema  ← 本次新增：session / staff_user_memory / run_log
```

- 关键关联：`staff_users`（身份来源，FK）、`audit_logs`（业务审计，run_log 不取代，C4）。
- 业务事实（订单/库存/价格）仍只查原业务表（C2）。

### 1.2 硬约束（C1–C7）

| # | 约束 |
|---|---|
| C1 | **不自建 checkpoint 体系**——用 LangGraph PostgresSaver |
| C2 | 业务事实不落 runtime 表（订单/库存/价格只查原业务表）|
| C3 | 记忆只记偏好/习惯，不记业务事实、不记敏感信息（Spec-1 §14.3）|
| C4 | `run_log` 是可观测日志，**≠ `audit_logs`**（业务审计走 public.audit_logs）|
| C5 | `user_id` 关联 `staff_users`（身份来自 Trusted UserContext，B4）|
| C6 | `store_id` 只作**快照/展示**，不作业务隔离源（隔离仍由工具层 + 原表保证，B5）|
| C7 | 不修改 Database V1.2.3 任何现有表 |

### 1.3 角色与 store 约定

- `role ∈ {customer_service, operations}`（与 `staff_users.role` 取值一致）。
- `session.store_id` 是**会话级选择**（用户本次选店）；`staff_users.store_id` 是员工**归属店/默认店**——两者可能不同，不冲突。

---

## 2. Checkpoint（PostgresSaver）

### 2.1 决策

- 用 `langgraph-checkpoint-postgres` 的 **PostgresSaver**，不自建 checkpoint 表（C1 / 闸门 4）。
- checkpoint 表（`checkpoints` / `checkpoint_writes` / `checkpoint_blobs`）由 PostgresSaver 自动创建，**我们不写 DDL**。
- **schema 归属（D1 验证结论）**：PostgresSaver **不支持自定义 schema**（构造器无 schema 参数，SQL 用裸表名）→ checkpoint 表落 **`public`**；本层业务表（session/memory/run_log）仍落 `runtime` schema。

### 2.2 依赖与风险（D6，spike 项）

- 新增依赖：`langgraph-checkpoint-postgres`。
- ⚠️ PostgresSaver 基于 **psycopg**；现有 `psycopg2-binary`——**兼容性需 spike 验证**（实现前 30min spike）。
- 若冲突：评估改用 psycopg，或调整连接方案（以 spike 结论为准）。

### 2.3 清理策略

- thread 不活跃 **30 天**后删除（LangGraph `delete_thread` / 定时任务）。
- session 关闭（§4）时同步评估对应 thread 清理。

---

## 3. Runtime 表（DDL）

### 3.1 session

```sql
CREATE SCHEMA IF NOT EXISTS runtime;

CREATE TABLE IF NOT EXISTS runtime.session (
    session_id  TEXT PRIMARY KEY,               -- UUID hex
    thread_id   TEXT NOT NULL UNIQUE,           -- LangGraph thread，1:1（Spec-1 §6）
    user_id     BIGINT NOT NULL REFERENCES public.staff_users(id),
    role        VARCHAR(32) NOT NULL,           -- customer_service | operations
    store_id    BIGINT NOT NULL REFERENCES public.stores(id),  -- 会话级选店（Trusted UserContext 快照）
    status      VARCHAR(16) NOT NULL DEFAULT 'active',  -- active | closed
    title       VARCHAR(200),                   -- 会话标题（首句摘要）
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_session_user ON runtime.session(user_id, status);
CREATE INDEX IF NOT EXISTS idx_session_updated ON runtime.session(updated_at);
```

### 3.2 staff_user_memory

```sql
CREATE TABLE IF NOT EXISTS runtime.staff_user_memory (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES public.staff_users(id),
    memory_type  VARCHAR(16) NOT NULL,          -- preference | behavior（V1 仅这两类）
    memory_key   VARCHAR(64) NOT NULL,          -- 如 default_horizon / response_format
    memory_value JSONB NOT NULL,
    confidence   FLOAT NOT NULL DEFAULT 0.5,
    source       TEXT,                          -- 来源 session_id
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, memory_type, memory_key)   -- 同 key 覆盖更新（Spec-1 §14.3）
);

CREATE INDEX IF NOT EXISTS idx_memory_user ON runtime.staff_user_memory(user_id);
```

### 3.3 run_log

```sql
CREATE TABLE IF NOT EXISTS runtime.run_log (
    run_id       TEXT PRIMARY KEY,              -- 每次执行的唯一 ID（Spec-1 §6）
    session_id   TEXT REFERENCES runtime.session(session_id),
    user_id      BIGINT NOT NULL REFERENCES public.staff_users(id),
    role         VARCHAR(32) NOT NULL,
    store_id     BIGINT NOT NULL,
    intent       VARCHAR(64),
    workflow     VARCHAR(32),
    route_status VARCHAR(32),
    tool_calls   JSONB,                         -- [{tool, args, result_summary}]
    status       VARCHAR(32) NOT NULL,          -- completed | failed | waiting_user_input | capability_required | approval_required | incomplete
    latency_ms   INT,
    token_usage  JSONB,                         -- {prompt, completion, total}
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_runlog_session ON runtime.run_log(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runlog_user ON runtime.run_log(user_id, created_at);
```

### 3.4 设计说明

- `run_log.tool_calls` 只存**结果摘要**（结构化值），不存原始 Trace 细节——Trace 事件流实时消费，不落库（Spec-1 §13）。
- `staff_user_memory.memory_value` 用 JSONB，支持偏好/行为的异构值（数值、字符串、列表）。
- 全部 `TIMESTAMPTZ`，与现有 schema 约定一致。

---

## 4. 数据生命周期

| 数据 | 保留 | 清理 |
|---|---|---|
| session | 关闭后保留元数据 | 手动关闭 + **24h 无活动自动关**（status→closed）|
| run_log | **30 天**（可配置）| 定时清理 |
| checkpoint | 随 session/thread 存活 | 不活跃 **30 天**删 thread（§2.3）|
| staff_user_memory | 长期 | 同 key 覆盖更新；**用户可清除** |

---

## 5. 迁移与连接

- **DDL**：新增 `db/runtime_schema.sql`（本文件内容 + checkpoint 建表说明）；**不动 `db/schema.sql`**（C7）。
- **导入/迁移**：db 脚本加 runtime 分支（建表 + 可选 seed）。
- **连接**：复用 `copilot/db.py` 的 `connect()` / DSN；PostgresSaver 走同库。

---

## 6. 与 Spec-1 一致性核对

| Spec-1 §14 | 本 Addendum | 一致 |
|---|---|---|
| §14.1 PostgresSaver，不自建 | §2 | ✅ |
| §14.2 session / staff_user_memory / run_log | §3 | ✅ |
| §14.3 写入策略（仅 completed 后 / 只记偏好 / 高置信 / 用户可清除）| §3.2 + §4 | ✅ |
| §6 Session↔Thread 一对一 | §3.1 `thread_id UNIQUE` | ✅ |
| §13 Trace 不落库、审计走 audit_logs | §3.4 + C4 | ✅ |

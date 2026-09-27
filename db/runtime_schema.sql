-- ============ Agent Runtime V2 持久化（Spec-2）============
-- runtime schema：session / staff_user_memory / run_log
-- checkpoint 表由 LangGraph PostgresSaver 自动建在 public（D1 结论，见 Spec-2 §2.1）

CREATE SCHEMA IF NOT EXISTS runtime;

-- 会话元数据（Spec-2 §3.1）
CREATE TABLE IF NOT EXISTS runtime.session (
    session_id  TEXT PRIMARY KEY,               -- UUID hex
    thread_id   TEXT NOT NULL UNIQUE,           -- LangGraph thread，1:1
    user_id     BIGINT NOT NULL REFERENCES public.staff_users(id),
    role        VARCHAR(32) NOT NULL,           -- customer_service | operations
    store_id    BIGINT NOT NULL REFERENCES public.stores(id),
    status      VARCHAR(16) NOT NULL DEFAULT 'active',  -- active | closed
    title       VARCHAR(200),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_session_user ON runtime.session(user_id, status);
CREATE INDEX IF NOT EXISTS idx_session_updated ON runtime.session(updated_at);

-- 长期记忆（Spec-2 §3.2；§14.3 只记偏好/行为，不记业务事实）
CREATE TABLE IF NOT EXISTS runtime.staff_user_memory (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES public.staff_users(id),
    memory_type  VARCHAR(16) NOT NULL,          -- preference | behavior
    memory_key   VARCHAR(64) NOT NULL,
    memory_value JSONB NOT NULL,
    confidence   FLOAT NOT NULL DEFAULT 0.5,
    source       TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, memory_type, memory_key)
);
CREATE INDEX IF NOT EXISTS idx_memory_user ON runtime.staff_user_memory(user_id);

-- 可观测日志（Spec-2 §3.3；可观测 ≠ audit_logs，C4）
CREATE TABLE IF NOT EXISTS runtime.run_log (
    run_id       TEXT PRIMARY KEY,
    session_id   TEXT REFERENCES runtime.session(session_id),
    user_id      BIGINT NOT NULL REFERENCES public.staff_users(id),
    role         VARCHAR(32) NOT NULL,
    store_id     BIGINT NOT NULL,
    intent       VARCHAR(64),
    workflow     VARCHAR(32),
    route_status VARCHAR(32),
    tool_calls   JSONB,
    status       VARCHAR(32) NOT NULL,          -- completed | failed | waiting_user_input | capability_required | approval_required | incomplete
    latency_ms   INT,
    token_usage  JSONB,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_runlog_session ON runtime.run_log(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runlog_user ON runtime.run_log(user_id, created_at);

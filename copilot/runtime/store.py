"""Agent Runtime 持久化 store（Spec-2）：session / staff_user_memory / run_log。

写操作由本模块负责（runtime 层允许写；业务查询仍走 copilot/db.py 只读原则）。
会话凭证（session_token，P0-1/P0-2 option b+）：
- create_session 为新会话（或历史无 token 会话）签发 token，供 HTTP API 审批/续答校验；
- resolve_api_session 为 HTTP 入口的会话解析（懒创建 / token 校验 / 服务端 store-user 锁定）。
"""
from __future__ import annotations

import json
import secrets
import time

from ..db import connect, query, query_one


def execute(conn, sql: str, params=()) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


# ---- session ----

def create_session(session_id: str, thread_id: str, user_id: int, role: str,
                   store_id: int, title: str | None = None) -> str:
    """建/复用会话并返回 session_token（新会话签发；既有会话保留原 token）。

    ON CONFLICT 只回填标题与状态，**不覆盖既有 token**——token 是会话凭证，一经签发保持稳定。
    """
    token = secrets.token_hex(16)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO runtime.session (session_id, thread_id, user_id, role, store_id, title, session_token)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET status='active', closed_at=NULL,
                    thread_id=EXCLUDED.thread_id, updated_at=now(),
                    -- I5：复用旧会话时回填标题（legacy 建的 None 标题行），新标题为空则保留原值
                    title = COALESCE(EXCLUDED.title, runtime.session.title),
                    session_token = COALESCE(runtime.session.session_token, EXCLUDED.session_token)
                RETURNING session_token
            """, (session_id, thread_id, user_id, role, store_id, title, token))
            row = cur.fetchone()
        conn.commit()
        return row[0] if row else token
    finally:
        conn.close()


def get_session(session_id: str) -> dict | None:
    conn = connect()
    try:
        return query_one(conn, "SELECT * FROM runtime.session WHERE session_id=%s", (session_id,))
    finally:
        conn.close()


def resolve_api_session(session_id: str, token: str | None, declared_user: int,
                        declared_store: int, role: str) -> tuple[dict | None, str | None]:
    """HTTP API 会话解析（P0-1/P0-2 option b+；demo 边界：无认证，首轮客户端声明）。

    返回 ({user_id, store_id, session_token}, None) 或 (None, error)。
    - 未知 session_id：以客户端声明的 store/user 懒创建会话，服务端签发 token（首轮信任引导）；
    - 既有会话 + token 匹配：user_id/store_id 以服务端记录为准（请求体忽略）；
    - 既有会话 token 为 NULL（历史/测试遗留）：首次 HTTP 访问签发 token 接管；
    - 既有会话 + token 不匹配：403（会话凭证无效）——审批/续答需持有该会话凭证。
    """
    conn = connect()
    try:
        row = query_one(conn,
                        "SELECT session_token, user_id, store_id FROM runtime.session WHERE session_id=%s",
                        (session_id,))
        if row is None:
            token = secrets.token_hex(16)
            execute(conn, """
                INSERT INTO runtime.session
                    (session_id, thread_id, user_id, role, store_id, session_token)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    session_token = COALESCE(runtime.session.session_token, EXCLUDED.session_token),
                    user_id=EXCLUDED.user_id, store_id=EXCLUDED.store_id,
                    status='active', updated_at=now()
            """, (session_id, session_id, declared_user, role, declared_store, token))
            return {"user_id": declared_user, "store_id": declared_store,
                    "session_token": token}, None
        stored = row["session_token"]
        if stored is None:
            # 历史无 token 会话：首次 HTTP 访问签发接管（后续请求须携带）
            token = secrets.token_hex(16)
            execute(conn, "UPDATE runtime.session SET session_token=%s WHERE session_id=%s",
                    (token, session_id))
            return {"user_id": row["user_id"], "store_id": row["store_id"],
                    "session_token": token}, None
        if not token or token != stored:
            return None, "会话凭证无效"
        return {"user_id": row["user_id"], "store_id": row["store_id"],
                "session_token": stored}, None
    finally:
        conn.close()


def close_session(session_id: str) -> None:
    conn = connect()
    try:
        execute(conn, """
            UPDATE runtime.session SET status='closed', closed_at=now() WHERE session_id=%s
        """, (session_id,))
    finally:
        conn.close()


# ---- staff_user_memory ----

def get_memory(user_id: int) -> list[dict]:
    conn = connect()
    try:
        return query(conn, """
            SELECT memory_type, memory_key, memory_value, confidence, source
            FROM runtime.staff_user_memory WHERE user_id=%s ORDER BY updated_at DESC
        """, (user_id,))
    finally:
        conn.close()


def upsert_memory(user_id: int, memory_type: str, memory_key: str, value,
                  confidence: float = 0.5, source: str | None = None) -> None:
    conn = connect()
    try:
        execute(conn, """
            INSERT INTO runtime.staff_user_memory
                (user_id, memory_type, memory_key, memory_value, confidence, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, memory_type, memory_key)
            DO UPDATE SET memory_value=EXCLUDED.memory_value,
                          confidence=EXCLUDED.confidence, source=EXCLUDED.source,
                          updated_at=now()
        """, (user_id, memory_type, memory_key, json.dumps(value, ensure_ascii=False), confidence, source))
    finally:
        conn.close()


def clear_memory(user_id: int, memory_key: str | None = None) -> None:
    conn = connect()
    try:
        if memory_key:
            execute(conn, "DELETE FROM runtime.staff_user_memory WHERE user_id=%s AND memory_key=%s",
                    (user_id, memory_key))
        else:
            execute(conn, "DELETE FROM runtime.staff_user_memory WHERE user_id=%s", (user_id,))
    finally:
        conn.close()


# ---- run_log ----

def write_run_log(run_id: str, session_id: str | None, user_id: int, role: str,
                  store_id: int, intent: str | None, workflow: str | None,
                  route_status: str | None, status: str, tool_calls: list | None = None,
                  latency_ms: int | None = None, error: str | None = None) -> None:
    conn = connect()
    try:
        execute(conn, """
            INSERT INTO runtime.run_log
                (run_id, session_id, user_id, role, store_id, intent, workflow,
                 route_status, tool_calls, status, latency_ms, error)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (run_id, session_id, user_id, role, store_id, intent, workflow,
              route_status, json.dumps(tool_calls) if tool_calls else None,
              status, latency_ms, error))
    finally:
        conn.close()


def now_ms() -> int:
    return int(time.time() * 1000)

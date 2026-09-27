"""Agent Runtime 持久化 store（Spec-2）：session / staff_user_memory / run_log。

写操作由本模块负责（runtime 层允许写；业务查询仍走 copilot/db.py 只读原则）。
"""
from __future__ import annotations

import json
import time

from ..db import connect, query, query_one


def execute(conn, sql: str, params=()) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


# ---- session ----

def create_session(session_id: str, thread_id: str, user_id: int, role: str,
                   store_id: int, title: str | None = None) -> None:
    conn = connect()
    try:
        execute(conn, """
            INSERT INTO runtime.session (session_id, thread_id, user_id, role, store_id, title)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE SET status='active', closed_at=NULL,
                thread_id=EXCLUDED.thread_id, updated_at=now(),
                -- I5：复用旧会话时回填标题（legacy 建的 None 标题行），新标题为空则保留原值
                title = COALESCE(EXCLUDED.title, runtime.session.title)
        """, (session_id, thread_id, user_id, role, store_id, title))
    finally:
        conn.close()


def get_session(session_id: str) -> dict | None:
    conn = connect()
    try:
        return query_one(conn, "SELECT * FROM runtime.session WHERE session_id=%s", (session_id,))
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

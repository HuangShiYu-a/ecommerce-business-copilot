"""PostgreSQL 只读访问（Query 原则：读不写）。"""
from __future__ import annotations

import json

import psycopg2
import psycopg2.extras

from .config import DB_DSN


def connect():
    conn = psycopg2.connect(DB_DSN)
    # JSONB → Python 对象（dict/list/scalar）
    psycopg2.extras.register_default_jsonb(conn_or_curs=conn, loads=json.loads)
    return conn


def query(conn, sql: str, params=()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def query_one(conn, sql: str, params=()) -> dict | None:
    rows = query(conn, sql, params)
    return rows[0] if rows else None

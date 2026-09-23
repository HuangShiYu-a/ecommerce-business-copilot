"""Phase 5（G5 核查）记忆读回离线测试（W5.1）。

- _extract_memory：『默认 N 天』→ default_horizon 偏好写入
- _memory_block：每轮注入格式（含偏好行）
- 用隔离测试 user，测后清理（clear_memory）
"""
from __future__ import annotations

import os

os.environ.setdefault("LLM_MODE", "dryrun")

import pytest

from copilot.agent.react import _extract_memory, _memory_block
from copilot.db import connect
from copilot.runtime.store import clear_memory, get_memory

TEST_USER = 99001


def _ensure_staff(uid: int) -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO staff_users (id, store_id, username, display_name, role, is_active) "
                    "VALUES (%s, 1, %s, %s, 'operations', true) ON CONFLICT (id) DO NOTHING",
                    (uid, f"TEST_{uid}", f"测试{uid}"))
        conn.commit()
        cur.close()


def _drop_staff(uid: int) -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM staff_users WHERE id=%s", (uid,))
        conn.commit()
        cur.close()


@pytest.fixture(autouse=True)
def _clean_memory():
    _ensure_staff(TEST_USER)
    clear_memory(TEST_USER)
    yield
    clear_memory(TEST_USER)
    _drop_staff(TEST_USER)


def test_extract_memory_default_horizon():
    _extract_memory({"session_id": "s", "user_id": TEST_USER}, "我默认看 7 天")
    mems = get_memory(TEST_USER)
    keys = {m["memory_key"]: m["memory_value"] for m in mems}
    assert keys.get("default_horizon") == 7, keys


def test_memory_block_format():
    _extract_memory({"session_id": "s", "user_id": TEST_USER}, "默认 30 天")
    block = _memory_block({"session_id": "s", "user_id": TEST_USER})
    assert "用户长期偏好" in block
    assert "默认分析时间窗" in block and "30" in block, block


def test_memory_block_empty_when_none():
    assert _memory_block({"session_id": "s", "user_id": TEST_USER}) == ""

"""可复用：清理无 checkpoint 的孤儿会话（Phase 1 数据卫生）。

安全线：**绝不删「有 checkpoint」的会话**（真实可续对话，LangGraph 每次 invoke 都落 checkpoint）。
删除范围：
  A 类：uuid（32 位 hex）+ 无 checkpoint + 无 run_log（纯 UI 孤儿，无法续跑、无审计）
  M 类：非 uuid + 无 checkpoint（手工/脚本测试会话，含被测试重建的 s_p2）
默认 --dry-run 只分类列出；--yes 才执行（单事务，先删 run_log 再删 session，FK 顺序）。

用法：
  python scripts/cleanup_orphan_sessions.py            # 仅列出待删清单
  python scripts/cleanup_orphan_sessions.py --yes      # 执行删除
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copilot.db import connect, query


def _should_delete(r: dict) -> bool:
    if r["has_ck"]:
        return False            # 真实对话，永不删
    if r["is_uuid"]:
        return not r["has_log"]  # uuid 孤儿：仅当无审计痕迹
    return True                 # 非 uuid 手工会话（且无 checkpoint）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="实际执行删除（默认仅 dry-run）")
    args = ap.parse_args()

    conn = connect()
    rows = query(conn, """
        SELECT session_id, title, role, updated_at,
               EXISTS(SELECT 1 FROM checkpoints ck WHERE ck.thread_id = s.thread_id) AS has_ck,
               EXISTS(SELECT 1 FROM runtime.run_log rl WHERE rl.session_id = s.session_id) AS has_log,
               (s.session_id ~ '^[0-9a-f]{32}$') AS is_uuid
        FROM runtime.session s
        ORDER BY s.updated_at DESC
    """)
    delete = [r for r in rows if _should_delete(r)]
    keep = [r for r in rows if not _should_delete(r)]

    print(f"总 {len(rows)} 条 | 待删 {len(delete)} 条 | 保留 {len(keep)} 条（全部有 checkpoint）\n")
    print("=== 待删清单 ===")
    for r in delete:
        kind = "A-孤儿" if r["is_uuid"] else "M-手工会话"
        print(f"  [{kind}] {r['session_id']} | {r['title']!r} | {r['role']} | {r['updated_at']}")
    print("\n=== 保留（不删）前 10 ===")
    for r in keep[:10]:
        print(f"  [保留] {r['session_id']} | {r['title']!r} | {r['role']}")

    if not args.yes:
        print("\n[dry-run] 未执行任何删除。加 --yes 执行。")
        conn.close()
        return 0

    sids = [r["session_id"] for r in delete]
    if not sids:
        print("[skip] 无待删项。")
        conn.close()
        return 0

    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM runtime.run_log WHERE session_id = ANY(%s)", (sids,))
        n_log = cur.rowcount
        cur.execute("DELETE FROM runtime.session WHERE session_id = ANY(%s)", (sids,))
        n_sess = cur.rowcount
        conn.commit()
        print(f"\n[deleted] run_log {n_log} 条，session {n_sess} 条")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

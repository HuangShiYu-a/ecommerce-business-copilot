"""Phase 4（G4 核查）新架构 SC 覆盖：data SC 全走工具层，断言 formal_result 派生 route。

D4：从 route_status 改为 formal_result 断言——本测试经 sc_runner 对每个 data SC 调用
确定性工具，route 由 formal_result 字段派生后与 expected_route 比对（架构无关，
非 legacy runtime 产物，Phase 6 切换后仍有效）。OP-07 / CS08-006 为"无路由断言"对照
→ 仅冒烟（工具 ok）。
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("LLM_MODE", "dryrun")

import yaml

from copilot.db import connect
from copilot.sc_runner import RUNNERS

SC = yaml.safe_load((Path(__file__).resolve().parent.parent.parent
                     / "data" / "scenarios" / "eval" / "scenarios.yaml")
                    .read_text(encoding="utf-8"))


def _data_scs():
    return [s for s in SC["scenarios"] if s["nature"] == "data"]


def test_all_data_scs_formal_result():
    """全部 data SC：有路由断言 → 匹配；无路由断言（对照）→ 工具 ok 冒烟。"""
    failures = []
    conn = connect()
    try:
        for s in _data_scs():
            runner = RUNNERS.get(s["workflow"])
            assert runner, f"缺 runner: {s['workflow']}"
            rep = runner(s, conn)
            if s.get("expected_route") is None:
                if rep["actual_route"].startswith("ERROR"):
                    failures.append(f"{s['scenario_id']}（对照）工具出错: {rep['actual_route']}")
            elif not rep["match"]:
                failures.append(
                    f"{s['scenario_id']}: expect {rep['expected_route']} got "
                    f"{rep['actual_route']} ({rep['actual_reason']})")
    finally:
        conn.close()
    assert not failures, "\n".join(failures)


def test_sc_route_coverage_count():
    """有路由断言的 data SC 数（新架构 formal_result 覆盖基线，≥ legacy 等价）。"""
    n = sum(1 for s in _data_scs() if s.get("expected_route"))
    assert n >= 21, f"data SC 路由断言数 {n} < 21"


def test_iso_cross_store_source_store():
    """SC-ISO-001：读放开 + source_store=2（D7 expected_formal_result）。"""
    s = next(x for x in _data_scs() if x["scenario_id"] == "SC-ISO-001")
    conn = connect()
    try:
        rep = RUNNERS["ISO"](s, conn)
        assert rep["match"], rep
        assert rep["detail"].get("source_store") == 2, rep["detail"]
    finally:
        conn.close()

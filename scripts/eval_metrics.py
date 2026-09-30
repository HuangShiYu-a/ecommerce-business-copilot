"""eval_metrics CLI（评估方案 §5）：offline 验证 / live 出数字。

用法：
  python scripts/eval_metrics.py --mode offline                # 离线 Phase A（fake，100% 验证）
  python scripts/eval_metrics.py --mode live --repeat 3 --out reports/eval_metrics.json
  python scripts/eval_metrics.py --mode live --set tool_sel    # 只跑某一集
  python scripts/eval_metrics.py --import-check                # 只验证导入（不调模型）

输出：终端表格 + 报告 JSON（带 Reproducibility Metadata）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _import_check() -> int:
    from copilot.eval import judgments, live, predicates, runner, safety_scenarios  # noqa: F401
    print("[OK] copilot.eval 全部模块可导入")
    print("      judgments/predicates/safety_scenarios/runner/live 就绪")
    return 0


def _offline() -> int:
    from copilot.eval.runner import run_offline
    rep = run_offline()
    for k in ("m1", "m3", "m2"):
        r = rep[k]
        mark = "PASS" if r["n_ok"] == r["n_total"] else "FAIL"
        print(f"[{mark}] {k}: {r['n_ok']}/{r['n_total']}")
        for f in r["failures"]:
            print(f"        {f}")
    print(f"[OK] m4: {rep['m4']}")
    return 0 if all(rep[k]["n_ok"] == rep[k]["n_total"] for k in ("m1", "m3", "m2")) else 1


def _live(repeat: int, out: str | None, only: str | None) -> int:
    from copilot.eval.live import (run_live_all, run_live_m1, run_live_m2,
                                   run_live_m3, metadata)
    from copilot.eval.runner import run_offline_m4
    from langgraph.checkpoint.memory import InMemorySaver
    from copilot.agent.graph_factory import ReactGraphFactory

    factory = ReactGraphFactory(checkpointer=InMemorySaver())
    rep: dict = {"metadata": metadata()}
    if only in (None, "tool_sel"):
        rep["m1"] = run_live_m1(factory, repeat)
    if only in (None, "multihop"):
        rep["m3"] = run_live_m3(factory, repeat)
    if only in (None, "task_success"):
        rep["m2"] = run_live_m2(factory, repeat)
    if only in (None, "rag"):
        rep["m4"] = run_offline_m4()
    for k in ("m1", "m3", "m2", "m4"):
        if k in rep:
            print(f"[{k}] {rep[k]}")
    if out:
        p = ROOT / out
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已写入: {p}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="E-commerce Agent 评测 harness")
    ap.add_argument("--mode", choices=["offline", "live"], help="offline=fake 验证；live=DeepSeek")
    ap.add_argument("--set", choices=["all", "tool_sel", "task_success", "rag", "multihop", "safety"],
                    default="all")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--out", default=None, help="报告 JSON 路径（相对仓库根）")
    ap.add_argument("--import-check", action="store_true")
    args = ap.parse_args()

    if args.import_check:
        return _import_check()
    if args.mode == "offline":
        return _offline()
    if args.mode == "live":
        only = None if args.set == "all" else args.set
        return _live(args.repeat, args.out, only)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

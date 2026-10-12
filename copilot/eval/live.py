"""D2 live runner：DeepSeek repeat=3 + warm-up + CS-08 清理 + resume 保护 + metadata。

只写代码与结构；实际 live 跑由 CLI 触发（--mode live）。M5 延迟在 runner 内计时
（不依赖 run_log，避免 DB 依赖）；CS-08 每次 repeat 后清理（V1.2.3：run 间必须清，
否则第 2/3 次全走 already_exists 无法复现 interrupt→建单路径）。
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from ..agent.graph_factory import ReactGraphFactory
from ..agent.react import run_agent_react
from .judgments import extract_trace, judge_m1_plan, judge_m3_trace
from .predicates import predicate_for
from .runner import (MODE_OF, WF_TOOL, _load, _sc_data, question_for, tool_args_for)

ROOT = Path(__file__).resolve().parent.parent.parent


def metadata() -> dict:
    # P8-I7：记录**完整 commit SHA + 工作树干净标记**（此前只记 --short，无法证明报告对应
    # 实际运行代码——P4 报告记 cd5ed7c 但运行于未提交的 P1~P6 改动之上的教训）。
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"],
                             capture_output=True, text=True, cwd=str(ROOT)).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True, cwd=str(ROOT)).stdout.strip()
        worktree = "dirty" if dirty else "clean"
    except Exception:
        sha, worktree = "", "unknown"
    return {
        "model": "deepseek-chat", "temperature": 0,
        "prompt_version": "react.py system prompt (V1.5.3+)",
        "tool_schema_version": "v1", "dataset_version": "v1.2.3",
        "git_commit": sha, "worktree": worktree, "as_of_date": "2026-09-17",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "runs_per_case": 3, "embedding_model": "bge-m3",
        "retrieval_config_version": "v1",
        "world": "dev",   # D-1：评测跑在 dev 世界导入的库（dev/eval 互斥，二选一；复现基准）
    }


def cleanup_cs08() -> None:
    """V1.2.3：repeat 间删除 CS08-* 售后/审计行（否则已建单短路 already_exists）。"""
    from ..db import connect
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audit_logs WHERE request_id LIKE 'CS08-%' "
                        "AND action='CREATE_RETURN_REQUEST'")
            cur.execute("DELETE FROM after_sales_requests WHERE idempotency_key LIKE 'CS08-%'")
        conn.commit()
    finally:
        conn.close()


def _session(mode: str, thread: str) -> dict:
    return {"session_id": thread, "user_id": 1, "workspace_mode": mode, "store_id": 1}


def _run_once(factory, mode: str, question: str, thread: str,
              resume_ok: bool = False) -> tuple[dict, list, int]:
    """跑一轮（含可选 resume 保护）。返回 (response, messages, latency_ms)。"""
    g = factory.get(mode)
    sess = _session(mode, thread)
    t0 = time.time() * 1000
    out = run_agent_react(g, thread, sess, question)
    lat = int(time.time() * 1000 - t0)
    resp = out["response"]
    # V1.2.3 resume 保护：有 __interrupt__ 才 resume（already_exists 不 resume）
    if resume_ok and resp.get("approval_required") and out.get("state", {}).get("__interrupt__"):
        t0 = time.time() * 1000
        out2 = run_agent_react(g, thread, sess, "", resume={"decision": "approved"})
        lat += int(time.time() * 1000 - t0)
        return out2["response"], out2["state"]["messages"], lat
    return resp, out["state"]["messages"], lat


def _agg(per: list, n_cases: int, lat: list, repeat: int) -> dict:
    run_ok = sum(p["passes"] for p in per)
    run_total = n_cases * repeat
    stable = sum(1 for p in per if p["stable"])
    s = sorted(lat)

    def pct(p):
        return s[int(round((len(s) - 1) * p))] if s else 0

    return {"run_success": f"{run_ok}/{run_total}", "run_rate": round(run_ok / run_total, 4),
            "case_stable": f"{stable}/{n_cases}", "n": len(lat),
            "latency_ms": {"p50": pct(0.5), "p95": pct(0.95)}}


# ---- 各集 live ----

# P8-I2：预热（三模式）——graph_factory 按模式惰性建图缓存，正式样本前须触发建图 +
# 首轮 LLM 调用，否则 P95 会混入首次建图/调用冷启动耗时。
WARMUP_MODES = ("UNSET", "CUSTOMER_SERVICE", "OPERATIONS")
WARMUP_QUESTION = "SKU_01_NORMAL_01 库存多少"


def warmup(factory, modes: tuple = WARMUP_MODES, n: int = 3) -> None:
    """对目标模式各预热 n 次（真实 LLM，结果不入正式样本）。"""
    for mode in modes:
        for i in range(n):
            _run_once(factory, mode, WARMUP_QUESTION, f"warm-{mode}-{i}")


def run_live_m1(factory, repeat: int = 3) -> dict:
    cases = _load("tool_sel.yaml")
    lat, per, detail = [], [], []
    for c in cases:
        mode = c.get("mode", "UNSET")
        passes = 0
        runs = []
        for rep in range(repeat):
            thread = f"lm1-{c['id']}-{rep}"
            resp, msgs, l = _run_once(factory, mode, c["question"], thread)
            lat.append(l)
            r = judge_m1_plan(extract_trace(msgs), c["acceptable_plan"],
                              resp.get("status", ""), resp.get("message", ""))
            passes += int(r["exact"])
            # P8-I3：逐用例工具调用记录（可追溯；工具集 = 实际调用序列去重）
            runs.append({"rep": rep, "exact": bool(r["exact"]),
                         "tools": sorted({n for n, *_ in extract_trace(msgs)})})
            cleanup_cs08()
        per.append({"id": c["id"], "passes": passes, "stable": passes == repeat})
        detail.append({"id": c["id"], "runs": runs})
    agg = _agg(per, len(cases), lat, repeat)
    agg["detail"] = detail
    return agg


def run_live_m3(factory, repeat: int = 3) -> dict:
    cases = _load("multihop_gold.yaml")
    lat, per = [], []
    for c in cases:
        mode = c.get("mode", "OPERATIONS")
        passes = 0
        for rep in range(repeat):
            thread = f"lm3-{c['id']}-{rep}"
            resp, msgs, l = _run_once(factory, mode, c["question"], thread)
            lat.append(l)
            ok = judge_m3_trace(extract_trace(msgs), resp, c)
            passes += int(ok)
        per.append({"id": c["id"], "passes": passes, "stable": passes == repeat})
    return _agg(per, len(cases), lat, repeat)


def run_live_m2(factory, repeat: int = 3) -> dict:
    scs = _sc_data()
    lat, per = [], []
    for sc in scs:
        wf = sc["workflow"]
        tool = "cs08_return_workflow" if sc["scenario_id"] == "SC-CS08-006" else WF_TOOL[wf]
        args = tool_args_for(sc)
        mode = MODE_OF[wf]
        resume_ok = wf in ("OP-05",)   # OP-05 HAS_RECO 需 resume；CS-08-006 为 already_exists 不 resume
        pred = predicate_for(sc)
        passes = 0
        for rep in range(repeat):
            thread = f"lm2-{sc['scenario_id']}-{rep}"
            resp, msgs, l = _run_once(factory, mode, question_for(sc), thread, resume_ok=resume_ok)
            lat.append(l)
            ok, _ = pred(resp)
            passes += int(ok)
            if wf == "CS-08":
                cleanup_cs08()
        per.append({"id": sc["scenario_id"], "passes": passes, "stable": passes == repeat})
    return _agg(per, len(scs), lat, repeat)


def run_react_business(factory, scs: list, repeat: int = 3) -> dict:
    """ReAct 在给定 SC 集上按**业务结果口径**（facts_on=False）重复运行——M8 同口径 React 侧。

    与 run_live_m2 同机制（_run_once + OP-05 resume + CS-08 清理），仅谓词用 facts_on=False
    （P8-I4：与 legacy 侧可比，双方均不含答案保真）；不产出 latency（M8 只比结果）。
    """
    warmup(factory)
    n_ok = total = 0
    per = []
    for sc in scs:
        wf = sc["workflow"]
        mode = MODE_OF[wf]
        resume_ok = wf in ("OP-05",)
        pred = predicate_for(sc, facts_on=False)
        passes = 0
        for rep in range(repeat):
            thread = f"m8r-{sc['scenario_id']}-{rep}"
            resp, _msgs, _l = _run_once(factory, mode, question_for(sc), thread,
                                        resume_ok=resume_ok)
            ok, _ = pred(resp)
            passes += int(ok)
            if wf == "CS-08":
                cleanup_cs08()
        total += repeat
        n_ok += passes
        per.append({"id": sc["scenario_id"], "passes": passes, "stable": passes == repeat})
    return {"run_success": f"{n_ok}/{total}", "run_rate": round(n_ok / total, 4),
            "n": total, "per_sc": per}


def run_live_all(repeat: int = 3, warmup: int = 4) -> dict:
    """完整 live：warm-up → M1/M3/M2（repeat=3）→ M4 确定性。"""
    factory = ReactGraphFactory(checkpointer=InMemorySaver())
    for i in range(warmup):
        _run_once(factory, "CUSTOMER_SERVICE", "SKU_01_NORMAL_01 库存多少", f"warm-{i}")
    from .runner import run_offline_m4
    return {"metadata": metadata(), "m1": run_live_m1(factory, repeat),
            "m3": run_live_m3(factory, repeat), "m2": run_live_m2(factory, repeat),
            "m4": run_offline_m4()}

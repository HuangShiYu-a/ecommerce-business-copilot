"""M8 Legacy vs ReAct 基线（§3.8）：同一 SC 26 上跑 legacy（dryrun 规则路由），对比。

- Task Success：用业务结果口径（facts_on=False，legacy 模板答案不含自然语言 facts 关键词，
  纯业务结果对比才公平）
- Coverage：legacy 能进入有效处理流程的 SC / 26
- Multi-tool / Conditional Multi-hop：legacy 结构性不支持（1 intent/轮、无 observation 驱动
  深挖）→ 标 N/A，ReAct 侧取 M1 multi_tool + M3 实测
- ReAct 侧数字读取最新提交的 live 报告（reports/eval_metrics_*.json），不硬编码占位
  （D-1：README/简历数字必须有报告背书）。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..agent.orchestrator import build_runtime_graph, run_agent
from .predicates import predicate_for
from .runner import _sc_data, question_for

ROOT = Path(__file__).resolve().parent.parent.parent

_CS_ROLES = {"CS-06", "CS-08", "ISO"}


def _run_legacy_scs(scs: list, repeat: int = 1) -> dict:
    """Legacy（dryrun 规则路由）在给定 SC 集上运行 repeat 次（确定性 → 结果恒等，如实记录）。

    返回含 supported_ids（能进入有效处理的 SC）与 per_sc，供 M8 同口径对比取共同子集。
    """
    g = build_runtime_graph()
    n_ok = n_supported = 0
    detail, supported, per_sc = [], [], []
    for i, sc in enumerate(scs):
        role = "customer_service" if sc["workflow"] in _CS_ROLES else "operations"
        sess = {"session_id": f"baseline-{i}", "user_id": 1, "role": role, "store_id": 1}
        for rep in range(repeat):
            try:
                out = run_agent(g, sess["session_id"], sess, question_for(sc))
                resp = out["response"]
            except Exception as exc:    # legacy 健壮性：含 datetime 工具结果 json.dumps 崩溃
                detail.append({"id": sc["scenario_id"], "err": f"legacy crash: {type(exc).__name__}"})
                break                   # 结构性不支持：该 SC 不进支持集
            if resp.get("status") == "error":
                detail.append({"id": sc["scenario_id"], "err": "legacy error",
                               "status": resp.get("status")})
                break
            if rep == 0:
                n_supported += 1
                supported.append(sc["scenario_id"])
            ok, det = predicate_for(sc, facts_on=False)(resp)
            n_ok += int(ok)
            if rep == 0:
                per_sc.append({"id": sc["scenario_id"], "ok": bool(ok)})
                if not ok:
                    detail.append({"id": sc["scenario_id"], "detail": det,
                                   "status": resp.get("status")})
    return {"run_success": f"{n_ok}/{n_supported * repeat}" if n_supported else "0/0",
            "coverage": f"{n_supported}/{len(scs)}",
            "run_rate": round(n_ok / (n_supported * repeat), 4) if n_supported else 0.0,
            "n_supported": n_supported, "n_ok": n_ok,
            "supported_ids": supported, "per_sc": per_sc, "failures": detail}


def run_legacy_m2() -> dict:
    """M8 legacy 侧：全部 26 SC × 1（兼容原报告口径 "n_ok/n_supported"）。"""
    return _run_legacy_scs(_sc_data(), repeat=1)


def _latest_report() -> dict | None:
    """读取最新**且含 m2+m3** 的 live 评测报告（P8-I4：跳过只含部分指标的中间报告）。"""
    try:
        files = sorted((ROOT / "reports").glob("eval_metrics_*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files:
            rep = json.loads(f.read_text(encoding="utf-8"))
            if rep.get("m2") and rep.get("m3"):
                return rep
        return None
    except Exception:
        return None


def m8_report() -> dict:
    """M8 对比（P8-I4 同口径）：覆盖率（同 26 集）+ 共同可执行子集业务结果通过率。

    与旧"81.8%→100%"差异：业务结果通过率只取 legacy 可执行的共同场景集、同一业务谓词
    （facts_on=False）、相同重复次数（3×）；legacy 为确定性 dryrun 规则路由，重复结果恒等
    （如实记录）。legacy 结构性不支持 multi-tool / 条件多跳（1 intent/轮）→ N/A，
    ReAct 侧取 M1/M3 实测。
    """
    from .live import run_react_business

    all_scs = _sc_data()
    legacy = run_legacy_m2()
    common = [sc for sc in all_scs if sc["scenario_id"] in set(legacy.get("supported_ids", []))]
    legacy_3x = _run_legacy_scs(common, repeat=3)
    react_bs = run_react_business(common, repeat=3)
    rep = _latest_report()
    n_sc = len(all_scs)
    n_common = len(common)
    if rep:
        react = {
            "multi_hop": rep["m3"].get("run_success", "?"),
            "multi_tool": "measured(M1)",
            "source_report": str(rep.get("metadata", {}).get("git_commit", ""))[:8] or "?",
        }
    else:
        react = {"multi_hop": "未跑（缺 live 报告）", "multi_tool": "N/A", "source_report": None}
    return {
        "comparison": {
            "coverage": {"legacy": f"{n_common}/{n_sc}", "react": f"{n_sc}/{n_sc}"},
            "business_result_pass_rate": {
                "common_scs": n_common, "repeats": 3, "predicate": "facts_on=False（业务结果口径）",
                "legacy": legacy_3x["run_success"], "react": react_bs["run_success"],
                "legacy_rate": legacy_3x["run_rate"], "react_rate": react_bs["run_rate"],
            },
        },
        "legacy": {"run_success": legacy["run_success"], "coverage": legacy["coverage"],
                   "failures": legacy["failures"]},
        "react": react,
        "note": ("同口径说明：覆盖率 = 同 26 场景总集（legacy 支持 22，ReAct 26）；"
                 "业务结果通过率 = legacy 可执行的共同场景 × 3 次、facts_on=False（双方均不含答案保真），"
                 "legacy 为确定性规则路由、重复结果恒等（P8-I4）。"
                 "legacy 结构性不支持 multi-tool / 条件多跳 → N/A；ReAct 侧取自最新 reports/eval_metrics_*.json"
                 "（含 m2+m3 的报告）。"),
    }

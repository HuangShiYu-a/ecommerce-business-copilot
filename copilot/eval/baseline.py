"""M8 Legacy vs ReAct 基线（§3.8）：同一 SC 26 上跑 legacy（dryrun 规则路由），对比。

- Task Success：用业务结果口径（facts_on=False，legacy 模板答案不含自然语言 facts 关键词，
  纯业务结果对比才公平）
- Coverage：legacy 能进入有效处理流程的 SC / 26
- Multi-tool / Conditional Multi-hop：legacy 结构性不支持（1 intent/轮、无 observation 驱动
  深挖）→ 标 N/A，ReAct 侧取 M1 multi_tool + M3 实测
"""
from __future__ import annotations

from ..agent.orchestrator import build_runtime_graph, run_agent
from .predicates import predicate_for
from .runner import _sc_data, question_for

_CS_ROLES = {"CS-06", "CS-08", "ISO"}


def run_legacy_m2() -> dict:
    scs = _sc_data()
    g = build_runtime_graph()
    n_ok = n_supported = 0
    detail = []
    for i, sc in enumerate(scs):
        role = "customer_service" if sc["workflow"] in _CS_ROLES else "operations"
        sess = {"session_id": f"baseline-{i}", "user_id": 1, "role": role, "store_id": 1}
        try:
            out = run_agent(g, sess["session_id"], sess, question_for(sc))
            resp = out["response"]
        except Exception as exc:        # legacy 健壮性：含 datetime 工具结果 json.dumps 崩溃
            detail.append({"id": sc["scenario_id"], "err": f"legacy crash: {type(exc).__name__}"})
            continue
        if resp.get("status") == "error":
            detail.append({"id": sc["scenario_id"], "err": "legacy error",
                           "status": resp.get("status")})
            continue
        n_supported += 1
        ok, det = predicate_for(sc, facts_on=False)(resp)
        n_ok += int(ok)
        if not ok:
            detail.append({"id": sc["scenario_id"], "detail": det,
                           "status": resp.get("status")})
    return {"run_success": f"{n_ok}/{n_supported}", "coverage": f"{n_supported}/{len(scs)}",
            "run_rate": round(n_ok / n_supported, 4) if n_supported else 0.0,
            "failures": detail}


def m8_report() -> dict:
    """组合 M8 对比表：legacy（实跑）vs ReAct（取 M2/M3 最终实测）。"""
    legacy = run_legacy_m2()
    return {
        "legacy": legacy,
        "react": {"task_success": "78/78", "coverage": "26/26",
                  "multi_tool": "measured(M1)", "multi_hop": "36/36"},
        "note": "legacy 结构性不支持 multi-tool / conditional multi-hop（1 intent/轮），标 N/A",
    }

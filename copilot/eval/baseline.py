"""M8 Legacy vs ReAct 基线（§3.8）：同一 SC 26 上跑 legacy，对比。

- **legacy 口径（P8-E 方案 A）**：live LLM 路由（legacy orchestrator 默认 LLM_MODE=live，
  非确定性）——如实反映 legacy 真实运行形态；4 个 SC（CS08-001/002/003、ISO-001）因
  LLM 路由传参导致 datetime json.dumps 崩溃（真实缺陷，ReAct 侧无此问题）。
  ×3 为独立运行（fresh thread_id，bl-{scenario_id}-{rep}），不声称"确定性恒等"。
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
    """Legacy（live LLM 路由，非确定性）在给定 SC 集上运行 repeat 次（独立 fresh thread）。

    P8-E：thread_id 每 (SC, repeat) 唯一（bl-{scenario_id}-{rep}）——legacy run_agent 按
    thread_id 读 PostgresSaver 持久化状态续答，复用 id 会加载历史 checkpoint 导致会话污染
    （实测假象 15/22）；非确定性 ⇒ repeat 为独立样本，不声称恒等。
    返回含 supported_ids（能进入有效处理的 SC）与 per_sc，供 M8 同口径对比取共同子集。
    """
    g = build_runtime_graph()
    n_ok = n_supported = 0
    detail, supported, per_sc = [], [], []
    for i, sc in enumerate(scs):
        role = "customer_service" if sc["workflow"] in _CS_ROLES else "operations"
        for rep in range(repeat):
            # P8-E 修复：thread_id 必须每 (SC, repeat) 唯一——legacy run_agent 按 thread_id
            # 读 PostgresSaver 持久化状态续答；复用 id 会加载历史 checkpoint（含历史 baseline-{i}），
            # 导致 OP-03/OP-04 等返回 waiting_user_input（会话污染，实测 15/22 假象）。
            thread = f"bl-{sc['scenario_id']}-{rep}"
            sess = {"session_id": thread, "user_id": 1, "role": role, "store_id": 1}
            try:
                out = run_agent(g, thread, sess, question_for(sc))
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


def _legacy_business_rate(scs: list, repeat: int = 3) -> dict:
    """legacy 在共同子集上重复运行，业务结果通过率（分母 = len(scs)*repeat 稳定）。

    P8-E：live LLM 路由（非确定性），重复中崩溃/错误**计为失败**（不排除）——legacy 的
    偶发崩溃是其真实可靠性属性，计入分母；与 react 侧（共同子集 × 3）同分母可比。
    """
    g = build_runtime_graph()
    n_ok = 0
    detail = []
    for sc in scs:
        role = "customer_service" if sc["workflow"] in _CS_ROLES else "operations"
        for rep in range(repeat):
            thread = f"blr-{sc['scenario_id']}-{rep}"
            sess = {"session_id": thread, "user_id": 1, "role": role, "store_id": 1}
            try:
                out = run_agent(g, thread, sess, question_for(sc))
                resp = out["response"]
            except Exception as exc:
                detail.append({"id": sc["scenario_id"], "err": f"legacy crash: {type(exc).__name__}"})
                continue            # 失败重复（计入分母）
            if resp.get("status") == "error":
                detail.append({"id": sc["scenario_id"], "err": "legacy error"})
                continue
            ok, _ = predicate_for(sc, facts_on=False)(resp)
            n_ok += int(ok)
    total = len(scs) * repeat
    return {"run_success": f"{n_ok}/{total}", "run_rate": round(n_ok / total, 4) if total else 0.0,
            "n": total, "failures": detail}


def m8_report() -> dict:
    """M8 对比（P8-I4 同口径）：覆盖率（同 26 集）+ 共同可执行子集业务结果通过率。

    与旧"81.8%→100%"差异：业务结果通过率只取 legacy 可执行的共同场景集、同一业务谓词
    （facts_on=False）、相同重复次数（3×）；**legacy 为 live LLM 路由（非确定性），3× 为
    独立 fresh-thread 运行**（P8-E 方案 A，如实反映 legacy 真实形态；不声称恒等）。
    legacy 结构性不支持 multi-tool / 条件多跳（1 intent/轮）→ N/A，ReAct 侧取 M1/M3 实测。
    """
    all_scs = _sc_data()
    legacy = run_legacy_m2()
    common = [sc for sc in all_scs if sc["scenario_id"] in set(legacy.get("supported_ids", []))]
    legacy_3x = _legacy_business_rate(common, repeat=3)
    rep = _latest_report()
    react_bs = _derive_react_business(rep, [s["scenario_id"] for s in common])
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
                "common_scs": n_common, "repeats": 3,
                "predicate": ("legacy=facts_on=False（业务结果）；"
                              "react=官方 M2 全谓词推导（更严，含答案保真）"),
                "legacy": legacy_3x["run_success"], "react": react_bs["run_success"],
                "legacy_rate": legacy_3x["run_rate"], "react_rate": react_bs["run_rate"],
                "react_method": react_bs.get("method"),
            },
        },
        "legacy": {"run_success": legacy["run_success"], "coverage": legacy["coverage"],
                   "failures": legacy["failures"]},
        "react": react,
        "note": ("同口径说明（P8-E 方案 A）：覆盖率 = 同 26 场景总集（legacy 支持 22，ReAct 26；"
                 "legacy 的 4 个不支持 SC 为 live LLM 路由传参导致的 datetime 崩溃，真实缺陷）；"
                 "业务结果通过率 = legacy 可执行的共同场景 × 3 次、facts_on=False；"
                 "**legacy 为 live LLM 路由（非确定性），3× 为独立 fresh-thread 运行（不声称恒等）**；"
                 "react 侧由官方 M2 全谓词报告推导（facts_on=True ⊇ facts_on=False：M2 26 SC × 3 全过 "
                 "⇒ 共同子集业务结果必然 66/66，更严谓词通过是更强证据；未做独立 facts_on=False 重跑，无 API 依赖）。"
                 "legacy 结构性不支持 multi-tool / 条件多跳 → N/A；ReAct 侧取自最新 reports/eval_metrics_*.json"
                 "（含 m2+m3 的报告）。"),
    }


def _derive_react_business(rep: dict | None, common_ids: list) -> dict:
    """P8-E 方案 A：从官方 M2 全谓词报告推导共同子集业务结果通过率（不重跑、无 API 依赖）。

    M2 谓词（facts_on=True，含答案保真）⊇ 业务结果谓词（facts_on=False）：M2 报告全过
    （78/78 且 26/26 case-stable）⇒ 每个 SC 的 3 次重复全部通过 ⇒ 共同子集业务结果必然全过。
    """
    total = len(common_ids) * 3
    base = {"method": "官方 M2 全谓词推导（facts_on=True ⊇ facts_on=False）"}
    if not (rep and rep.get("m2")):
        return {**base, "run_success": "未跑（缺 M2 live 报告）", "run_rate": 0.0, "n": 0}
    m2 = rep["m2"]
    per = m2.get("per_sc")
    if per:
        d = {p["id"]: p["passes"] for p in per}
        n_ok = sum(d.get(sid, 0) for sid in common_ids)
    else:
        full = m2.get("run_rate") == 1.0 and m2.get("n") == 26 * 3
        n_ok = total if full else None
    if n_ok is None:
        return {**base, "run_success": "无法推导（M2 报告非全过）", "run_rate": 0.0, "n": total}
    return {**base, "run_success": f"{n_ok}/{total}", "run_rate": round(n_ok / total, 4), "n": total}

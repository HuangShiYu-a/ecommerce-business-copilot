"""M2 每 workflow 业务结果谓词（C1，V1.2.3）。

谓词 = 业务结果 + 约束 + 副作用 + Final Answer Fidelity，作用于 run_agent_react 的
response 信封（{message, status, approval_required, result}）。返回 (ok, detail)。
per-workflow 语义见 evaluation-plan-v1.md §2.4 / §3.2；predicate_for(sc) 按 SC 派发。
"""
from __future__ import annotations

from .judgments import check_facts


# ---- CS-06 履约 ----

def cs06(expected_route: str, facts: dict | None = None):
    def p(response):
        result = response.get("result") or {}
        ok = result.get("route") == expected_route
        detail = {"route": result.get("route"), "expected": expected_route}
        if ok and facts:
            ok = check_facts(response.get("message", ""), facts)
        return ok, detail
    return p


# ---- CS-08 退货（查询 / 两路径）----

def cs08_eligibility(expected_decision: str, facts: dict | None = None):
    def p(response):
        result = response.get("result") or {}
        ok = result.get("decision") == expected_decision
        detail = {"decision": result.get("decision"), "expected": expected_decision}
        if ok and facts:
            ok = check_facts(response.get("message", ""), facts)
        return ok, detail
    return p


def cs08_already_exists(facts: dict | None = None):
    """H1：已有成功退货单 → 短路 already_exists（不 interrupt、不调 T-X-01）。"""
    def p(response):
        result = response.get("result") or {}
        ok = (result.get("status") == "already_exists"
              and response.get("approval_required") is False)
        detail = {"status": result.get("status"),
                  "approval_required": response.get("approval_required")}
        if ok and facts:
            ok = check_facts(response.get("message", ""), facts)
        return ok, detail
    return p


# ---- OP-03 慢销（候选非空/空 + 命中 SKU，不引用 units）----

def op03(expected: str, sku: str | None = None):
    def p(response):
        result = response.get("result") or {}
        cands = result.get("candidates") or []
        codes = {c.get("sku_code") for c in cands}
        if expected == "HAS_CANDIDATES":
            ok = bool(cands) and (sku is None or sku in codes)
        else:  # EMPTY
            ok = not cands
        return ok, {"n_candidates": len(cands), "has_sku": sku in codes if sku else None}
    return p


# ---- OP-04 缺货风险（HIGH / NORMAL / 未定）----

def op04(expected: str):
    def p(response):
        result = response.get("result") or {}
        rl = result.get("risk_level")
        if expected == "HAS_RISK":
            ok = rl == "HIGH"
        elif expected == "NO_RISK":
            ok = rl == "NORMAL"
        else:  # UNDETERMINED（缺销售窗等无法判定）
            ok = rl in (None, "UNDETERMINED") or bool(result.get("error_code"))
        return ok, {"risk_level": rl}
    return p


# ---- OP-05 补货 workflow（HAS_RECO 经 resume 后 confirmed / NO_RECO / 未定）----

def op05(expected: str):
    def p(response):
        result = response.get("result") or {}
        st = result.get("status")
        if expected == "HAS_RECO":
            ok = st == "confirmed"
        elif expected == "NO_RECO":
            ok = st == "no_reco"
        else:  # UNDETERMINED（缺 lead_time 配置等）
            ok = st in ("undetermined", None) or bool(result.get("error_code"))
        return ok, {"status": st}
    return p


# ---- OP-07 商品健康度（route=None，冒烟：工具 ok + 有评分）----

def op07(_trigger: str | None = None):
    def p(response):
        result = response.get("result") or {}
        ok = result.get("score") is not None and not result.get("error_code")
        return ok, {"score": result.get("score")}
    return p


# ---- OP-08 销售异常（ANOMALY / NORMAL / 未定）----

def op08(expected: str):
    def p(response):
        result = response.get("result") or {}
        ia = result.get("is_anomaly")
        if expected == "ANOMALY":
            ok = ia is True
        elif expected == "NORMAL":
            ok = ia is False
        else:  # UNDETERMINED
            ok = ia is None or bool(result.get("error_code"))
        return ok, {"is_anomaly": ia}
    return p


# ---- ISO 跨店读（source_store 标注）----

def iso_cross_store():
    def p(response):
        result = response.get("result") or {}
        ok = result.get("source_store") == 2
        return ok, {"source_store": result.get("source_store")}
    return p


# ---- 按 SC 派发 ----

def predicate_for(sc: dict):
    """sc：data/scenarios/eval/scenarios.yaml 里的一条 data SC → 谓词闭包。"""
    wf = sc.get("workflow")
    sid = sc.get("scenario_id")
    route = sc.get("expected_route")
    facts = FACTS.get(sid)
    if wf == "CS-06":
        return cs06(route, facts)
    if wf == "CS-08":
        if sid == "SC-CS08-006":       # 预置已成功售后 → already_exists（H1）
            return cs08_already_exists(facts)
        return cs08_eligibility(route, facts)
    if wf == "OP-03":
        sku = (sc.get("sku_ids") or [None])[0]
        return op03(route, sku)
    if wf == "OP-04":
        return op04(route)
    if wf == "OP-05":
        return op05(route)
    if wf == "OP-07":
        return op07(route)
    if wf == "OP-08":
        return op08(route)
    if wf == "ISO":
        return iso_cross_store()
    raise ValueError(f"未支持 workflow: {wf}")


# ---- 每 SC 的 Final Answer required_facts（答案保真，V1.2.3）----

FACTS: dict[str, dict] = {
    # CS-06：答案含延误/正常结论（不反向）
    "SC-CS06-001": {"延误": None},
    "SC-CS06-002": {"延误": None},
    "SC-CS06-003": {"延误": None},
    # CS-08：答案含资格结论
    "SC-CS08-001": {"可以退货": None},
    "SC-CS08-002": {"不能退": None, "窗口": None},
    "SC-CS08-003": {"退货": None, "待定": None},
    "SC-CS08-006": {"已有": None, "退货": None},
    # OP-03 / OP-04 / OP-05 / OP-07 / OP-08 / ISO：结论词（宽松）
    "SC-OP03-001": {"慢销": None},
    "SC-OP03-003": {"慢销": None},
    "SC-OP04-001": {"缺货": None},
    "SC-OP04-002": {"缺货": None},
    "SC-OP05-001": {"补货": None},
    "SC-OP05-002": {"补货": None},
    "SC-OP08-001": {"异常": None},
    "SC-OP08-002": {"正常": None},
    "SC-ISO-001": {"门店": None},
}

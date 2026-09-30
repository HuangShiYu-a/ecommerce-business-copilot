"""Workflow 执行器（Spec-1 §3.5 契约）：Runtime → Workflow 的边界。

DEPRECATED：本模块的 OP-05/CS-08 流程逻辑已被 toolkit.py 的 workflow 工具
（make_op05_workflow_tool / make_cs08_workflow_tool）取代；仅 AGENT_BACKEND=legacy
回退的 legacy orchestrator 使用。改动请优先作用于 toolkit 版，避免两处漂移。

Runtime 不把完整 AgentRuntimeState 传给 workflow，只传最小输入（WorkflowInput），
回收结构化结果（WorkflowResult）。Workflow 内部语义（计算/映射）不暴露给 Runtime。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..context import ops_ctx
from ..tool import run_tool


@dataclass
class WorkflowInput:
    task_id: str
    user_id: int
    store_id: int
    intent: str
    slots: dict
    context_refs: dict | None = None


@dataclass
class WorkflowResult:
    formal_result: dict = field(default_factory=dict)
    status: str = "completed"          # completed | undetermined | terminated | error
    route_status: str | None = None    # 如 HAS_RECO / NO_RECO / UNDETERMINED
    evidence_refs: list[str] = field(default_factory=list)
    next_step: str | None = None
    confirmation_required: bool = False


# ---- OP-05：补货建议（T-R-01）----

def _op05(ctx, sku_code: str, horizon_days: int | None, lead_time: int | None) -> WorkflowResult:
    params = {"sku_code": sku_code}
    if horizon_days is not None:
        params["horizon_days"] = horizon_days
    if lead_time is not None:
        params["lead_time_days"] = lead_time
    res = run_tool("T-R-01", ctx, **params)
    if res.ok:
        route = "HAS_RECO" if res.data.get("recommended_quantity", 0) > 0 else "NO_RECO"
        return WorkflowResult(
            formal_result=res.data, route_status=route,
            status="completed",
            confirmation_required=(route == "HAS_RECO"),   # 有补货建议 → 需确认（Spec-1 §9.2）
        )
    if res.error_code == "DATA_UNAVAILABLE":
        return WorkflowResult(
            formal_result={"error_detail": res.error_detail},
            route_status="UNDETERMINED", status="undetermined",
        )
    if res.error_code == "FORBIDDEN":
        return WorkflowResult(
            formal_result={"error_code": "FORBIDDEN", "error_detail": res.error_detail},
            route_status="FORBIDDEN", status="error",
        )
    return WorkflowResult(
        formal_result={"error_code": res.error_code, "error_detail": res.error_detail},
        route_status=f"ERROR({res.error_code})", status="error",
    )


# ---- OP-04：缺货风险（T-A-07）----

def _op04(ctx, sku_code: str, forecast_days: int | None) -> WorkflowResult:
    params = {"sku_code": sku_code}
    if forecast_days is not None:
        params["forecast_days"] = forecast_days
    res = run_tool("T-A-07", ctx, **params)
    if res.ok:
        route = "HAS_RISK" if res.data.get("risk_level") == "HIGH" else "NO_RISK"
        return WorkflowResult(formal_result=res.data, route_status=route, status="completed")
    if res.error_code == "DATA_UNAVAILABLE":
        return WorkflowResult(
            formal_result={"error_detail": res.error_detail},
            route_status="UNDETERMINED", status="undetermined",
        )
    if res.error_code == "FORBIDDEN":
        return WorkflowResult(
            formal_result={"error_code": "FORBIDDEN", "error_detail": res.error_detail},
            route_status="FORBIDDEN", status="error",
        )
    return WorkflowResult(
        formal_result={"error_code": res.error_code, "error_detail": res.error_detail},
        route_status=f"ERROR({res.error_code})", status="error",
    )


# ---- OP-07：商品健康度（T-A-05）----

def _op07(ctx, sku_code: str, window_days: int | None) -> WorkflowResult:
    from ..tool import run_tool as _rt
    params = {"sku_code": sku_code}
    if window_days is not None:
        params["window_days"] = window_days
    res = _rt("T-A-05", ctx, **params)
    if res.ok:
        return WorkflowResult(formal_result=res.data, route_status="HEALTHY", status="completed")
    if res.error_code == "DATA_UNAVAILABLE":
        return WorkflowResult(formal_result={"error_detail": res.error_detail},
                              route_status="UNDETERMINED", status="undetermined")
    if res.error_code == "FORBIDDEN":
        return WorkflowResult(formal_result={"error_code": "FORBIDDEN", "error_detail": res.error_detail},
                              route_status="FORBIDDEN", status="error")
    return WorkflowResult(
        formal_result={"error_code": res.error_code, "error_detail": res.error_detail},
        route_status=f"ERROR({res.error_code})", status="error",
    )


# ---- OP-08：销售异常（T-A-06）----

def _op08(ctx, sku_code: str, baseline_policy: str | None) -> WorkflowResult:
    from ..tool import run_tool as _rt
    params = {"sku_code": sku_code}
    if baseline_policy:
        params["baseline_policy"] = baseline_policy
    res = _rt("T-A-06", ctx, **params)
    if res.ok:
        route = "ANOMALY" if res.data.get("is_anomaly") else "NORMAL"
        return WorkflowResult(formal_result=res.data, route_status=route, status="completed")
    if res.error_code == "DATA_UNAVAILABLE":
        return WorkflowResult(formal_result={"error_detail": res.error_detail},
                              route_status="UNDETERMINED", status="undetermined")
    if res.error_code == "FORBIDDEN":
        return WorkflowResult(formal_result={"error_code": "FORBIDDEN", "error_detail": res.error_detail},
                              route_status="FORBIDDEN", status="error")
    return WorkflowResult(
        formal_result={"error_code": res.error_code, "error_detail": res.error_detail},
        route_status=f"ERROR({res.error_code})", status="error",
    )


# ---- OP-03：慢销候选筛选（T-A-04 mode=slow_moving）----

def _op03(ctx, sku_code: str | None, category: str | None) -> WorkflowResult:
    from ..tool import run_tool as _rt
    params = {"mode": "slow_moving"}
    if sku_code:
        params["sku_code"] = sku_code
    if category:
        params["category"] = category
    res = _rt("T-A-04", ctx, **params)
    if res.ok:
        route = "HAS_CANDIDATES" if res.data.get("candidates") else "EMPTY"
        return WorkflowResult(formal_result=res.data, route_status=route, status="completed")
    if res.error_code == "DATA_UNAVAILABLE":
        return WorkflowResult(formal_result={"error_detail": res.error_detail},
                              route_status="UNDETERMINED", status="undetermined")
    if res.error_code == "FORBIDDEN":
        return WorkflowResult(formal_result={"error_code": "FORBIDDEN", "error_detail": res.error_detail},
                              route_status="FORBIDDEN", status="error")
    return WorkflowResult(
        formal_result={"error_code": res.error_code, "error_detail": res.error_detail},
        route_status=f"ERROR({res.error_code})", status="error",
    )


# ---- CS-06：物流履约异常（T-A-01）----

def _cs06(ctx, order_no: str) -> WorkflowResult:
    from ..tool import run_tool as _rt
    res = _rt("T-A-01", ctx, order_no=order_no)
    if res.ok:
        return WorkflowResult(formal_result=res.data, route_status=res.data.get("status"),
                              status="completed")
    if res.error_code == "DATA_UNAVAILABLE":
        return WorkflowResult(formal_result={"error_detail": res.error_detail},
                              route_status="UNDETERMINED", status="undetermined")
    if res.error_code == "FORBIDDEN":
        return WorkflowResult(formal_result={"error_code": "FORBIDDEN", "error_detail": res.error_detail},
                              route_status="FORBIDDEN", status="error")
    return WorkflowResult(
        formal_result={"error_code": res.error_code, "error_detail": res.error_detail},
        route_status=f"ERROR({res.error_code})", status="error",
    )


# ---- CS-08：退货资格判定（T-A-09，RAG 消解）----

def _cs08(ctx, order_no: str) -> WorkflowResult:
    from ..tool import run_tool as _rt
    res = _rt("T-A-09", ctx, order_no=order_no)
    if res.ok:
        # H1：已有成功退货单 → 不再触发 N6 确认/建单（与 ReAct 版短路对齐）
        if res.data.get("existing_return"):
            existing = res.data.get("existing_return")
            return WorkflowResult(
                formal_result={"status": "already_exists",
                               "request_no": existing.get("request_no"),
                               "message": f"订单 {order_no} 已有退货申请"
                                          f"（{existing.get('request_no')}），不再重复创建"},
                route_status="already_exists", status="completed",
                confirmation_required=False,
            )
        decision = res.data.get("decision", "undetermined")
        return WorkflowResult(
            formal_result=res.data, route_status=decision, status="completed",
            confirmation_required=(decision == "eligible"),   # eligible → N6 客服确认（WF §5.1）
        )
    if res.error_code == "DATA_UNAVAILABLE":
        return WorkflowResult(formal_result={"error_detail": res.error_detail},
                              route_status="UNDETERMINED", status="undetermined")
    if res.error_code == "FORBIDDEN":
        return WorkflowResult(formal_result={"error_code": "FORBIDDEN", "error_detail": res.error_detail},
                              route_status="FORBIDDEN", status="error")
    return WorkflowResult(
        formal_result={"error_code": res.error_code, "error_detail": res.error_detail},
        route_status=f"ERROR({res.error_code})", status="error",
    )


def run_workflow(wf_input: WorkflowInput) -> WorkflowResult:
    """按 intent 分发到对应 workflow 执行器；未知 workflow → error。"""
    ctx = ops_ctx(wf_input.store_id)
    if wf_input.intent == "restock_recommendation":
        return _op05(
            ctx,
            sku_code=wf_input.slots.get("sku_code", ""),
            horizon_days=wf_input.slots.get("horizon_days"),
            lead_time=wf_input.slots.get("lead_time_days"),
        )
    if wf_input.intent == "stockout_risk":
        return _op04(ctx, sku_code=wf_input.slots.get("sku_code", ""),
                     forecast_days=wf_input.slots.get("horizon_days"))
    if wf_input.intent == "product_health":
        return _op07(ctx, sku_code=wf_input.slots.get("sku_code", ""),
                     window_days=wf_input.slots.get("window_days"))
    if wf_input.intent == "sales_anomaly":
        return _op08(ctx, sku_code=wf_input.slots.get("sku_code", ""),
                     baseline_policy=wf_input.slots.get("baseline_policy"))
    if wf_input.intent == "slow_moving":
        return _op03(ctx, sku_code=wf_input.slots.get("sku_code"),
                     category=wf_input.slots.get("category"))
    if wf_input.intent == "fulfillment_delay":
        return _cs06(ctx, order_no=wf_input.slots.get("order_no", ""))
    if wf_input.intent == "return_eligibility":
        return _cs08(ctx, order_no=wf_input.slots.get("order_no", ""))
    return WorkflowResult(status="error", formal_result={"error_detail": f"未实现 workflow: {wf_input.intent}"})

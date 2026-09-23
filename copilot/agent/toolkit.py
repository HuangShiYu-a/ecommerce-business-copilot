"""Agent 工具层（Phase 1）：10 个直连工具 → LangChain StructuredTool。

设计要点（对齐 V1.5.2 W1.2~1.4）：
- **args_schema**：复用各工具现成 pydantic `Input` 类，零额外定义
- **ctx 注入**：经 `ctx_provider` 在**调用时**解析（不把会话 ctx 闭包进缓存的 agent，符合
  D9/D12 决策意图）；Phase 1 demo 传固定 ctx，Phase 2 换 langgraph runtime 后端
- **D11 投影**：返回经 `_project()` 裁剪，V1 只删确定冗余字段（id/store_id/customer_id/user_id）
- **错误语义**：工具失败返回 `{error_code, error_detail}`（不 raise），LLM 如实转述（R4）
- **目录过滤（W1.4）**：按 Workspace Mode 过滤；UNSET=交集（同时允许两角色）
- **纯新增**：不接入运行时（Phase 2），不影响 legacy 135 测试

说明（最小安全幅度取舍）：LLM 面向的描述放在本模块（W1.3 意图），不改 10 个工具文件
的描述字段（Tool Contract 元数据保持原样）。
"""
from __future__ import annotations

from collections.abc import Callable

from langchain_core.tools import StructuredTool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from ..calc.orders import get_order_detail
from ..config import AS_OF_DATE
from ..context import UserContext
from ..db import connect
from ..tools import (AnalyzeFulfillmentDelay, AnalyzeSalesAnomaly,
                     AnalyzeStockoutRisk, CalculateProductHealth,
                     CalculateRestockRecommendation, CheckReturnEligibility,
                     CreateReturnRequest, GetInventory, GetOrder,
                     GetShippingStatus, QueryProductPerformance,
                     SearchBusinessKnowledge)

# ---- W1.3：LLM 面向描述（8 字段要义：做什么/何时用/何时不用/输入/权威性）----

_DESCRIPTIONS: dict[str, str] = {
    "get_inventory": (
        "按 SKU 查询当前可用库存/安全库存/再订货点。"
        "用于：用户问『XX 库存多少/还剩多少/够不够』。需要 sku_code（或 sku_id）。"
        "返回即正式库存事实（Authoritative=Yes）。"),
    "get_order": (
        "按订单号查询订单详情（状态/关键时间/明细行/商品类目）。"
        "用于：订单查询、售后判定的事实支撑。需要 order_no。"
        "**不要**用于『真正发起退货』——那走 CS-08 workflow。返回即正式订单事实。"),
    "get_shipping_status": (
        "按订单号查询物流状态与最新轨迹事件。"
        "用于：『物流到哪了/发货没有/送到没』。需要 order_no。返回即正式物流事实。"),
    "search_business_knowledge": (
        "检索业务知识/规则（退货政策/物流时效/SOP/话术等），返回命中的规则片段。"
        "用于：政策/规则类问答。参数 query 用整句问题。结果仅作证据参考，非正式裁定。"),
    "analyze_fulfillment_delay": (
        "按订单号判定物流履约（NORMAL/ANOMALY/UNDETERMINED）：超 promised 未按时送达→ANOMALY。"
        "用于：『有没有延误/超时未送达』。需要 order_no。返回即正式判定。"),
    "check_return_eligibility": (
        "按订单号判定退货资格三态（eligible/ineligible/undetermined）。"
        "用于：『能退吗/退货资格』。需要 order_no。"
        "**不要**用于『真正发起退货』——那走 CS-08 workflow。返回即正式资格判定。"),
    "query_product_performance": (
        "低动销候选筛选（mode=slow_moving）。"
        "用于：『有没有慢销/滞销商品』。给 sku_code 单查或 category 类目扫描（二选一）。"
        "返回即正式候选清单。"),
    "calculate_product_health": (
        "按 SKU 计算商品健康度（五核心维 + 完整度 + 评分/等级）。"
        "用于：『健康度/完整度怎么样』。需要 sku_code（window_days 可选）。返回即正式健康判定。"),
    "analyze_sales_anomaly": (
        "按 SKU 判定销售异常（近 7 天 vs 前 7 天，阈值来自 StoreConfig）。"
        "用于：『销售异常/骤降/暴涨』。需要 sku_code。返回即正式异常判定。"),
    "analyze_stockout_risk": (
        "按 SKU 评估缺货风险等级（HIGH/NORMAL），支持 forecast_days 时间窗。"
        "用于：『缺货风险/会不会断货/够不够卖』。需要 sku_code（forecast_days 可选）。返回即正式风险判定。"),
}

# ---- D11：V1 只删确定冗余字段 ----

_REDUNDANT_KEYS = {"id", "store_id", "customer_id", "user_id"}


def _project(value):
    """递归删除确定冗余字段（内部 id/store_id/customer_id/user_id），保留业务字段（含 items）。"""
    if isinstance(value, dict):
        return {k: _project(v) for k, v in value.items() if k not in _REDUNDANT_KEYS}
    if isinstance(value, list):
        return [_project(v) for v in value]
    return value


# ---- 10 直连工具 ----

DIRECT_TOOLS = [
    GetInventory, GetOrder, GetShippingStatus, SearchBusinessKnowledge,
    AnalyzeFulfillmentDelay, CheckReturnEligibility,
    QueryProductPerformance, CalculateProductHealth,
    AnalyzeSalesAnomaly, AnalyzeStockoutRisk,
]


def make_langchain_tool(tool_cls, ctx_provider: Callable[[], UserContext]) -> StructuredTool:
    """把一个 Tool 子类转成 LangChain StructuredTool。

    ctx_provider 在每次调用时解析 ctx；工具失败返回结构化 error dict（不 raise）。
    """
    def _run(**params):
        ctx = ctx_provider()
        conn = connect()
        try:
            res = tool_cls(conn).run(ctx, **params)
        finally:
            conn.close()
        if res.ok:
            return _project(res.data)
        return {"error_code": res.error_code, "error_detail": res.error_detail}

    return StructuredTool.from_function(
        func=_run,
        name=tool_cls.name,
        description=_DESCRIPTIONS.get(tool_cls.name, tool_cls.description),
        args_schema=tool_cls.input_model,
    )


# ---- W1.4：Workspace Mode 目录过滤 ----

def _catalog_classes(mode: str) -> list:
    """按 Workspace Mode 过滤 10 直连工具。UNSET=交集（同时允许两角色）。"""
    if mode == "OPERATIONS":
        return [c for c in DIRECT_TOOLS if "operations" in c.allowed_roles]
    if mode == "CUSTOMER_SERVICE":
        return [c for c in DIRECT_TOOLS if "customer_service" in c.allowed_roles]
    # UNSET：交集（同时允许两角色才可见）
    return [c for c in DIRECT_TOOLS
            if c.allowed_roles and {"customer_service", "operations"} <= set(c.allowed_roles)]


def catalog_names(mode: str) -> list[str]:
    """某模式下的工具名清单（UNSET/OPERATIONS/CUSTOMER_SERVICE）。"""
    return [c.name for c in _catalog_classes(mode)]


# ---- W2.9：request_capability meta-tool（恒在，所有模式可见）----

def make_request_capability_tool() -> StructuredTool:
    """能力协商 meta-tool（D10=a+）。

    类比 Unix sudo：不调业务数据、不改业务状态，仅发起"切换到更高能力域"的请求；
    真正的 Workspace Mode 变更必须用户确认（react.py 捕获该调用 → capability_pending）。
    """
    def _request(domain: str) -> dict:
        return {
            "capability_requested": domain,
            "status": "pending",
            "note": "已请求切换到该能力域，等待用户确认。",
        }

    return StructuredTool.from_function(
        func=_request,
        name="request_capability",
        description=(
            "请求切换到更高的能力域（customer_service / operations）。"
            "用于：当前任务需要当前 Workspace Mode 目录之外的专属工具时（如 UNSET 下需要"
            "缺货风险/退货建单等）。仅发起请求，切换需用户确认，本工具不执行任何业务查询。"),
        args_schema=RequestCapabilityInput,
    )


# ---- W3.1/W3.2：审批 workflow 工具（T-X-01 不暴露给 LLM，D1/R10）----

class CS08ReturnInput(BaseModel):
    order_no: str = Field(description="订单号，如 ORD_01_000438")
    reason: str | None = Field(default=None, description="退货原因（可选）")


def make_cs08_workflow_tool(ctx_provider: Callable[[], UserContext]) -> StructuredTool:
    """CS-08 退货 workflow（客服专属）。

    内部链：T-A-09 资格判定（确定性三态）→ eligible → **interrupt 人审** → 确认后
    T-X-01 建单 + 审计 + 幂等。资格/审批触发均由结构化结果决定（R5）；写前已重验资格（R10）。
    T-X-01 不裸露给 LLM——LLM 只能调用本 workflow 工具。
    """
    def _run(order_no: str, reason: str | None = None, **kw) -> dict:
        ctx = ctx_provider()
        conn = connect()
        try:
            res = CheckReturnEligibility(conn).run(ctx, order_no=order_no)
            if not res.ok:
                return {"error_code": res.error_code, "error_detail": res.error_detail}
            data = res.data
            if data.get("decision") != "eligible":
                # 不可退/未决 → 不触发 interrupt，直接返回（R5）
                return {"decision": data.get("decision"),
                        "reason_code": data.get("reason_code"),
                        "explanation": data.get("explanation"),
                        "existing_return": data.get("existing_return")}
            order = get_order_detail(conn, ctx.store_id, order_no=order_no)
            if order is None or not order.get("items"):
                return {"error_code": "DATA_UNAVAILABLE", "error_detail": "订单无明细行"}
            item = order["items"][0]
            decision = interrupt({
                "type": "approval", "workflow": "CS-08", "order_no": order_no,
                "order_id": order["id"], "item_id": item["id"],
                "quantity": int(item["quantity"]), "reason": reason or "无理由退货",
                "message": f"订单 {order_no} 符合退货资格，是否创建退货申请？",
            })
            if not (decision and decision.get("decision") == "approved"):
                return {"decision": "cancelled", "order_no": order_no,
                        "explanation": "已取消退货申请"}
            request_id = f"CS08-{order['id']}-{item['id']}"   # 幂等键（重放返回原单）
            res2 = CreateReturnRequest(conn).run(
                ctx, order_id=order["id"], item_id=item["id"],
                quantity=int(item["quantity"]), reason=reason or "无理由退货",
                request_id=request_id,
                approval={"decision": "approved", "approver_id": ctx.user_id,
                          "approved_at": AS_OF_DATE, "comment": "HITL 人工确认"})
            if res2.ok:
                return {**res2.data, "eligible_reason": data.get("reason_code")}
            return {"error_code": res2.error_code, "error_detail": res2.error_detail}
        finally:
            conn.close()

    return StructuredTool.from_function(
        func=_run, name="cs08_return_workflow",
        description=(
            "退货流程工具（CS-08）：按订单号走完整退货申请流程——资格判定 → 人工确认 → "
            "创建退货申请（含审计）。用于：用户要求『真正发起退货/申请退货』（不是只问资格）。"
            "需要 order_no（reason 可选）。资格判定与建单均以系统结果为准。"),
        args_schema=CS08ReturnInput,
    )


class OP05RestockInput(BaseModel):
    sku_code: str = Field(description="SKU 编码，如 SKU_01_STOCKOUT_01")
    horizon_days: int | None = Field(default=None, description="补货展望天数（可选）")
    lead_time_days: int | None = Field(default=None, description="采购周期天数（可选）")


def make_op05_workflow_tool(ctx_provider: Callable[[], UserContext]) -> StructuredTool:
    """OP-05 补货 workflow（运营专属）。

    内部链：T-R-01 建议 → HAS_RECO → **interrupt 确认** → 确认=记录确认事件
    （V1 无采购单写工具，不写业务表）。触发审批由结构化 HAS_RECO 决定（R5）。
    """
    def _run(sku_code: str, horizon_days: int | None = None,
             lead_time_days: int | None = None, **kw) -> dict:
        ctx = ctx_provider()
        conn = connect()
        try:
            res = CalculateRestockRecommendation(conn).run(
                ctx, sku_code=sku_code, horizon_days=horizon_days,
                lead_time_days=lead_time_days)
            if not res.ok:
                return {"error_code": res.error_code, "error_detail": res.error_detail}
            data = res.data
            rec = int(data.get("recommended_quantity") or 0)
            if rec <= 0:
                return {**data, "status": "no_reco"}   # 无建议不 interrupt
            decision = interrupt({
                "type": "approval", "workflow": "OP-05", "sku_code": sku_code,
                "recommended_quantity": rec,
                "message": f"建议补货 {rec} 件，是否确认执行？",
            })
            if not (decision and decision.get("decision") == "approved"):
                return {**data, "status": "cancelled"}
            return {**data, "status": "confirmed"}   # V1 仅记录确认事件（不写业务表）
        finally:
            conn.close()

    return StructuredTool.from_function(
        func=_run, name="op05_restock_workflow",
        description=(
            "补货流程工具（OP-05）：按 SKU 计算补货建议并走人工确认（有建议时）。"
            "用于：用户要『补货/补仓/确认补货』的完整流程。需要 sku_code（horizon_days/"
            "lead_time_days 可选）。建议量以系统计算结果为准。"),
        args_schema=OP05RestockInput,
    )


def build_toolkit(mode: str, ctx_provider: Callable[[], UserContext]) -> list[StructuredTool]:
    """返回该模式下的 LangChain 工具列表（直连 + 审批 workflow + request_capability）。

    - OPERATIONS：10 直连 + OP-05 workflow
    - CUSTOMER_SERVICE：6 公共直连 + CS-08 workflow
    - UNSET：6 公共直连（无 workflow）
    - 均含恒在 request_capability meta-tool
    """
    tools = [make_langchain_tool(c, ctx_provider) for c in _catalog_classes(mode)]
    if mode == "OPERATIONS":
        tools.append(make_op05_workflow_tool(ctx_provider))
    elif mode == "CUSTOMER_SERVICE":
        tools.append(make_cs08_workflow_tool(ctx_provider))
    tools.append(make_request_capability_tool())
    return tools


class RequestCapabilityInput(BaseModel):
    domain: str = Field(description="请求切换到的能力域：customer_service / operations")

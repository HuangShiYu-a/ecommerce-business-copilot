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
from pydantic import BaseModel, Field

from ..context import UserContext
from ..db import connect
from ..tools import (AnalyzeFulfillmentDelay, AnalyzeSalesAnomaly,
                     AnalyzeStockoutRisk, CalculateProductHealth,
                     CheckReturnEligibility, GetInventory, GetOrder,
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


def build_toolkit(mode: str, ctx_provider: Callable[[], UserContext]) -> list[StructuredTool]:
    """返回该模式下的 LangChain 工具列表（直连 + 恒在 request_capability meta-tool）。

    Phase 1 仅含 10 直连工具；workflow 工具（OP-05/CS-08）在 Phase 3 加入。
    """
    return ([make_langchain_tool(c, ctx_provider) for c in _catalog_classes(mode)]
            + [make_request_capability_tool()])


class RequestCapabilityInput(BaseModel):
    domain: str = Field(description="请求切换到的能力域：customer_service / operations")

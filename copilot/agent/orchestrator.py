"""Runtime Orchestrator（Spec-1 §3）：单 Agent Runtime Graph。

DEPRECATED：仅 AGENT_BACKEND=legacy 回退使用；新架构（ReAct）见 copilot/agent/react.py。

节点流：pending_check → router → guardrails → resolver → dispatcher
        → tool_node / workflow_node → finalize；
        handle_pending 处理挂起任务（confirm / slot_fill），clarify 最小澄清。

关键语义（Spec-1）：
- Pending Task Check 优先于重新路由（§3.1）。
- Router 只出语义，执行路径由 Intent Registry 决定（§8）。
- HITL confirm 为 Runtime 级状态机（§9.2），非 LangGraph interrupt。
- LLM 只解释不裁定：正式结论来自 Tool/Workflow（R4）。
"""
from __future__ import annotations

import time
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .. import llm
from ..context import ops_ctx
from ..tool import run_tool
from .context import ContextInput, assemble
from .persona import capability_intro
from .registry import resolve
from .router import extract_entities, route_rules
from .state import COMPLETED, RUNNING, TERMINATED, WAITING_USER_INPUT
from .trace import Trace
from .workflows import WorkflowInput, run_workflow


class AgentRuntimeState(TypedDict, total=False):
    session: dict          # {session_id, user_id, role, store_id}
    message: str           # 当前用户消息
    routing: dict          # {intent, entities, missing_slots, low_confidence}
    conversation: list     # [{role, content}] 历史（finalize 追加）
    task: dict             # {intent, slots, missing_slots, status, current_step, pending_type}
    execution: dict        # {run_id, trace, phase, kind, intent, tool_result, workflow_result}
    response: dict         # {message, status, needs_user_input, approval_required, result}


def _new_task(routing: dict) -> dict:
    return {
        "intent": routing.get("intent"),
        "slots": dict(routing.get("entities", {})),
        "missing_slots": [],
        "status": RUNNING,
        "current_step": "router",
        "pending_type": None,
    }


def _emit(exec_: dict, type_: str, step: str,
          status: str = "success", payload: dict | None = None) -> dict:
    """向 execution.trace 追加 Domain Trace Event（Spec-1 §13）。"""
    events = list(exec_.get("trace", []))
    events.append({
        "type": type_, "run_id": exec_.get("run_id", ""), "step": step,
        "status": status, "payload": payload or {}, "timestamp": time.time(),
    })
    exec_["trace"] = events
    return exec_


# ---- 节点 ----

def pending_check(state: AgentRuntimeState) -> dict:
    task = state.get("task")
    if task and task.get("status") == WAITING_USER_INPUT:
        return {"execution": {**state.get("execution", {}), "pending": True}, "__next": "handle_pending"}
    return {"__next": "router"}


def handle_pending(state: AgentRuntimeState) -> dict:
    """挂起任务继续：confirm 解析确认/拒绝；slot_fill 尝试补槽。"""
    task = dict(state.get("task", {}))
    message = state.get("message", "")
    if task.get("pending_type") == "confirm":
        from ..context import approval_text_decision
        accepted = approval_text_decision(message) == "approved"   # H4：否定优先/疑问守卫
        task["status"] = COMPLETED if accepted else TERMINATED
        task["current_step"] = "confirm"
        # L3：确认话术按意图区分（退货确认不再误显补货文案）
        if accepted:
            if task.get("intent") == "return_eligibility":
                msg = "已确认，退货申请流程已启动。"
            else:
                msg = "已确认，补货建议生效。"
        else:
            msg = "已取消该操作。"
        exec_ = _emit(state.get("execution", {}), "human_confirmed", "confirm",
                      payload={"decision": "accepted" if accepted else "rejected"})
        return {"task": task, "execution": exec_, "__next": "end", "response": {
            "message": msg, "status": task["status"], "needs_user_input": False,
            "result": task.get("slots", {})}}
    if task.get("pending_type") == "slot_fill":
        missing = task.get("missing_slots", [])
        filled = {k: v for k, v in extract_entities(message).items() if k in missing}
        if filled:
            slots = dict(task.get("slots", {})); slots.update(filled)
            task["slots"] = slots
            task["missing_slots"] = [m for m in missing if m not in filled]
            task["status"] = RUNNING
            task["pending_type"] = None
            routing = dict(state.get("routing", {}))
            routing["entities"] = {**routing.get("entities", {}), **slots}
            routing["missing_slots"] = []
            exec_ = _emit(state.get("execution", {}), "step_completed", "slot_fill",
                          payload={"filled": filled})
            exec_["phase"] = "continue"
            return {"task": task, "routing": routing, "execution": exec_, "__next": "dispatcher"}
        return {"task": task, "__next": "clarify"}
    return {"__next": "router"}


def _is_continue(message: str) -> bool:
    return any(w in message for w in ("继续", "重新", "再试", "接着"))


def _resolve_default_store(entities: dict) -> int | None:
    """从实体前缀解析默认门店（ORD_x_/SKU_x_ → 店号）；无前缀 → None。"""
    from ..tool import reference_store
    for v in entities.values():
        if isinstance(v, str):
            s = reference_store(v)
            if s is not None:
                return s
    return None


def router(state: AgentRuntimeState) -> dict:
    message = state.get("message", "")
    if llm.mode() == "live":
        from .llm_router import llm_route
        result = llm_route(message, state.get("conversation"))
    else:
        result = route_rules(message)
    # 续答（A13 / §9.3）：用户说「继续/重新」→ 复用上一任务的意图与槽位重试（简单恢复）
    if _is_continue(message):
        task = state.get("task")
        if task and task.get("intent"):
            result.intent = task["intent"]
            result.entities = {**task.get("slots", {}), **result.entities}
            result.missing_slots = []
    # 裸续问（out_of_scope + 有实体 + 上一个任务）→ 沿用上一个任务的意图（多轮引用）
    elif result.intent == "out_of_scope" and result.entities:
        task = state.get("task")
        prior = task.get("intent") if task else None
        if prior and prior != "out_of_scope":
            result.intent = prior
            # F4.0：意图沿用时并入上一任务已解析槽位（续问带 SKU/订单号），
            # 但仅限「确实沿用意图」的情形——无关新话题（无实体）不会进入本分支
            result.entities = {**task.get("slots", {}), **result.entities}
    exec_ = _emit(state.get("execution", {}), "intent_detected", "router",
                  payload={"intent": result.intent, "entities": result.entities})
    exec_["phase"] = "new"
    exec_["pending"] = False

    # 方向 A：首次对话自动判定角色/门店并锁定（前端零预选）
    session = dict(state.get("session", {}))
    determined = False
    if not session.get("role"):
        session["role"] = result.role or "operations"
        determined = True
    if not session.get("store_id"):
        dstore = _resolve_default_store(result.entities)
        session["store_id"] = dstore if dstore is not None else 1   # 无门店引用 → 默认店 1
    if determined:
        exec_["role_just_determined"] = True   # 触发首次角色说明（finalize 消费，仅本轮）
    return {"routing": result.model_dump(), "execution": exec_, "session": session}


# workflow → 允许角色（阶段 4 随各 workflow 扩展；Spec-1 §4.2）
WORKFLOW_ROLES = {"OP-05": ("operations",), "OP-04": ("operations",), "OP-07": ("operations",),
                  "OP-08": ("operations",), "OP-03": ("operations",),
                  "CS-06": ("customer_service", "operations"),
                  "CS-08": ("customer_service",)}


def _clarify_ambiguous(routing: dict, role: str, message: str, store_id: int = 1) -> str:
    """F5：意图模糊时的澄清引导（选项确定性；live 由 LLM 用专用澄清提示润色措辞）。"""
    entities = routing.get("entities", {})
    sku = entities.get("sku_code")
    order = entities.get("order_no")
    if sku:
        fallback = (f"关于 {sku}，你想看哪一项？"
                    "库存 / 缺货风险 / 补货建议 / 商品健康度 / 销售异常 / 慢销。")
    elif order:
        fallback = f"关于 {order}，你想看哪一项？订单详情 / 物流状态 / 退货资格。"
    else:
        fallback = (f"你的问题有些模糊。我可以帮你：{capability_intro(role)}"
                    "请告诉我你想了解的具体内容。")
    # live：专用澄清提示（非 persona——澄清是提问不是执行，避免被当成查数据）
    if llm.mode() != "live":
        return fallback
    try:
        sys = ("你是客服/运营 Copilot 的意图澄清助手。用户意图不明确，你需要向他确认"
               "具体想看哪个维度的信息，然后请他选择。只提问、列选项，不要执行任何查询、"
               "不要编造数据、不要假装已经查到了结果。用中文，简洁，给出 2~6 个选项。")
        resp = llm.get_llm().invoke([("system", sys), ("user", message)])
        text = str(resp.content or "").strip()
        return text if text else fallback
    except Exception:
        return fallback


def guardrails(state: AgentRuntimeState) -> dict:
    routing = dict(state.get("routing", {}))
    intent = routing.get("intent")
    role = state.get("session", {}).get("role", "operations")
    path = resolve(intent)
    if path is None:  # 未知意图 → out_of_scope（Spec-1 §10.3）
        routing["intent"] = "out_of_scope"
        routing["entities"] = {}
        routing["missing_slots"] = []
        return {"routing": routing}
    # 实体键归一化：LLM 键名 → 工具 Schema 规范键（Spec-1 §10.3）
    from .router import normalize_entities
    routing["entities"] = normalize_entities(routing.get("entities", {}))
    # F5：意图模糊（LLM 低置信）→ 澄清引导，不硬猜执行（Spec-1 §9.1 歧义处理）
    if routing.get("low_confidence") and intent != "out_of_scope":
        store_id = state.get("session", {}).get("store_id", 1)
        msg = _clarify_ambiguous(routing, role, state.get("message", ""), store_id)
        task = _new_task(routing)
        task["status"] = WAITING_USER_INPUT
        task["pending_type"] = "clarify_intent"
        task["current_step"] = "clarify_intent"
        exec_ = _emit(state.get("execution", {}), "human_requested", "clarify_intent",
                      payload={"intent": intent, "entities": routing.get("entities", {})})
        return {"task": task, "routing": routing, "execution": exec_, "response": {
            "message": msg, "status": WAITING_USER_INPUT, "needs_user_input": True}}
    # 权限检查（Spec-1 §4.2 / §10.3）：direct 工具或 workflow 的允许角色
    denied = False
    required = None
    if path.kind == "direct" and path.target:
        from ..tool import TOOLS
        if not TOOLS:
            from .. import tools  # noqa: F401
        cls = TOOLS.get(path.target)
        denied = bool(cls and not cls.allows(role))
        required = cls.allowed_roles if cls else None
    elif path.kind == "workflow" and path.target:
        roles = WORKFLOW_ROLES.get(path.target)
        denied = bool(roles and role not in roles)
        required = roles
    if denied:
        need = "/".join(required) if required else "相应"
        exec_ = _emit(state.get("execution", {}), "step_failed", "guardrails",
                      status="forbidden", payload={"intent": intent, "role": role})
        exec_["denied"] = True
        return {"routing": routing, "execution": exec_, "response": {
            "message": f"无权执行该操作（当前角色 {role} 权限不足；该功能需要 {need} 角色）。",
            "status": "forbidden", "needs_user_input": False}}
    return {"routing": routing}


def resolver(state: AgentRuntimeState) -> dict:
    """引用解析 + 最小澄清：missing_slots 先从任务状态（L2）解析，才问用户。

    F4.0：只从 task.slots 补全「当前缺失的槽位」（续问场景，如「未来 7 天呢」沿
    用 sku_code），不再整包合并旧 slots —— 否则上一轮实体（SKU/订单号）会泄漏进
    无关新话题（如「今天天气怎么样」被误判成 SKU 查询）。
    """
    routing = dict(state.get("routing", {}))
    task = state.get("task")
    slots = dict(task.get("slots", {})) if task else {}
    missing = list(routing.get("missing_slots", []))
    resolved = {}
    for m in list(missing):
        if m in slots:
            resolved[m] = slots[m]
            missing.remove(m)
    routing["entities"] = {**routing.get("entities", {}), **resolved}
    routing["missing_slots"] = missing
    return {"routing": routing, "__next": "clarify" if missing else "dispatcher"}


def clarify(state: AgentRuntimeState) -> dict:
    routing = state.get("routing", {})
    task = _new_task(routing)
    task["status"] = WAITING_USER_INPUT
    task["pending_type"] = "slot_fill"
    task["missing_slots"] = list(routing.get("missing_slots", []))   # 必须带入，供补槽
    field = task["missing_slots"][0] if task["missing_slots"] else ""
    # F3：per-field 示例（订单号示例不再混入 SKU）；慢销提示 SKU 或类目
    examples = {
        "order_no": "订单号，如 ORD_01_000437",
        "sku_code": "SKU 编码，如 SKU_01_STOCKOUT_01",
    }
    hint = examples.get(field, field)
    if field == "sku_code" and routing.get("intent") == "slow_moving":
        hint = "SKU 编码（如 SKU_01_STOCKOUT_01）或类目（如 美妆）"
    exec_ = _emit(state.get("execution", {}), "human_requested", "clarify",
                  payload={"missing_slots": task["missing_slots"]})
    return {
        "task": task, "execution": exec_,
        "response": {"message": f"请提供{hint}。",
                     "status": WAITING_USER_INPUT, "needs_user_input": True},
    }


def dispatcher(state: AgentRuntimeState) -> dict:
    intent = state.get("routing", {}).get("intent", "out_of_scope")
    path = resolve(intent)
    kind = path.kind if path else "none"
    return {"execution": {**state.get("execution", {}), "kind": kind, "intent": intent}}


def tool_node(state: AgentRuntimeState) -> dict:
    session = state["session"]
    ctx = ops_ctx(session["store_id"])
    intent = state["execution"]["intent"]
    entities = state["routing"]["entities"]
    path = resolve(intent)
    tool_id = path.target if (path and path.kind == "direct") else ""
    if intent == "knowledge_query":
        params = {"query": state.get("message", "")}   # 知识检索用整句提问，非实体槽
    else:
        params = entities
    exec_ = _emit(state["execution"], "tool_called", "tool",
                  payload={"tool": tool_id, "arguments": params})
    res = run_tool(tool_id, ctx, **params)
    data = res.data if res.ok else {"error_code": res.error_code, "error_detail": res.error_detail}
    exec_ = _emit(exec_, "tool_completed", "tool", status="success" if res.ok else "error",
                  payload={"result": data})
    exec_["tool_result"] = data
    return {"execution": exec_}


def workflow_node(state: AgentRuntimeState) -> dict:
    session = state["session"]
    routing = state["routing"]
    intent = routing["intent"]
    exec_ = _emit(state["execution"], "tool_called", "workflow",
                  payload={"workflow": intent, "arguments": routing.get("entities", {})})
    wf_in = WorkflowInput(
        task_id=str(session.get("session_id", "")),
        user_id=session.get("user_id", 0),
        store_id=session["store_id"],
        intent=intent,
        slots=routing.get("entities", {}),
    )
    wf = run_workflow(wf_in)
    wr = {"formal_result": wf.formal_result, "route_status": wf.route_status,
          "status": wf.status, "confirmation_required": wf.confirmation_required}
    exec_ = _emit(exec_, "tool_completed", "workflow",
                  status="success" if wf.status == "completed" else wf.status,
                  payload={"route_status": wf.route_status})
    exec_["workflow_result"] = wr
    return {"execution": exec_}


# ---- F1 分层兜底（out_of_scope → 能力咨询 / 知识检索 / 选项引导 / 自然拒绝）----

_CAPABILITY_KEYWORDS = ("你是谁", "你能做什么", "能做什么", "能帮我做什么", "会什么",
                        "介绍", "帮忙看看你", "你的功能", "能干嘛")


def _chat_fallback(state: AgentRuntimeState, routing: dict, session: dict) -> tuple[str, str]:
    """out_of_scope 分层兜底：返回 (message, status)。

    Tier ① 能力咨询 → persona 能力清单（live 由 LLM 润色）
    Tier ② 知识型 → T-K-01 RAG 检索，命中则基于证据作答
    Tier ③ 有 sku/order 实体 → 选项式引导（列该实体可查的能力）
    Tier ④ 其余 → 自然拒绝 + 能力引导（保留「能力范围」措辞）
    """
    message = state.get("message", "")
    entities = routing.get("entities", {})
    role = session.get("role", "operations")
    store_id = session.get("store_id", 1)
    conv = list(state.get("conversation", []))[-6:]

    def _blocks(rag=None, tool_result=None):
        return assemble(ContextInput(
            role=role, store_id=store_id, message=message, conversation=conv,
            rag=rag, tool_result=tool_result))

    # ① 能力咨询
    if any(k in message for k in _CAPABILITY_KEYWORDS):
        fallback = capability_intro(role)
        return llm.draft(_blocks(), fallback), COMPLETED

    # ② 有实体无意图 → 选项式引导（用户指向具体对象，先给该对象可查的能力）
    entity = entities.get("sku_code") or entities.get("order_no")
    if entity:
        caps = ("库存/缺货风险/补货建议/商品健康度/销售异常/慢销" if entities.get("sku_code")
                else "订单详情/物流/退货资格")
        fallback = (f"关于 {entity}，我可以帮你查：{caps}。"
                    "请告诉我你想看哪一项。")
        return fallback, COMPLETED

    # ③ 知识型兜底（RAG）：T-K-01 检索，命中则基于证据作答
    try:
        from ..context import ops_ctx
        res = run_tool("T-K-01", ops_ctx(store_id), query=message)
        results = (res.data or {}).get("results", []) if res.ok else []
        if results:
            rag = [f"{r.get('title')}（{r.get('section','')}）：{r.get('content','')}" for r in results[:2]]
            fallback = "检索到相关业务知识：\n" + "\n".join(
                f"· {r.get('title')}（{r.get('section','')}）" for r in results[:3])
            return llm.draft(_blocks(rag=rag), fallback), COMPLETED
    except Exception:
        pass

    # ④ 自然拒绝 + 能力引导
    intro = capability_intro(role)
    fallback = f"这超出了我的能力范围。{intro}"
    return llm.draft(_blocks(), fallback), TERMINATED


def _role_label(role: str) -> str:
    return {"operations": "运营", "customer_service": "客服"}.get(role, role)


def _role_announcement(role: str, intent: str) -> str:
    """方向 A：首次角色说明（仅判定当轮附加一次）。"""
    intent_zh = {"stockout_risk": "缺货风险", "restock_recommendation": "补货建议",
                 "inventory_query": "库存查询", "sales_anomaly": "销售异常",
                 "slow_moving": "慢销识别", "product_health": "商品健康度",
                 "return_eligibility": "退货资格", "shipping_status": "物流查询",
                 "order_query": "订单查询", "fulfillment_delay": "物流异常",
                 "knowledge_query": "知识问答"}.get(intent, "业务")
    return (f"自动检测到你提问了「{intent_zh}」相关问题，已为你判定为{_role_label(role)}人员，"
            f"主要提供{_role_label(role)}场景的查询与决策辅助。如需切换角色，请重开窗口或手动切换。\n\n")


def finalize(state: AgentRuntimeState) -> dict:
    if state.get("response"):  # guardrails 权限拒绝已设响应 → 直接收尾
        task = dict(state.get("task", {})) or _new_task(state.get("routing", {}))
        task["status"] = TERMINATED if state["response"].get("status") == "forbidden" else task.get("status", RUNNING)
        task["current_step"] = "guardrails"
        exec_ = _emit(state.get("execution", {}), "final_response", "finalize",
                      payload={"status": state["response"].get("status")})
        return {"task": task, "execution": exec_, "response": state["response"]}

    execution = state.get("execution", {})
    phase = execution.get("phase", "new")
    routing = state.get("routing", {})
    kind = execution.get("kind")

    if phase == "new":
        task = _new_task(routing)
    else:  # continue（slot_fill 补全后）
        task = dict(state.get("task", {}))
        task["slots"] = {**task.get("slots", {}), **routing.get("entities", {})}

    if kind == "direct":
        result = execution.get("tool_result", {})
        message = _draft_direct(state, routing.get("intent"), result)
        status = COMPLETED if "error_code" not in result else "error"
    elif kind == "workflow":
        wr = execution.get("workflow_result", {})
        task.update(intent=routing.get("intent"),
                    slots={**task.get("slots", {}), **routing.get("entities", {})})
        if wr.get("confirmation_required"):
            task.update(status=WAITING_USER_INPUT, pending_type="confirm", current_step="confirm")
            exec_ = _emit(state["execution"], "human_requested", "confirm",
                          payload={"route_status": wr.get("route_status")})
            return {"task": task, "execution": exec_, "response": {
                "message": _draft_workflow(state, wr) + "\n\n是否确认执行？",
                "status": WAITING_USER_INPUT, "needs_user_input": True,
                "approval_required": True, "result": wr.get("formal_result", {})}}
        message = _draft_workflow(state, wr)
        status = COMPLETED if wr.get("status") == "completed" else TERMINATED
    else:  # out_of_scope → F1 分层兜底
        message, status = _chat_fallback(state, routing, state.get("session", {}))

    task["current_step"] = "finalize"
    task["status"] = status if status in (COMPLETED, TERMINATED) else task.get("status", RUNNING)
    exec_ = _emit(state["execution"], "final_response", "finalize", payload={"status": status})
    return {"task": task, "execution": exec_, "response": {
        "message": message, "status": status, "needs_user_input": False,
        "result": execution.get("tool_result") or execution.get("workflow_result", {}).get("formal_result", {}),
    }}


def _draft_context(state: AgentRuntimeState, tool_result: dict | None = None) -> list[tuple[str, str]]:
    """组装 LLM 解释上下文（F2）：persona + 历史 + 工具结果 + 当前消息。"""
    session = state.get("session", {})
    conv = list(state.get("conversation", []))[-6:]
    return assemble(ContextInput(
        role=session.get("role", "operations"), store_id=session.get("store_id", 1),
        message=state.get("message", ""), conversation=conv, tool_result=tool_result))


def _draft_direct(state: AgentRuntimeState, intent: str, result: dict) -> str:
    fallback = _draft_direct_tpl(intent, result)
    if "error_code" in result or intent == "knowledge_query" or llm.mode() != "live":
        return fallback   # 错误/检索列表/离线 → 保持确定性模板（引用事实）
    return llm.draft(_draft_context(state, tool_result=result), fallback)


def _draft_workflow(state: AgentRuntimeState, wr: dict) -> str:
    fallback = _draft_workflow_tpl(wr)
    if (wr.get("status") != "completed" or wr.get("route_status") in ("FORBIDDEN", "UNDETERMINED")
            or llm.mode() != "live"):
        return fallback   # 失败/隔离/未决/离线 → 模板（明确语义，LLM 不润色）
    return llm.draft(_draft_context(state, tool_result=wr.get("formal_result", {})), fallback)


def _draft_direct_tpl(intent: str, result: dict) -> str:
    if "error_code" in result:
        return f"查询失败：{result.get('error_detail', result.get('error_code'))}。"
    if intent == "inventory_query":
        return (f"SKU {result.get('sku_code')} 当前可用库存 {result.get('available_qty')} 件"
                f"（安全库存 {result.get('safety_stock')}）。")
    if intent == "knowledge_query":
        results = result.get("results", [])
        if not results:
            return "未检索到相关业务知识。"
        lines = [f"· {r['title']}（{r.get('section','')}）" for r in results[:3]]
        return "检索到相关业务知识：\n" + "\n".join(lines)
    return f"查询结果：{result}"


def _draft_workflow_tpl(wr: dict) -> str:
    route = wr.get("route_status")
    fr = wr.get("formal_result", {})
    if route == "HAS_RECO":
        return (f"建议补货 {fr.get('recommended_quantity')} 件"
                f"（日均 {fr.get('avg_daily_sales_est')} 件，约 {fr.get('days_until_stockout')} 天后缺货）。")
    if route == "NO_RECO":
        return "当前库存充足，无需补货。"
    if route in ("HAS_RISK", "NO_RISK"):
        return (f"缺货风险评估：{fr.get('risk_level')}（日均 {fr.get('avg_daily_sales_est')} 件，"
                f"可用 {fr.get('available_qty')} 件，约 {fr.get('days_until_stockout')} 天后缺货）。")
    if route == "UNDETERMINED":
        return f"暂无法判定：{fr.get('error_detail')}。"
    if route == "FORBIDDEN":
        detail = fr.get("error_detail", "跨店数据被隔离")
        return f"无权访问：{detail}" if detail.endswith("。") else f"无权访问：{detail}。"
    if route == "already_exists":
        return "该订单已有退货申请，无需重复提交。"
    if route in ("eligible", "ineligible", "undetermined"):
        reason = fr.get("reason_code", route)
        return (f"退货资格判定：{route}（{reason}）。{fr.get('explanation', '')}"
                + ("\n\n是否提交退货申请？" if route == "eligible" else ""))
    return f"执行结果：{route}"


def _default_checkpointer():
    """PostgresSaver（Spec-2 §2，持久化跨重启）；不可用则回退 InMemorySaver。"""
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import connect as pg_connect

        from ..config import DB_DSN
        conn = pg_connect(DB_DSN, autocommit=True, connect_timeout=5)
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    except Exception:
        return InMemorySaver()


def build_runtime_graph(checkpointer=None):
    """构建 Runtime 图；checkpointer 传入则启用持久化（会话/续答）。"""
    g = StateGraph(AgentRuntimeState)
    g.add_node("pending_check", pending_check)
    g.add_node("handle_pending", handle_pending)
    g.add_node("router", router)
    g.add_node("guardrails", guardrails)
    g.add_node("resolver", resolver)
    g.add_node("clarify", clarify)
    g.add_node("dispatcher", dispatcher)
    g.add_node("tool_node", tool_node)
    g.add_node("workflow_node", workflow_node)
    g.add_node("finalize", finalize)

    g.add_edge(START, "pending_check")
    g.add_conditional_edges("pending_check",
                            lambda s: s.get("__next", "router"),
                            {"router": "router", "handle_pending": "handle_pending"})
    g.add_conditional_edges("handle_pending",
                            lambda s: s.get("__next", "router"),
                            {"router": "router", "dispatcher": "dispatcher",
                             "clarify": "clarify", "end": END})
    g.add_edge("router", "guardrails")
    g.add_conditional_edges("guardrails",
                            lambda s: "finalize" if s.get("response") else "resolver",
                            {"resolver": "resolver", "finalize": "finalize"})
    g.add_conditional_edges("resolver",
                            lambda s: s.get("__next", "dispatcher"),
                            {"dispatcher": "dispatcher", "clarify": "clarify"})
    g.add_edge("clarify", END)
    g.add_conditional_edges("dispatcher",
                            lambda s: s.get("execution", {}).get("kind", "none"),
                            {"direct": "tool_node", "workflow": "workflow_node", "none": "finalize"})
    g.add_edge("tool_node", "finalize")
    g.add_edge("workflow_node", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer or _default_checkpointer())


def run_agent(graph, thread_id: str, session: dict, message: str) -> dict:
    """对外入口：一轮执行。首轮传完整 session；后续仅传 message（其余状态走 checkpointer 持久化）。

    返回 {'response': AgentResponse 字段, 'state': 最终 state}。
    """
    trace = Trace()
    input_state: AgentRuntimeState = {
        "session": session,
        "message": message,
        "execution": {"run_id": trace.run_id, "trace": trace.to_list()},
        "response": {},   # 覆盖上轮持久化的 response（guardrails 条件边依赖）
    }
    config = {"configurable": {"thread_id": thread_id}}
    # 续轮：读取已持久化的 task/conversation/session（不覆盖）
    try:
        persisted = graph.get_state(config).values
    except Exception:
        persisted = {}
    if persisted.get("task"):
        input_state["task"] = persisted["task"]
    if persisted.get("conversation"):
        input_state["conversation"] = persisted["conversation"]
    if persisted.get("session"):
        # 方向 A：已判定角色/门店的会话，用持久化值（前端零预选/未回传时沿用）
        saved = dict(persisted["session"])
        if not session.get("role") and saved.get("role"):
            session = {**session, "role": saved["role"], "store_id": saved.get("store_id")}
    input_state["session"] = session

    out = graph.invoke(input_state, config)
    resp = out.get("response", {"message": "", "status": "error"})
    # 方向 A：判定后的 session（role/store 可能被 router 首次对话更新）
    resolved_session = out.get("session") or session
    _persist(out, resolved_session, thread_id, message)
    # 追加会话历史（user + assistant）
    conv = list(out.get("conversation", []))
    conv += [{"role": "user", "content": message}]
    if resp.get("message"):
        conv += [{"role": "assistant", "content": resp["message"]}]
    graph.update_state(config, {"conversation": conv, "session": resolved_session})
    # 方向 A：首次判定角色 → 附加一次角色说明（统一在出口注入，覆盖所有 finalize 分支）
    if out.get("execution", {}).get("role_just_determined"):
        announce = _role_announcement(resolved_session.get("role", "operations"),
                                      out.get("routing", {}).get("intent", ""))
        if resp.get("message"):
            resp["message"] = announce + resp["message"]
    resp["role"] = resolved_session.get("role")          # 供前端回显判定后的角色
    resp["store_id"] = resolved_session.get("store_id")  # 供前端回显判定后的门店
    return {"response": resp, "state": out}


def _persist(out: dict, session: dict, thread_id: str, message: str) -> None:
    """会话创建 + run_log 写入 + 记忆提取（Spec-2 / §14.3）；失败降级不阻断。"""
    resp = out.get("response", {})
    exec_ = out.get("execution", {})
    sid = session.get("session_id", "")
    uid = session.get("user_id", 0)
    role = session.get("role", "operations")
    store = session.get("store_id", 1)
    try:
        from ..runtime.store import create_session, upsert_memory, write_run_log
        create_session(sid, thread_id, uid, role, store)
        workflow = exec_.get("intent") if exec_.get("kind") == "workflow" else None
        status = resp.get("status", "error")
        write_run_log(
            exec_.get("run_id", ""), sid, uid, role, store,
            intent=out.get("routing", {}).get("intent"),
            workflow=workflow,
            route_status=(exec_.get("workflow_result") or {}).get("route_status"),
            status=status,
            tool_calls=exec_.get("trace", []),
            error=status if status in ("error", "forbidden", "failed") else None,
        )
        if status == "completed":
            _extract_memory(session, message)
    except Exception:
        pass  # 持久化失败不阻断对话（降级）


def _extract_memory(session: dict, message: str) -> None:
    """记忆提取（V1 规则式，仅 completed 后；§14.3 只记偏好，不记业务事实）。"""
    import re

    from ..runtime.store import upsert_memory
    uid = session.get("user_id", 0)
    src = session.get("session_id")
    m = re.search(r"默认.*?(\d+)\s*天", message)
    if m:
        upsert_memory(uid, "preference", "default_horizon", int(m.group(1)),
                      confidence=0.9, source=src)
    if "表格" in message and ("偏好" in message or "喜欢" in message):
        upsert_memory(uid, "preference", "response_format", "table",
                      confidence=0.7, source=src)

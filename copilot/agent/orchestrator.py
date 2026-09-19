"""Runtime Orchestrator（Spec-1 §3）：单 Agent Runtime Graph。

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
        accepted = any(k in message for k in ("确认", "同意", "可以", "好的"))
        task["status"] = COMPLETED if accepted else TERMINATED
        task["current_step"] = "confirm"
        msg = "已确认，补货建议生效。" if accepted else "已取消该操作。"
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
    exec_ = _emit(state.get("execution", {}), "intent_detected", "router",
                  payload={"intent": result.intent, "entities": result.entities})
    exec_["phase"] = "new"
    exec_["pending"] = False
    return {"routing": result.model_dump(), "execution": exec_}


# workflow → 允许角色（阶段 4 随各 workflow 扩展；Spec-1 §4.2）
WORKFLOW_ROLES = {"OP-05": ("operations",), "OP-04": ("operations",)}


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
    # 权限检查（Spec-1 §4.2 / §10.3）：direct 工具或 workflow 的允许角色
    denied = False
    if path.kind == "direct" and path.target:
        from ..tool import TOOLS
        if not TOOLS:
            from .. import tools  # noqa: F401
        cls = TOOLS.get(path.target)
        denied = bool(cls and not cls.allows(role))
    elif path.kind == "workflow" and path.target:
        roles = WORKFLOW_ROLES.get(path.target)
        denied = bool(roles and role not in roles)
    if denied:
        exec_ = _emit(state.get("execution", {}), "step_failed", "guardrails",
                      status="forbidden", payload={"intent": intent, "role": role})
        exec_["denied"] = True
        return {"routing": routing, "execution": exec_, "response": {
            "message": f"无权执行该操作（{role} 角色权限不足）。",
            "status": "forbidden", "needs_user_input": False}}
    return {"routing": routing}


def resolver(state: AgentRuntimeState) -> dict:
    """引用解析 + 最小澄清：missing_slots 先从任务状态（L2）解析，才问用户。"""
    routing = dict(state.get("routing", {}))
    task = state.get("task")
    slots = dict(task.get("slots", {})) if task else {}
    missing = list(routing.get("missing_slots", []))
    for m in list(missing):
        if m in slots:
            missing.remove(m)
    routing["entities"] = {**slots, **routing.get("entities", {})}
    routing["missing_slots"] = missing
    return {"routing": routing, "__next": "clarify" if missing else "dispatcher"}


def clarify(state: AgentRuntimeState) -> dict:
    routing = state.get("routing", {})
    task = _new_task(routing)
    task["status"] = WAITING_USER_INPUT
    task["pending_type"] = "slot_fill"
    task["missing_slots"] = list(routing.get("missing_slots", []))   # 必须带入，供补槽
    field = task["missing_slots"][0] if task["missing_slots"] else ""
    label = {"order_no": "订单号", "sku_code": "SKU 编码"}.get(field, field)
    exec_ = _emit(state.get("execution", {}), "human_requested", "clarify",
                  payload={"missing_slots": task["missing_slots"]})
    return {
        "task": task, "execution": exec_,
        "response": {"message": f"请提供{label}（形如 SKU_01_STOCKOUT_01 / ORD_01_000437）。",
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
    tool_id = _TOOL_BY_INTENT.get(intent, "")
    exec_ = _emit(state["execution"], "tool_called", "tool",
                  payload={"tool": tool_id, "arguments": entities})
    res = run_tool(tool_id, ctx, **entities)
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
        message = _draft_direct(routing.get("intent"), result)
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
                "message": _draft_workflow(wr) + "\n\n是否确认执行？",
                "status": WAITING_USER_INPUT, "needs_user_input": True,
                "approval_required": True, "result": wr.get("formal_result", {})}}
        message = _draft_workflow(wr)
        status = COMPLETED if wr.get("status") == "completed" else TERMINATED
    else:  # out_of_scope
        message = "该问题不在我的能力范围（可咨询库存/补货/缺货/订单/物流/退货等）。"
        status = TERMINATED

    task["current_step"] = "finalize"
    task["status"] = status if status in (COMPLETED, TERMINATED) else task.get("status", RUNNING)
    exec_ = _emit(state["execution"], "final_response", "finalize", payload={"status": status})
    return {"task": task, "execution": exec_, "response": {
        "message": message, "status": status, "needs_user_input": False,
        "result": execution.get("tool_result") or execution.get("workflow_result", {}).get("formal_result", {}),
    }}


def _draft_direct(intent: str, result: dict) -> str:
    if "error_code" in result:
        return f"查询失败：{result.get('error_detail', result.get('error_code'))}。"
    if intent == "inventory_query":
        return (f"SKU {result.get('sku_code')} 当前可用库存 {result.get('available_qty')} 件"
                f"（安全库存 {result.get('safety_stock')}）。")
    return f"查询结果：{result}"


def _draft_workflow(wr: dict) -> str:
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
    return f"执行结果：{route}"


_TOOL_BY_INTENT = {"inventory_query": "T-Q-03"}


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
    # 续轮：读取已持久化的 task/conversation，不覆盖
    try:
        persisted = graph.get_state(config).values
    except Exception:
        persisted = {}
    if persisted.get("task"):
        input_state["task"] = persisted["task"]
    if persisted.get("conversation"):
        input_state["conversation"] = persisted["conversation"]

    out = graph.invoke(input_state, config)
    resp = out.get("response", {"message": "", "status": "error"})
    _persist(out, session, thread_id, message)
    # 追加会话历史（user + assistant）
    conv = list(out.get("conversation", []))
    conv += [{"role": "user", "content": message}]
    if resp.get("message"):
        conv += [{"role": "assistant", "content": resp["message"]}]
    graph.update_state(config, {"conversation": conv})
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

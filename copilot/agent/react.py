"""Agent Runtime V2：ReAct 图（Phase 2，并行新模块；legacy orchestrator 仍默认）。

设计（对齐 V1.5.2 W2.1~2.9）：
- **自定义 StateGraph**（模型节点/工具节点/路由/收尾）：create_react_agent 不便自定义
  working_context / execution_context / capability_pending 的更新，故自建（结构与 ReAct 一致）
- **ctx 经 contextvar 注入**：session 来自每轮 invoke 输入；不闭包进按 mode 缓存的 agent
  （D9/D12 意图）。注：context_schema 的运行时传递走 pregel 内部 __pregel_runtime，
  外部注入不可靠，故用 contextvar 实现同一"调用时解析、不缓存会话"意图
- **model 注入口**（fake/live，D6）；**循环控制** max_iterations + max_tool_calls（W2.1）
- **request_capability** meta-tool → execution.capability_pending（W2.9，D10/D12）
- **working state 覆盖规则**（W2.8）：新实体（ORD_/SKU_）出现即覆盖；模式切换不重置
- **run_agent 兼容入口**（W2.5）：response 信封不变（message/status/needs_user_input/
  approval_required/result）
"""
from __future__ import annotations

import contextvars
import json
import re
import time
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph, add_messages

from .. import llm
from ..context import approval_text_decision, mode_to_role, session_ctx
from .persona import get_persona
from .toolkit import build_toolkit, catalog_names

# ---- ctx：contextvar 注入（Phase 1 ctx_provider 的 Phase 2 实现）----

_CURRENT_SESSION: contextvars.ContextVar[dict] = contextvars.ContextVar("react_session", default={})


def _ctx_provider():
    return session_ctx(_CURRENT_SESSION.get())


# ---- State（W2.8）----

class AgentRuntimeState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    session: dict          # {session_id, user_id, workspace_mode, store_id}
    working: dict          # {current_order_no, current_sku, current_domain}
    execution: dict        # {tool_calls, iterations, capability_pending}
    response: dict         # response 信封


# ---- working state 覆盖规则（W2.8）----

_ORDER_RE = re.compile(r"ORD_\d+_\d+")
_SKU_RE = re.compile(r"SKU_\d+_[A-Z0-9_]+")


def _extract_entities(text: str) -> dict:
    """从用户消息抽取实体 → working state 覆盖键（新实体出现即覆盖旧值）。"""
    out = {}
    m = _ORDER_RE.search(text)
    if m:
        out["current_order_no"] = m.group(0)
    m = _SKU_RE.search(text)
    if m:
        out["current_sku"] = m.group(0)
    return out


# ---- ReAct system prompt（W2.2）----

def _system_prompt(session: dict, working: dict, memory: str = "") -> list[SystemMessage]:
    mode = session.get("workspace_mode") or "UNSET"
    role = (mode or "UNSET").lower()          # F3：UNSET → 中立 persona（不自称运营/客服）
    lines = [
        get_persona(role),
        f"当前工作模式（Workspace Mode）：{mode}；store_id={session.get('store_id', 1)}。",
        "数据范围（ISO）：读取可跨店——引用其他门店标识（ORD_02_*/SKU_02_*）时，工具返回会标注 "
        "source_store，属正式数据可直接用于结论；回复涉及跨店数据时须向用户说明来源门店；"
        "**写操作仅限当前会话门店**，跨店写会被拒绝。",
        "R4 安全红线：正式结论（补货量/风险等级/资格三态/异常判定/库存）一律以工具返回值为准，"
        "禁止自行推算或编造数值。"
        "若任务需要当前目录之外的权威工具（如缺货风险/销售异常等运营分析），**不得用其他工具"
        "（如库存）的数据自行推算结论**——必须调用 request_capability(domain) 请求切换，"
        "或明确告知用户需要对应能力模式；绝不可临场判断权威结论。",
        "能力边界：只能调用当前模式目录内的工具（当前可用：" + "、".join(catalog_names(mode))
        + "）。若任务需要目录之外的专属工具，调用 request_capability(domain) 请求切换——"
        "不要编造或猜测目录外工具。示例：当前无运营工具时用户问『SKU_01_STOCKOUT_01 缺货风险"
        "怎么样』，应调用 request_capability(domain='operations')，而不是用库存数据自行判断，"
        "也不是仅文字说明需要运营模式。"
        "F4：当任务需要当前模式目录之外的能力时，**必须立刻调用 request_capability(domain) "
        "发起切换申请**，不要用文字说明代替，也不要等用户追问后再申请。"
        "若用户已明确同意切换（如回复『好的/切换』），也应调用 request_capability(domain) 正式发起申请。",
        "缺槽规则：用户未提供 SKU 编码/订单号时，必须向用户询问，禁止编造标识符。",
        "知识问答（W5.2）：基于检索命中的文档内容作答，并引用文档标题作为来源；"
        "不要编造未检索到的规则。",
        "任务上下文：" + json.dumps(working, ensure_ascii=False)
        + "（仅记录实体/任务引用；业务事实永远以工具返回为准，勿用此缓存替代查询）。",
        "流程边界（查询 vs 发起）：只问『能否/有没有/要不要/是不是』→ 用查询/判定工具直接作答即可；"
        "用户要『申请/发起/执行』退货或补货（申请退货、帮我退货、发起退货、生成补货建议并执行、"
        "确认补货等）→ **必须调用对应 workflow 工具**（退货走 cs08_return_workflow，补货走 "
        "op05_restock_workflow），不得只用查询工具答复了事。",
        "流程：思考需要的工具→调用→基于工具结果继续→信息足够时给出最终中文回答，引用工具数值。",
    ]
    if memory:
        lines.append(memory)   # 用户长期偏好（W5.1，每轮注入）
    return [SystemMessage(content="\n".join(lines))]


_MEMORY_LABELS = {
    "default_horizon": "默认分析时间窗（天）",
    "response_format": "偏好输出格式",
}

# I6：Workspace Mode 用户可见中文标签（capability 提示等气泡文案）
_MODE_LABEL = {"UNSET": "未锁定", "CUSTOMER_SERVICE": "客服", "OPERATIONS": "运营"}


def _memory_block(session: dict) -> str:
    """每轮读取用户长期偏好（W5.1 读回；补『只写不读』断点）。"""
    try:
        from ..runtime.store import get_memory
        mems = get_memory(int(session.get("user_id") or 1))
    except Exception:
        return ""
    if not mems:
        return ""
    parts = []
    for m in mems:
        key = m["memory_key"]
        label = _MEMORY_LABELS.get(key, key)
        val = m["memory_value"]
        if key == "default_horizon":
            parts.append(
                f"- 默认分析时间窗 {val} 天：调用缺货风险(forecast_days)/补货(horizon_days)等"
                f"分析工具时，若用户未明确指定时间窗，请使用 {val} 天")
        else:
            parts.append(f"- {label}（{key}）: {val}")
    return "用户长期偏好：\n" + "\n".join(parts)


def _default_horizon(session: dict) -> int | None:
    """W5.1：读 default_horizon 偏好，供分析工具参数确定性默认（不依赖 LLM 自觉）。"""
    try:
        from ..runtime.store import get_memory
        mems = get_memory(int(session.get("user_id") or 1))
    except Exception:
        return None
    for m in mems:
        if m["memory_key"] == "default_horizon":
            try:
                return int(m["memory_value"])
            except (TypeError, ValueError):
                return None
    return None


def _extract_memory(session: dict, message: str) -> None:
    """记忆写入（W5.1 最小扩展，同 legacy 规则）：用户说『默认 N 天』→ default_horizon。"""
    import re

    from ..runtime.store import upsert_memory
    m = re.search(r"默认.*?(\d+)\s*天", message)
    if m:
        upsert_memory(int(session.get("user_id") or 1), "preference", "default_horizon",
                      int(m.group(1)), confidence=0.9, source=session.get("session_id"))


def _sanitize_for_model(messages) -> list:
    """剥离发给 LLM 的历史中无对应 ToolMessage 的悬空 tool_calls（防 DeepSeek 400
    'insufficient tool messages following tool_calls'）。

    悬空来源：审批 interrupt（workflow 工具未返回）或 max_iterations/max_tool_calls 兜底命中。
    只作用于发给模型的副本，不改持久化 state。
    """
    answered = {getattr(m, "tool_call_id", None) for m in messages
                if getattr(m, "type", "") == "tool"}
    out = []
    for m in messages:
        tcs = getattr(m, "tool_calls", None)
        if not tcs:
            out.append(m)
            continue
        keep = [tc for tc in tcs if tc.get("id") in answered]
        if len(keep) == len(tcs):
            out.append(m)
            continue
        if not keep and not (getattr(m, "content", "") or "").strip():
            # 全部悬空且无内容：转成说明消息（保留 assistant 轮次，避免破坏交替）
            out.append(AIMessage(content="[上一轮工具调用未完成，已忽略]"))
        else:
            try:
                out.append(m.model_copy(update={"tool_calls": keep}))
            except Exception:
                out.append(m)
    return out


def read_capability_pending(graph, thread_id: str) -> dict | None:
    """读 AgentState.execution_context.capability_pending（供 UI/API 层判断文本确认切换）。"""
    try:
        values = graph.get_state({"configurable": {"thread_id": thread_id}}).values
        return (values.get("execution") or {}).get("capability_pending")
    except Exception:
        return None


# 审批 workflow 工具（用于识别挂起的审批 interrupt）
_APPROVAL_WORKFLOW_TOOLS = {"cs08_return_workflow", "op05_restock_workflow"}


def resolve_approval_text(graph, thread_id: str, message: str) -> dict | None:
    """审批文本确认（P1）：末尾悬空 workflow tool_call + 确认/拒绝 → resume 决策。

    返回 {"decision": "approved"|"rejected"} 或 None。用户打字而非点按钮时的路径。
    文本判定复用 context.approval_text_decision（H4：疑问守卫 + 拒绝词优先）。
    """
    if not (message or "").strip():
        return None
    try:
        values = graph.get_state({"configurable": {"thread_id": thread_id}}).values
        msgs = values.get("messages") or []
        last = msgs[-1] if msgs else None
        if getattr(last, "type", "") == "ai" and getattr(last, "tool_calls", None):
            names = {tc.get("name") for tc in last.tool_calls}
            if names & _APPROVAL_WORKFLOW_TOOLS:
                d = approval_text_decision(message)
                if d:
                    return {"decision": d}
    except Exception:
        pass
    return None


def resolve_text_action(graph, thread_id: str, session: dict, message: str) -> tuple[dict, dict | None, bool]:
    """文本动作解析（P1）：用户打字而非点按钮。

    能力切换：capability_pending + 确认词 → (切到新 mode 的 session, None, capability_replay=True)
    审批：末尾悬空 workflow tool_call + 确认/拒绝 → (session, resume, False)
    其余 → (session, None, False)（reject/无关消息：pending 由 run_agent_react 新轮清掉）
    """
    try:
        pending = read_capability_pending(graph, thread_id)
        if pending:
            from ..context import capability_text_decision, normalize_mode
            if capability_text_decision(message) == "confirm":
                return {**session,
                        "workspace_mode": normalize_mode(pending.get("domain"))}, None, True
            return session, None, False
        d = resolve_approval_text(graph, thread_id, message)
        if d:
            return session, d, False
        # F4：无 pending 时的显式域切换兜底——用户直接说"切换到运营/客服模式"，
        # 无需依赖模型先调 request_capability。无显式域（如"好的，切换"）则返回 None。
        from ..context import capability_domain_switch
        domain = capability_domain_switch(message)
        if domain:
            return {**session, "workspace_mode": domain}, None, True
    except Exception:
        pass
    return session, None, False


def _persist_session(session: dict, thread_id: str, status: str, message: str,
                     tool_names: list[str] | None = None) -> None:
    """ReAct 会话/日志持久化（W6 决策 1）：写 runtime.session（侧栏/重启）+ run_log。

    降级不阻断：持久化失败不干扰对话。workspace_mode 直接写 role 列（侧栏徽章映射）。
    """
    try:
        from ..runtime.store import create_session, write_run_log
        sid = session.get("session_id", "")
        uid = int(session.get("user_id") or 1)
        mode = session.get("workspace_mode") or "UNSET"
        store = int(session.get("store_id") or 1)
        # P2：session.role 存大写 workspace_mode（侧栏徽章/会话重开按模式回读）；
        # run_log.role 保持小写（legacy 约定，审查发现 4）
        create_session(sid, thread_id, uid, mode, store, title=message[:20] or None)
        write_run_log(
            f"react-{int(time.time() * 1000)}-{thread_id[:8]}", sid, uid,
            mode_to_role(mode), store,
            intent=(tool_names[-1] if tool_names else None), workflow=None,
            route_status=status, tool_calls=tool_names, status=status)
    except Exception:
        pass


def _last_user_content(state) -> str:
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage):
            return m.content
    return ""


def _round_tool_names(out, prev_msgs: list) -> list[str]:
    """本轮实际调用的工具名（F5 观测）：对比 invoke 前后的消息，从新增消息里
    提取 AIMessage.tool_calls 的工具名（按出现序去重）。供 run_log 记录。"""
    msgs = out.get("messages") or []
    prev_n = len(prev_msgs)
    new_msgs = msgs[prev_n:] if len(msgs) >= prev_n else msgs
    names = []
    for m in new_msgs:
        for tc in (getattr(m, "tool_calls", None) or []):
            name = tc.get("name")
            if name and name not in names:
                names.append(name)
    return names


# ---- 图构建（并行新模块，legacy 不动）----

def build_react_graph(model=None, mode: str = "UNSET", checkpointer=None,
                      max_iterations: int = 6, max_tool_calls: int = 12,
                      ctx_provider=None):
    """构建 ReAct 图（按 Workspace Mode 过滤工具目录）。

    model 注入口（D6）：fake（离线测试）/ None（live，默认 DeepSeek）。
    ctx_provider 默认为 contextvar 后端（每轮从 session 解析）。
    """
    provider = ctx_provider or _ctx_provider
    tools = build_toolkit(mode, provider)
    tool_map = {t.name: t for t in tools}
    bound = (model or llm.get_llm()).bind_tools(tools)

    def model_node(state: AgentRuntimeState) -> dict:
        exec_ = dict(state.get("execution", {}))
        working = dict(state.get("working", {}))
        prompt = _system_prompt(state["session"], working, _memory_block(state["session"]))
        # P0：清洗悬空 tool_calls（防 400）
        resp = bound.invoke(prompt + _sanitize_for_model(state["messages"]))
        # working state 覆盖：从最新用户消息抽取实体
        new_working = dict(working)
        new_working.update(_extract_entities(_last_user_content(state)))
        exec_["iterations"] = exec_.get("iterations", 0) + 1
        return {"messages": [resp], "working": new_working, "execution": exec_}

    def tools_node(state: AgentRuntimeState) -> dict:
        last = state["messages"][-1]
        exec_ = dict(state.get("execution", {}))
        out_msgs = []
        pending = None
        n = 0
        for tc in last.tool_calls:
            name = tc.get("name")
            args = dict(tc.get("args") or {})
            if name == "request_capability":
                from ..context import normalize_mode
                pending = {"domain": normalize_mode(args.get("domain")),
                           "original_message": _last_user_content(state)}
                out_msgs.append(ToolMessage(
                    content=json.dumps({"capability_requested": args.get("domain"),
                                        "status": "pending"}, ensure_ascii=False),
                    tool_call_id=tc["id"]))
                continue
            # W5.1：记忆确定性默认（缺货风险/补货分析的默认时间窗，不依赖 LLM 自觉）
            if name == "analyze_stockout_risk" and not args.get("forecast_days"):
                hz = _default_horizon(state["session"])
                if hz:
                    args["forecast_days"] = hz
            elif name == "op05_restock_workflow" and not args.get("horizon_days"):
                hz = _default_horizon(state["session"])
                if hz:
                    args["horizon_days"] = hz
            t = tool_map.get(name)
            if t is None:
                out_msgs.append(ToolMessage(content="{'error': '工具不在当前目录'}",
                                            tool_call_id=tc["id"]))
            else:
                out_msgs.append(ToolMessage(
                    content=json.dumps(t.invoke(args), ensure_ascii=False, default=str),
                    tool_call_id=tc["id"]))
            n += 1
        exec_["tool_calls"] = exec_.get("tool_calls", 0) + n
        if pending:
            exec_["capability_pending"] = pending
        return {"messages": out_msgs, "execution": exec_}

    def route(state: AgentRuntimeState) -> str:
        exec_ = state.get("execution", {})
        if exec_.get("capability_pending"):
            return "finalize"                    # 能力请求已置 → 结束等用户确认
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            if (exec_.get("iterations", 0) >= max_iterations
                    or exec_.get("tool_calls", 0) >= max_tool_calls):
                return "finalize"                # 保险丝：正常结束是 LLM 出答案，计数是兜底
            return "tools"
        return "finalize"

    def finalize(state: AgentRuntimeState) -> dict:
        exec_ = state.get("execution", {})
        last = state["messages"][-1]
        pending = exec_.get("capability_pending")
        # 结构化 result：取最后一个 ToolMessage（如 workflow 的 confirmed/cancelled/ineligible）
        tool_res: dict = {}
        for m in reversed(state["messages"]):
            if getattr(m, "type", "") == "tool":
                try:
                    tool_res = json.loads(m.content)
                except Exception:
                    tool_res = {}
                break
        if pending:
            label = _MODE_LABEL.get(pending["domain"], pending["domain"])
            resp = {
                "message": f"该请求需要 {label} 能力域。[切换到{label}模式后自动继续]",
                "status": "capability_required",
                "needs_user_input": True,
                "approval_required": False,
                "result": {"capability_pending": pending},
            }
        elif isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            # P0/F2：熔断兜底——最后一条是未执行的工具调用，不是最终答案。
            # 不得把其 content（可能是 "I'll check…" 半截话）当作 completed 返回。
            # 正常路径下带 tool_calls 的 AIMessage 会进 tools 节点，不会到 finalize，
            # 本分支只在熔断截断（单轮循环超限）时命中。
            resp = {
                "message": "本轮处理遇到限制，工具调用未完成，请重试或换一种问法。",
                "status": "incomplete",
                "needs_user_input": True,
                "approval_required": False,
                "result": tool_res,
            }
        elif isinstance(last, AIMessage) and last.content:
            resp = {
                "message": last.content,
                "status": "completed",
                "needs_user_input": False,
                "approval_required": False,
                "result": tool_res,
            }
        else:
            resp = {"message": "处理完成", "status": "completed",
                    "needs_user_input": False, "approval_required": False, "result": tool_res}
        return {"response": resp}

    def _after_tools(state: AgentRuntimeState) -> str:
        # 能力请求已置 → 结束等用户确认；否则回模型节点继续 ReAct
        return "finalize" if state.get("execution", {}).get("capability_pending") else "model"

    g = StateGraph(AgentRuntimeState)
    g.add_node("model", model_node)
    g.add_node("tools", tools_node)
    g.add_node("finalize", finalize)
    g.add_edge(START, "model")
    g.add_conditional_edges("model", route,
                            {"tools": "tools", "finalize": "finalize"})
    g.add_conditional_edges("tools", _after_tools,
                            {"model": "model", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


# ---- 对外入口（W2.5：run_agent 兼容信封）----

def _default_checkpointer():
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


def run_agent_react(graph, thread_id: str, session: dict, message: str,
                    capability_replay: bool = False, resume: dict | None = None) -> dict:
    """ReAct 一轮执行（legacy run_agent 兼容信封）。

    capability_replay（D12）：用户确认切换模式后的重跑——同一 thread、不追加用户消息、
    输入 capability_confirmed 系统旁注、清空 capability_pending（原消息仍在 messages 中）。
    resume（W3.3）：审批确认/拒绝——以 Command(resume=...) 恢复被 interrupt 的 workflow 工具。
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:
        persisted = graph.get_state(config).values
    except Exception:
        persisted = {}
    working = dict(persisted.get("working") or {})
    execution = dict(persisted.get("execution") or {})
    prev_msgs = list(persisted.get("messages") or [])   # F5：本轮消息对比基线
    saved_session = persisted.get("session") or session
    if not session.get("workspace_mode") and saved_session.get("workspace_mode"):
        session = {**session, "workspace_mode": saved_session["workspace_mode"],
                   "store_id": saved_session.get("store_id")}

    # P1：新轮（非 resume/replay）清掉过期 capability_pending——用户未确认即离开，
    # 防 route 误判阻塞后续工具调用（文本确认/拒绝在 web/api 层已先处理）
    if resume is None and not capability_replay:
        execution["capability_pending"] = None

    # P0/F1：熔断计数按"单次用户请求"计——每轮（非 resume）重置 iterations/tool_calls。
    # 否则计数在持久化 execution 里跨轮累计，≥max_iterations 后 route 永远截断到
    # finalize、工具不再执行（"处理完成"/"I'll check…"故障的根因）。
    # resume 是同一轮被 interrupt 打断后的延续，保留其预算不重置。
    if resume is None:
        execution["iterations"] = 0
        execution["tool_calls"] = 0

    token = _CURRENT_SESSION.set(session)
    try:
        if resume is not None:
            from langgraph.types import Command
            out = graph.invoke(Command(resume=resume), config)
        elif capability_replay:
            execution["capability_pending"] = None
            out = graph.invoke({
                "session": session, "working": working, "execution": execution,
                "messages": [SystemMessage(
                    content=f"用户已确认切换到 {session.get('workspace_mode')} 模式，请继续处理上一条请求。")],
            }, config)
        else:
            out = graph.invoke({
                "session": session, "working": working, "execution": execution,
                "messages": [HumanMessage(content=message)],
            }, config)
    finally:
        _CURRENT_SESSION.reset(token)

    # 审批 interrupt（W3.3）：workflow 工具触发 interrupt → 图暂停 → approval_required 响应
    interrupts = out.get("__interrupt__") or []
    if interrupts:
        val = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
        resp = {
            "message": val.get("message", "需要审批确认"),
            "status": "approval_required",
            "needs_user_input": True,
            "approval_required": True,
            "result": val,
        }
        if not capability_replay and resume is None:
            _persist_session(session, thread_id, "approval_required", message,
                             tool_names=_round_tool_names(out, prev_msgs))
        resp["role"] = session.get("workspace_mode") or "operations"
        resp["store_id"] = session.get("store_id", 1)
        return {"response": resp, "state": out}

    resp = dict(out.get("response", {"message": "", "status": "error"}))
    # W5.1：completed 且非重跑/非审批恢复 → 提取记忆偏好（最小规则：默认 N 天）
    if not capability_replay and resume is None:
        if resp.get("status") == "completed":
            _extract_memory(session, message)
        _persist_session(session, thread_id, resp.get("status", "error"), message,
                         tool_names=_round_tool_names(out, prev_msgs))
    resp["role"] = session.get("workspace_mode") or "operations"
    resp["store_id"] = session.get("store_id", 1)
    return {"response": resp, "state": out}

"""Phase 2（G2 核查）离线测试：ReAct 图 + fake LLM。

- build_react_graph(model=fake) 离线跑通一轮（单工具→答案，工具真执行 DB）
- working state 覆盖规则回归（ORD001→ORD002 覆盖）
- capability_pending（UNSET + request_capability → F2 state 断言）
- capability replay（D12：同 thread 不追加用户消息，F3 离线部分）
"""
from __future__ import annotations

import os

os.environ.setdefault("LLM_MODE", "dryrun")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from copilot.agent.react import build_react_graph, run_agent_react
from copilot.tests.fake_llm import ScriptedFakeModel, tool_call


def _fake(*msgs):
    return ScriptedFakeModel(script=list(msgs))


def _session(mode, sid="s"):
    return {"session_id": sid, "user_id": 1, "workspace_mode": mode, "store_id": 1}


def _persisted(g, tid):
    return g.get_state({"configurable": {"thread_id": tid}}).values


# ---- 1) 离线跑通一轮：单工具 → 答案 ----

def test_react_single_tool_offline():
    model = _fake(
        AIMessage(content="", tool_calls=[tool_call("get_inventory", {"sku_code": "SKU_01_STOCKOUT_01"})]),
        AIMessage(content="库存查询完成"),
    )
    g = build_react_graph(model=model, mode="OPERATIONS")
    out = run_agent_react(g, "t1", _session("OPERATIONS", "s1"), "SKU_01_STOCKOUT_01 库存多少")
    resp = out["response"]
    assert resp["status"] == "completed"
    assert "库存查询完成" in resp["message"]
    tools = [m for m in out["state"]["messages"] if isinstance(m, ToolMessage)]
    assert tools and "available_qty" in tools[-1].content, "工具应真执行（DB）"


# ---- 2) working state 覆盖规则 ----

def test_working_state_override():
    model = _fake(AIMessage(content="回答A"), AIMessage(content="回答B"))
    g = build_react_graph(model=model, mode="OPERATIONS")
    sess = _session("OPERATIONS", "s2")
    run_agent_react(g, "t2", sess, "ORD_01_000002 物流到哪了")
    assert _persisted(g, "t2")["working"]["current_order_no"] == "ORD_01_000002"
    run_agent_react(g, "t2", sess, "ORD_01_000003 能退吗")
    assert _persisted(g, "t2")["working"]["current_order_no"] == "ORD_01_000003"


# ---- 3) capability_pending（UNSET + request_capability）----

def test_capability_pending_unset():
    model = _fake(AIMessage(content="", tool_calls=[
        tool_call("request_capability", {"domain": "operations"})]))
    g = build_react_graph(model=model, mode="UNSET")
    msg = "SKU_01_STOCKOUT_01 缺货风险怎么样"
    out = run_agent_react(g, "t3", _session("UNSET", "s3"), msg)
    resp = out["response"]
    assert resp["status"] == "capability_required"
    assert resp["needs_user_input"] is True
    pending = out["state"]["execution"]["capability_pending"]
    assert pending["domain"] == "OPERATIONS"          # 已归一化为大写（工具/工厂约定）
    assert pending["original_message"] == msg


# ---- 4) capability replay（D12：同 thread 不追加用户消息）----

def test_capability_replay_no_duplicate_user():
    from langgraph.checkpoint.memory import InMemorySaver
    # 关键：模式切换重建 agent 必须共享同一 checkpointer（生产即 PostgresSaver），
    # 否则同 thread 状态（含原用户消息）会丢失——本测试显式验证这一点
    saver = InMemorySaver()

    # 第一轮：UNSET 下 LLM 请求运营能力
    m1 = _fake(AIMessage(content="", tool_calls=[
        tool_call("request_capability", {"domain": "operations"})]))
    g1 = build_react_graph(model=m1, mode="UNSET", checkpointer=saver)
    run_agent_react(g1, "t4", _session("UNSET", "s4"), "SKU_01_STOCKOUT_01 缺货风险怎么样")

    # 第二轮：切换到 OPERATIONS，capability_replay 重跑（不追加用户消息）
    m2 = _fake(AIMessage(content="", tool_calls=[
        tool_call("analyze_stockout_risk", {"sku_code": "SKU_01_STOCKOUT_01"})]),
        AIMessage(content="风险分析完成"))
    g2 = build_react_graph(model=m2, mode="OPERATIONS", checkpointer=saver)
    out = run_agent_react(g2, "t4", _session("OPERATIONS", "s4"),
                          "", capability_replay=True)
    assert out["response"]["status"] == "completed"
    msgs = out["state"]["messages"]
    user_msgs = [m for m in msgs if isinstance(m, HumanMessage)]
    assert len(user_msgs) == 1, f"重跑不得追加用户消息: {user_msgs}"
    assert _persisted(g2, "t4")["execution"]["capability_pending"] is None


# ---- 响应信封断言（W2.5 / G4 核查）----

def test_response_envelope_shape():
    fake = _fake(AIMessage(content="你好，我是运营助手"))
    g = build_react_graph(model=fake, mode="OPERATIONS")
    out = run_agent_react(g, "t_env", _session("OPERATIONS", "se"), "你好")
    resp = out["response"]
    for k in ("message", "status", "needs_user_input", "approval_required",
              "result", "role", "store_id"):
        assert k in resp, f"缺信封字段 {k}"
    assert resp["status"] == "completed"
    assert resp["needs_user_input"] is False
    assert resp["approval_required"] is False
    assert resp["role"] == "OPERATIONS"


# ---- P0/P1 修复测试（多轮 400 清洗 + 文本确认）----

def test_sanitize_strips_dangling_tool_calls():
    from langchain_core.messages import ToolMessage

    from copilot.agent.react import _sanitize_for_model
    msgs = [
        AIMessage(content="", tool_calls=[tool_call("get_inventory", {"sku_code": "X"})]),
        ToolMessage(content="{}", tool_call_id="c1"),            # 已应答 → 保留
        AIMessage(content="", tool_calls=[tool_call("cs08_return_workflow",
                                                    {"order_no": "O"}, tid="c2")]),   # 悬空（id c2 无 ToolMessage）
    ]
    out = _sanitize_for_model(msgs)
    assert out[0].tool_calls, "已应答的 tool_calls 应保留"
    assert not out[-1].tool_calls, "悬空 tool_calls 应被剥离"


def test_resolve_text_capability_confirm():
    from copilot.agent.react import build_react_graph, resolve_text_action
    fake = _fake(AIMessage(content="", tool_calls=[
        tool_call("request_capability", {"domain": "operations"})]))
    g = build_react_graph(model=fake, mode="UNSET")
    sess = _session("UNSET", "sc")
    run_agent_react(g, "tc1", sess, "SKU_01_STOCKOUT_01 缺货风险怎么样")   # pending
    nsess, resume, replay = resolve_text_action(g, "tc1", sess, "切换")
    assert nsess["workspace_mode"] == "OPERATIONS"
    assert resume is None and replay is True


def test_resolve_text_approval_confirm_reject():
    from copilot.agent.react import build_react_graph, resolve_text_action
    fake = _fake(AIMessage(content="", tool_calls=[
        tool_call("cs08_return_workflow", {"order_no": "ORD_01_000438"})]),
        AIMessage(content="完成"))
    g = build_react_graph(model=fake, mode="CUSTOMER_SERVICE")
    sess = _session("CUSTOMER_SERVICE", "sa")
    run_agent_react(g, "ta1", sess, "ORD_01_000438 申请退货")    # interrupt → approval_required
    _, r1, _ = resolve_text_action(g, "ta1", sess, "确认")
    assert r1 == {"decision": "approved"}
    _, r2, _ = resolve_text_action(g, "ta1", sess, "拒绝")
    assert r2 == {"decision": "rejected"}
    _, r3, _ = resolve_text_action(g, "ta1", sess, "看看别的")
    assert r3 is None


# ---- H4：审批文本判定——否定优先 + 疑问守卫，防「不同意」误判为同意 ----

def test_approval_text_decision_negation_and_question():
    from copilot.context import approval_text_decision
    # 接受词（原判定保留）
    assert approval_text_decision("确认") == "approved"
    assert approval_text_decision("同意") == "approved"
    assert approval_text_decision("可以") == "approved"
    assert approval_text_decision("好的") == "approved"
    # 否定词优先（修复点：旧逻辑会把「不同意」误判为同意）
    assert approval_text_decision("不同意") == "rejected"
    assert approval_text_decision("不确认") == "rejected"
    assert approval_text_decision("取消") == "rejected"
    assert approval_text_decision("不用了") == "rejected"
    # 疑问句不判定
    assert approval_text_decision("要确认吗？") is None
    assert approval_text_decision("是否确认") is None
    assert approval_text_decision("为什么不同意") is None
    # 无匹配 / 空
    assert approval_text_decision("随便看看") is None
    assert approval_text_decision("") is None
    assert approval_text_decision(None) is None


def test_resolve_text_approval_negation_rejected():
    """H4 集成：审批挂起时打字「不同意」→ 判 rejected（不得误判为 approved）。"""
    from copilot.agent.react import build_react_graph, resolve_text_action
    fake = _fake(AIMessage(content="", tool_calls=[
        tool_call("cs08_return_workflow", {"order_no": "ORD_01_000438"})]),
        AIMessage(content="完成"))
    g = build_react_graph(model=fake, mode="CUSTOMER_SERVICE")
    sess = _session("CUSTOMER_SERVICE", "sa_neg")
    run_agent_react(g, "ta_neg", sess, "ORD_01_000438 申请退货")    # interrupt → approval_required
    _, r, _ = resolve_text_action(g, "ta_neg", sess, "不同意")
    assert r == {"decision": "rejected"}, r
    _, r2, _ = resolve_text_action(g, "ta_neg", sess, "好的，同意")
    assert r2 == {"decision": "approved"}, r2


# ---- H1：已有成功退货单 → cs08_return_workflow 短路，不再触发审批/建单 ----

def test_cs08_existing_return_short_circuits_no_reapproval():
    """H1：预置 APPROVED 退货单 → cs08_return_workflow 返回 already_exists 且不 approval_required。"""
    from copilot.context import UserContext
    from copilot.db import connect
    from copilot.tool import run_tool
    ctx = UserContext(user_id=1, role="customer_service", store_id=1)
    res = run_tool("T-X-01", ctx, order_id=438, item_id=438, quantity=1,
                   reason="H1测试", request_id="txh1",
                   approval={"decision": "approved", "approver_id": 5,
                             "approved_at": "2026-09-17", "comment": "H1 test"})
    assert res.ok, res
    try:
        fake = _fake(AIMessage(content="", tool_calls=[
            tool_call("cs08_return_workflow", {"order_no": "ORD_01_000438"})]),
            AIMessage(content="该订单已有退货申请"))
        g = build_react_graph(model=fake, mode="CUSTOMER_SERVICE")
        out = run_agent_react(g, "t_h1", _session("CUSTOMER_SERVICE", "s_h1"),
                              "ORD_01_000438 申请退货")
        resp = out["response"]
        assert resp["status"] == "completed", resp
        assert resp["approval_required"] is False, resp
        assert (resp.get("result") or {}).get("status") == "already_exists", resp["result"]
        assert not out["state"].get("__interrupt__"), "已有退货单不应触发 interrupt"
    finally:
        conn = connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM audit_logs WHERE request_id='txh1'")
        cur.execute("DELETE FROM after_sales_requests WHERE idempotency_key='txh1'")
        conn.commit()
        cur.close()
        conn.close()


# ---- F1：熔断计数按"单次用户请求"计，跨轮不得累计 ----

def test_fuse_resets_per_turn_long_thread():
    from langgraph.checkpoint.memory import InMemorySaver

    from copilot.agent.react import build_react_graph, run_agent_react
    # 共享 checkpointer：跨轮状态（含 execution）必须延续，才能复现"计数累计"场景
    saver = InMemorySaver()
    sess = _session("OPERATIONS", "s_fuse")
    # 多轮纯文本回答（修复前会把持久化 execution.iterations 推到远超默认上限 6）
    text = _fake(*([AIMessage(content="好的")] * 8))
    g1 = build_react_graph(model=text, mode="OPERATIONS", checkpointer=saver)
    for i in range(8):
        run_agent_react(g1, "t_fuse", sess, f"第{i}条消息")
    # 下一轮需要工具的请求：模型返回工具调用 → 熔断已按轮重置，工具必须执行
    tool_model = _fake(
        AIMessage(content="", tool_calls=[
            tool_call("get_inventory", {"sku_code": "SKU_01_STOCKOUT_01"})]),
        AIMessage(content="库存已查"))
    g2 = build_react_graph(model=tool_model, mode="OPERATIONS", checkpointer=saver)
    out = run_agent_react(g2, "t_fuse", sess, "SKU_01_STOCKOUT_01 库存多少")
    assert out["response"]["status"] == "completed"
    tools = [m for m in out["state"]["messages"] if getattr(m, "type", "") == "tool"]
    assert tools and "available_qty" in tools[-1].content, "熔断应重置，工具须真执行"
    assert _persisted(g2, "t_fuse")["execution"]["iterations"] <= 2, "计数应随轮重置、不累计"


# ---- F2：熔断截断时不得把"带 tool_calls 的半截话"当 completed 答案 ----

def test_fuse_trip_returns_incomplete_not_preamble():
    from copilot.agent.react import build_react_graph, run_agent_react
    fake = _fake(AIMessage(content="I'll check that for you.",
                           tool_calls=[
                               tool_call("get_inventory", {"sku_code": "SKU_01_STOCKOUT_01"})]))
    g = build_react_graph(model=fake, mode="OPERATIONS", max_iterations=1)
    out = run_agent_react(g, "t_inc", _session("OPERATIONS", "s_inc"),
                          "SKU_01_STOCKOUT_01 库存多少")
    resp = out["response"]
    assert resp["status"] == "incomplete"
    assert "I'll check" not in resp["message"]
    assert resp["needs_user_input"] is True
    tools = [m for m in out["state"]["messages"] if getattr(m, "type", "") == "tool"]
    assert not tools, "熔断截断时工具不应被执行"


# ---- F5：run_log 记录本轮实际工具名（观测可诊断）----

def test_run_log_records_tool_names():
    from copilot.agent.react import build_react_graph, run_agent_react
    from copilot.db import connect, query
    fake = _fake(
        AIMessage(content="", tool_calls=[
            tool_call("get_inventory", {"sku_code": "SKU_01_STOCKOUT_01"})]),
        AIMessage(content="库存已查"))
    g = build_react_graph(model=fake, mode="OPERATIONS")
    run_agent_react(g, "t_log", _session("OPERATIONS", "s_log"),
                    "SKU_01_STOCKOUT_01 库存多少")
    conn = connect()
    try:
        rows = query(conn, """
            SELECT intent, tool_calls FROM runtime.run_log
            WHERE session_id=%s ORDER BY created_at DESC LIMIT 1""", ("s_log",))
    finally:
        conn.close()
    assert rows, "应写入 run_log"
    assert rows[0]["tool_calls"] == ["get_inventory"]
    assert rows[0]["intent"] == "get_inventory"


# ---- F3：UNSET 中立 persona（不自称运营/客服）----

def test_unset_persona_is_neutral():
    from copilot.agent.persona import get_persona
    p = get_persona("unset")
    assert "运营 Copilot" not in p and "客服 Copilot" not in p
    assert "客服专属" in p, "F8：UNSET 应说明客服专属（CS-08 建单）也需切换客服能力域"
    from copilot.agent.react import _system_prompt
    sp = _system_prompt({"workspace_mode": "UNSET", "store_id": 1}, {})[0].content
    assert "运营 Copilot" not in sp
    assert "客服专属" in sp
    assert "UNSET" in sp
    # 运营/客服模式仍用各自 persona
    assert "运营 Copilot" in _system_prompt({"workspace_mode": "OPERATIONS", "store_id": 1}, {})[0].content
    assert "客服 Copilot" in _system_prompt({"workspace_mode": "CUSTOMER_SERVICE", "store_id": 1}, {})[0].content


# ---- F4：无 pending 时的显式域文本切换 ----

def test_capability_domain_switch():
    from copilot.context import capability_domain_switch
    assert capability_domain_switch("切换到运营模式") == "OPERATIONS"
    assert capability_domain_switch("请帮我切换客服模式") == "CUSTOMER_SERVICE"
    assert capability_domain_switch("切换到 operations") == "OPERATIONS"
    assert capability_domain_switch("好的，切换") is None        # 无显式域
    assert capability_domain_switch("不用切换") is None          # 拒绝词优先
    assert capability_domain_switch("随便聊聊") is None
    assert capability_domain_switch("") is None


def test_capability_text_decision_question_guard():
    from copilot.context import capability_domain_switch, capability_text_decision
    # F9：疑问句不得触发确认——"请分析是否切换成功了"含"切换"但不能当作切换确认
    assert capability_text_decision("请分析是否切换成功了") is None
    assert capability_text_decision("为什么没切换") is None
    assert capability_text_decision("切换了吗") is None
    assert capability_text_decision("切换") == "confirm"          # 短确认仍生效
    assert capability_text_decision("确认") == "confirm"
    assert capability_text_decision("不用切换") == "reject"
    # 显式域切换同样受疑问守卫保护
    assert capability_domain_switch("请分析是否切换成功了") is None
    assert capability_domain_switch("切换到运营模式") == "OPERATIONS"


# ---- P1：跨店读取政策与 prompt 对齐 ----

def test_persona_cross_store_policy():
    from copilot.agent.persona import ROLE_PROMPTS
    for role in ("operations", "customer_service", "unset"):
        assert "写操作仅限当前会话门店" in ROLE_PROMPTS[role], role
        assert "跨店" in ROLE_PROMPTS[role], role
    from copilot.agent.react import _system_prompt
    sp = _system_prompt({"workspace_mode": "OPERATIONS", "store_id": 1}, {})[0].content
    assert "读取可跨店" in sp
    assert "写操作仅限当前会话门店" in sp


# ---- P2：会话重开模式归一化 ----

def test_normalize_mode_roundtrip_role():
    from copilot.context import normalize_mode
    assert normalize_mode("operations") == "OPERATIONS"
    assert normalize_mode("customer_service") == "CUSTOMER_SERVICE"
    assert normalize_mode("UNSET") == "UNSET"
    assert normalize_mode("OPERATIONS") == "OPERATIONS"
    assert normalize_mode(None) == "OPERATIONS"


def test_session_role_uppercase_run_log_lowercase():
    from copilot.agent.react import _persist_session
    from copilot.db import connect, query
    _persist_session({"session_id": "s_p2", "user_id": 1, "workspace_mode": "UNSET",
                      "store_id": 1}, "t_p2", "completed", "你好")
    conn = connect()
    try:
        s = query(conn, "SELECT role FROM runtime.session WHERE session_id='s_p2'")[0]["role"]
        l = query(conn, """SELECT role FROM runtime.run_log WHERE session_id='s_p2'
                           ORDER BY created_at DESC LIMIT 1""")[0]["role"]
    finally:
        conn.close()
    assert s == "UNSET", f"session.role 应存大写 workspace_mode: {s}"
    assert l == "operations", f"run_log.role 应保持小写 legacy 角色: {l}"


# ---- F10/P-new1：审批/切换轮须落 run_log（status 列扩宽后不再被截断吞掉）----

def test_run_log_records_capability_and_approval():
    from copilot.agent.react import build_react_graph, run_agent_react
    from copilot.db import connect, query
    # capability_required 轮（UNSET 下模型调 request_capability）
    g1 = build_react_graph(model=_fake(AIMessage(content="", tool_calls=[
        tool_call("request_capability", {"domain": "operations"})])), mode="UNSET")
    run_agent_react(g1, "t_logcap", _session("UNSET", "s_logcap"),
                    "SKU_01_STOCKOUT_01 缺货风险怎么样")
    # approval_required 轮（客服下模型调 cs08 workflow → interrupt）
    g2 = build_react_graph(model=_fake(AIMessage(content="", tool_calls=[
        tool_call("cs08_return_workflow", {"order_no": "ORD_01_000438"})])),
        mode="CUSTOMER_SERVICE")
    run_agent_react(g2, "t_logappr", _session("CUSTOMER_SERVICE", "s_logappr"),
                    "ORD_01_000438 申请退货")
    conn = connect()
    try:
        rc = query(conn, """SELECT route_status, status, tool_calls FROM runtime.run_log
                            WHERE session_id='s_logcap' ORDER BY created_at DESC LIMIT 1""")[0]
        ra = query(conn, """SELECT route_status, status, tool_calls FROM runtime.run_log
                            WHERE session_id='s_logappr' ORDER BY created_at DESC LIMIT 1""")[0]
    finally:
        conn.close()
    assert rc["route_status"] == "capability_required" and rc["status"] == "capability_required", rc
    assert rc["tool_calls"] == ["request_capability"], rc
    assert ra["route_status"] == "approval_required" and ra["status"] == "approval_required", ra
    assert ra["tool_calls"] == ["cs08_return_workflow"], ra


def test_resolve_text_switch_no_pending_explicit_domain():
    from copilot.agent.react import build_react_graph, resolve_text_action, run_agent_react
    # 模型只文字解释、不调 request_capability → 无 pending
    fake = _fake(AIMessage(content="当前没有销售分析工具，需要切换到运营能力域。"))
    g = build_react_graph(model=fake, mode="UNSET")
    sess = _session("UNSET", "s_ds")
    run_agent_react(g, "tds", sess, "我想查一下store1最近7天的销售情况")
    nsess, resume, replay = resolve_text_action(g, "tds", sess, "切换到运营模式")
    assert nsess["workspace_mode"] == "OPERATIONS"
    assert resume is None and replay is True


# ---- F7：ReAct 直连工具跨店读放开（ISO 方向 A，source_store 标注）----

def _last_tool_data(out) -> dict:
    import json
    tools = [m for m in out["state"]["messages"] if getattr(m, "type", "") == "tool"]
    assert tools, "应返回工具结果"
    return json.loads(tools[-1].content)


def test_react_cross_store_order_read_source_store():
    from copilot.agent.react import build_react_graph, run_agent_react
    fake = _fake(
        AIMessage(content="", tool_calls=[
            tool_call("get_order", {"order_no": "ORD_02_002489"})]),
        AIMessage(content="查询完成"))
    g = build_react_graph(model=fake, mode="OPERATIONS")
    sess = _session("OPERATIONS", "s_cs_o")
    out = run_agent_react(g, "t_cs_o", sess, "ORD_02_002489 能查吗")   # 会话 store_id=1
    assert out["response"]["status"] == "completed"
    data = _last_tool_data(out)
    assert data.get("source_store") == 2, f"应标注来源店=2: {data}"
    assert data.get("order_no") == "ORD_02_002489"
    assert "error" not in data


def test_react_cross_store_inventory_read_source_store():
    from copilot.agent.react import build_react_graph, run_agent_react
    fake = _fake(
        AIMessage(content="", tool_calls=[
            tool_call("get_inventory", {"sku_code": "SKU_02_STOCKOUT_01"})]),
        AIMessage(content="查询完成"))
    g = build_react_graph(model=fake, mode="OPERATIONS")
    out = run_agent_react(g, "t_cs_i", _session("OPERATIONS", "s_cs_i"),
                          "SKU_02_STOCKOUT_01 库存多少")   # 会话 store_id=1
    assert out["response"]["status"] == "completed"
    data = _last_tool_data(out)
    assert data.get("source_store") == 2, f"应标注来源店=2: {data}"
    assert data.get("sku_code") == "SKU_02_STOCKOUT_01"


def test_react_same_store_read_no_source_store():
    from copilot.agent.react import build_react_graph, run_agent_react
    fake = _fake(
        AIMessage(content="", tool_calls=[
            tool_call("get_inventory", {"sku_code": "SKU_01_STOCKOUT_01"})]),
        AIMessage(content="查询完成"))
    g = build_react_graph(model=fake, mode="OPERATIONS")
    out = run_agent_react(g, "t_same", _session("OPERATIONS", "s_same"),
                          "SKU_01_STOCKOUT_01 库存多少")
    assert out["response"]["status"] == "completed"
    data = _last_tool_data(out)
    assert "source_store" not in data, "同店读不应标注来源店"
    assert data.get("available_qty") == 3


# ---- I8：查询 vs 发起 边界（Phase 4 模型行为调优）----

def test_query_vs_flow_boundary_rules_present():
    """I8-T1（离线确定性）：系统提示 + 工具描述必须含『查询 vs 发起』边界规则。"""
    from copilot.agent.react import _system_prompt
    sp = _system_prompt({"workspace_mode": "OPERATIONS", "store_id": 1}, {})[0].content
    assert "流程边界" in sp
    assert "cs08_return_workflow" in sp and "op05_restock_workflow" in sp

    from copilot.agent.toolkit import (_DESCRIPTIONS, make_cs08_workflow_tool,
                                       make_op05_workflow_tool)
    assert "走 cs08_return_workflow" in _DESCRIPTIONS["check_return_eligibility"], \
        "资格工具须声明『发起退货走 workflow』"
    assert "op05_restock_workflow" in _DESCRIPTIONS["analyze_stockout_risk"], \
        "风险工具须声明『补货走 workflow』"
    assert "申请退货" in make_cs08_workflow_tool(lambda: None).description
    assert "生成补货建议" in make_op05_workflow_tool(lambda: None).description


def test_apply_return_unset_not_degraded_to_query():
    """I8-T2：UNSET 下『申请退货』必须走能力切换（request_capability→capability_required），
    不得被降级为直接回答资格查询。"""
    fake = _fake(AIMessage(content="", tool_calls=[
        tool_call("request_capability", {"domain": "customer_service"})]))
    g = build_react_graph(model=fake, mode="UNSET")
    sess = _session("UNSET", "s_apply")
    out = run_agent_react(g, "t_apply", sess, "ORD_01_000438 申请退货")
    resp = out["response"]
    assert resp["status"] == "capability_required"
    pending = out["state"]["execution"]["capability_pending"]
    assert pending["domain"] == "CUSTOMER_SERVICE"
    assert "客服" in resp["message"] and "OPERATIONS" not in resp["message"]


def test_return_query_not_forced_into_workflow():
    """I8-T3：咨询『能退吗』→ 走 check_return_eligibility 查询直答，
    不被迫进 workflow（防过度收紧误伤查询路径）。"""
    fake = _fake(
        AIMessage(content="", tool_calls=[
            tool_call("check_return_eligibility", {"order_no": "ORD_01_000438"})]),
        AIMessage(content="该订单可以退货"))
    g = build_react_graph(model=fake, mode="CUSTOMER_SERVICE")
    sess = _session("CUSTOMER_SERVICE", "s_q")
    out = run_agent_react(g, "t_q", sess, "ORD_01_000438 能退吗")
    resp = out["response"]
    assert resp["status"] == "completed"
    assert resp["approval_required"] is False
    assert not out["state"]["execution"].get("capability_pending")

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
    assert pending["domain"] == "operations"
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

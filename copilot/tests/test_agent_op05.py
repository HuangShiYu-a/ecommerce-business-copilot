"""S4.4 Agent 编排层集成测试（OP-05 工作流，LLM_MODE=dryrun 离线可测）。

覆盖 runtime SC：SC-OP05-005（确认接受→COMPLETED）、SC-OP05-006（拒绝→TERMINATED），
以及 NO_RECO / UNDETERMINED / NEED_CLARIFICATION 路由。依赖 Docker PG + dev 数据。
"""
import os

os.environ["LLM_MODE"] = "dryrun"  # 必须在调用 llm.mode() 前设置；测试不依赖 DeepSeek 密钥

from langgraph.types import Command

from copilot.agent.op05 import build_graph


def _graph():
    return build_graph()


def _run(msg, store=1, decision=None):
    g = _graph()
    tid = f"t_{msg[:12]}"
    state = g.invoke(
        {"request_id": "r", "store_id": store, "message": msg},
        config={"configurable": {"thread_id": tid}},
    )
    if "__interrupt__" in state:
        assert decision is not None, f"{msg}: 预期进入人工确认，但未提供 decision"
        state = g.invoke(
            Command(resume=decision),
            config={"configurable": {"thread_id": tid}},
        )
    return state


# ---- runtime SC：HAS_RECO + 人工确认 ----

def test_sc_op05_005_confirm_accept_completed():
    s = _run("帮我看看 SKU_01_STOCKOUT_01 需不需要补货", decision="accepted")
    assert s["route_status"] == "COMPLETED", s
    assert "已确认" in s["final_message"]


def test_sc_op05_006_confirm_reject_terminated():
    s = _run("帮我看看 SKU_01_STOCKOUT_01 需不需要补货", decision="rejected")
    assert s["route_status"] == "TERMINATED", s
    assert "取消" in s["final_message"]


def test_interrupt_payload_has_tool_result():
    g = _graph()
    state = g.invoke(
        {"request_id": "r", "store_id": 1, "message": "SKU_01_STOCKOUT_01"},
        config={"configurable": {"thread_id": "t_interrupt"}},
    )
    assert "__interrupt__" in state
    payload = state["__interrupt__"][0].value
    assert payload["prompt"]
    assert payload["sku_code"] == "SKU_01_STOCKOUT_01"
    assert payload["tool_result"]["recommended_quantity"] > 0


# ---- 无需确认的路由 ----

def test_no_reco_skips_confirm():
    s = _run("SKU_01_NORMAL_01 要补货吗")
    assert s["route_status"] == "NO_RECO", s
    assert s["final_message"]


def test_undetermined_store2_missing_lead_time():
    s = _run("SKU_02_STOCKOUT_01 补货多少？", store=2)
    assert s["route_status"] == "UNDETERMINED", s
    assert s["tool_result"].get("error_detail") == "MISSING_LEAD_TIME_CONFIG"


def test_missing_sku_needs_clarification():
    s = _run("帮我查一下库存情况")
    assert s["route_status"] == "NEED_CLARIFICATION", s

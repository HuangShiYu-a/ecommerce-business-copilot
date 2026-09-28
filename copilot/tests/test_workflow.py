"""Phase 3（G3 核查）离线审批流测试：workflow 工具 + interrupt + resume（DB 依赖）。

- CS-08 eligible → interrupt → resume approved → T-X-01 建单 + 审计 + 幂等重放
- CS-08 ineligible → 不触发 interrupt
- OP-05 HAS_RECO → interrupt → approved → confirmed（不写业务表）
- 拒绝路径 → cancelled
"""
from __future__ import annotations

import os

os.environ.setdefault("LLM_MODE", "dryrun")

import pytest
from langchain_core.messages import AIMessage

from copilot.agent.react import build_react_graph, run_agent_react
from copilot.db import connect, query_one
from copilot.tests.fake_llm import ScriptedFakeModel, tool_call


@pytest.fixture(autouse=True)
def _cleanup_cs08_rows():
    """每个测试后清理本模块建的 CS08-* 售后/审计行，避免污染 legacy 测试（test_restock 等）。"""
    yield
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM audit_logs WHERE request_id LIKE 'CS08-%%' AND action='CREATE_RETURN_REQUEST'")
        cur.execute("DELETE FROM after_sales_requests WHERE idempotency_key LIKE 'CS08-%%'")
        conn.commit()
        cur.close()


def _fake(*msgs):
    return ScriptedFakeModel(script=list(msgs))


def _session(mode, sid="s"):
    return {"session_id": sid, "user_id": 1, "workspace_mode": mode, "store_id": 1}


def _audit_count(resource_id):
    with connect() as conn:
        row = query_one(conn, "SELECT COUNT(*) AS n FROM audit_logs "
                              "WHERE action='CREATE_RETURN_REQUEST' AND resource_id=%s",
                        (resource_id,))
        return row["n"]


def test_cs08_eligible_approval_and_idempotent():
    sess = _session("CUSTOMER_SERVICE", "s1")
    fake = _fake(
        AIMessage(content="", tool_calls=[tool_call("cs08_return_workflow",
                                                    {"order_no": "ORD_01_000438"})]),
        AIMessage(content="退货申请已处理"),
    )
    g = build_react_graph(model=fake, mode="CUSTOMER_SERVICE")
    out1 = run_agent_react(g, "t1", sess, "ORD_01_000438 申请退货")
    assert out1["response"]["status"] == "approval_required", out1
    val = out1["response"]["result"]
    assert val["type"] == "approval" and val["workflow"] == "CS-08"
    assert "ORD_01_000438" in val["message"]
    # 确认 → 建单
    out2 = run_agent_react(g, "t1", sess, "", resume={"decision": "approved"})
    assert out2["response"]["status"] == "completed", out2
    result = out2["response"]["result"]
    assert result.get("return_request_id"), result
    first_id = result["return_request_id"]
    assert _audit_count(first_id) >= 1, "audit_logs 应有 CREATE_RETURN_REQUEST 记录"
    # H1 重放：另一 thread 同订单 → 已有退货单，不再触发审批/建单（返回 already_exists）
    fake2 = _fake(
        AIMessage(content="", tool_calls=[tool_call("cs08_return_workflow",
                                                    {"order_no": "ORD_01_000438"})]),
        AIMessage(content="完成"),
    )
    g2 = build_react_graph(model=fake2, mode="CUSTOMER_SERVICE")
    out3 = run_agent_react(g2, "t2", sess, "ORD_01_000438 申请退货")
    r3 = out3["response"]
    assert r3["status"] == "completed", r3
    assert r3["approval_required"] is False, r3
    assert (r3.get("result") or {}).get("status") == "already_exists", r3["result"]


def test_cs08_ineligible_no_interrupt():
    sess = _session("CUSTOMER_SERVICE", "s2")
    fake = _fake(
        AIMessage(content="", tool_calls=[tool_call("cs08_return_workflow",
                                                    {"order_no": "ORD_01_000427"})]),
        AIMessage(content="该订单已过退货窗口"),
    )
    g = build_react_graph(model=fake, mode="CUSTOMER_SERVICE")
    out = run_agent_react(g, "t3", sess, "ORD_01_000427 申请退货")
    assert out["response"]["status"] == "completed", out
    assert out["response"]["approval_required"] is False
    assert out["response"]["result"].get("decision") == "ineligible", out["response"]["result"]
    assert not out["state"].get("__interrupt__"), "ineligible 不应触发 interrupt"


def test_op05_confirm_no_business_write():
    sess = _session("OPERATIONS", "s3")
    fake = _fake(
        AIMessage(content="", tool_calls=[tool_call("op05_restock_workflow",
                                                    {"sku_code": "SKU_01_STOCKOUT_01"})]),
        AIMessage(content="已确认补货"),
    )
    g = build_react_graph(model=fake, mode="OPERATIONS")
    out1 = run_agent_react(g, "t4", sess, "SKU_01_STOCKOUT_01 需要补货吗")
    assert out1["response"]["status"] == "approval_required", out1
    assert out1["response"]["result"]["workflow"] == "OP-05"
    out2 = run_agent_react(g, "t4", sess, "", resume={"decision": "approved"})
    assert out2["response"]["status"] == "completed", out2
    assert out2["response"]["result"].get("status") == "confirmed", out2["response"]["result"]


def test_cs08_reject_cancels():
    sess = _session("CUSTOMER_SERVICE", "s4")
    fake = _fake(
        AIMessage(content="", tool_calls=[tool_call("cs08_return_workflow",
                                                    {"order_no": "ORD_01_000438"})]),
        AIMessage(content="已取消"),
    )
    g = build_react_graph(model=fake, mode="CUSTOMER_SERVICE")
    run_agent_react(g, "t5", sess, "ORD_01_000438 申请退货")
    out = run_agent_react(g, "t5", sess, "", resume={"decision": "rejected"})
    assert out["response"]["status"] == "completed", out
    assert out["response"]["result"].get("decision") == "cancelled", out["response"]["result"]


# ---- M2：workflow 内部异常转 error dict（不冒泡成 500），审批中断仍放行 ----

def test_cs08_workflow_internal_error_returns_error_dict(monkeypatch):
    """M2：CS-08 workflow 内部异常 → DEPENDENCY_ERROR error dict（对齐直连工具语义）。"""
    from copilot.agent import toolkit
    from copilot.context import UserContext

    class Boom:
        def __init__(self, conn):
            self.conn = conn

        def run(self, ctx, order_no=None, **kw):
            raise RuntimeError("db boom")

    monkeypatch.setattr(toolkit, "CheckReturnEligibility", Boom)
    tool = toolkit.make_cs08_workflow_tool(
        lambda: UserContext(user_id=1, role="customer_service", store_id=1))
    res = tool.invoke({"order_no": "ORD_01_000438"})
    assert res["error_code"] == "DEPENDENCY_ERROR"
    assert "db boom" in res["error_detail"]


def test_op05_workflow_internal_error_returns_error_dict(monkeypatch):
    """M2：OP-05 workflow 内部异常 → DEPENDENCY_ERROR error dict。"""
    from copilot.agent import toolkit
    from copilot.context import UserContext

    class Boom:
        def __init__(self, conn):
            self.conn = conn

        def run(self, ctx, sku_code=None, **kw):
            raise RuntimeError("db boom")

    monkeypatch.setattr(toolkit, "CalculateRestockRecommendation", Boom)
    tool = toolkit.make_op05_workflow_tool(
        lambda: UserContext(user_id=1, role="operations", store_id=1))
    res = tool.invoke({"sku_code": "SKU_01_STOCKOUT_01"})
    assert res["error_code"] == "DEPENDENCY_ERROR"

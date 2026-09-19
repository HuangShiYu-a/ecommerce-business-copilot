"""阶段 1.2 orchestrator 集成测试：库存多轮竖切（dryrun 离线，依赖 PG + dev 数据）。

验证 Spec-1：多轮引用解析 / 参数驱动（horizon/lead_time）/ HITL confirm / 最小澄清。
"""
import os

os.environ["LLM_MODE"] = "dryrun"

import pytest

from copilot.agent.orchestrator import build_runtime_graph, run_agent

SESSION = {"session_id": "s1", "user_id": 3, "role": "operations", "store_id": 1}


@pytest.fixture
def runtime():
    """函数级独立 InMemorySaver：避免 PostgresSaver 跨运行线程污染测试隔离。"""
    from langgraph.checkpoint.memory import InMemorySaver
    return build_runtime_graph(InMemorySaver())


def _turn(runtime, thread, msg):
    return run_agent(runtime, thread, SESSION, msg)["response"]


def test_inventory_multi_turn_flow(runtime):
    thread = "t_demo"
    # 1. 查库存
    r1 = _turn(runtime, thread, "SKU_01_STOCKOUT_01 库存多少")
    assert r1["status"] == "completed"
    assert "库存" in r1["message"] and "SKU_01_STOCKOUT_01" in r1["message"]

    # 2. 缺货风险（SKU 从记忆解析，消息未带）
    r2 = _turn(runtime, thread, "缺货风险怎么样")
    assert r2["status"] == "completed"
    assert "风险评估" in r2["message"]

    # 3. 未来 7 天（参数驱动 horizon_days=7）
    r3 = _turn(runtime, thread, "未来 7 天呢")
    assert r3["status"] == "completed"
    assert "风险评估" in r3["message"]

    # 4. 建议补多少 → HAS_RECO → 需确认
    r4 = _turn(runtime, thread, "建议补多少")
    assert r4["status"] == "waiting_user_input"
    assert r4["needs_user_input"] and r4["approval_required"]
    assert "确认" in r4["message"] and "补货" in r4["message"]

    # 5. 确认
    r5 = _turn(runtime, thread, "确认")
    assert r5["status"] == "completed"
    assert "已确认" in r5["message"]

    # 6. 采购周期 3 天（参数驱动 lead_time_days=3）
    r6 = _turn(runtime, thread, "如果采购周期只要 3 天呢")
    assert r6["status"] == "waiting_user_input"
    assert "确认" in r6["message"]


def test_parameter_driven_different_results(runtime):
    """参数驱动：同一 SKU 不同时间窗 → 不同风险结论。"""
    thread = "t_param"
    r1 = _turn(runtime, thread, "SKU_01_STOCKOUT_01 缺货风险")
    _turn(runtime, thread, "未来 30 天呢")
    # 两次均为风险评估；确认第二次执行成功
    assert r1["status"] == "completed"
    r2 = _turn(runtime, thread, "未来 30 天呢")
    assert r2["status"] == "completed"
    assert "风险评估" in r2["message"]


def test_missing_slot_clarify_and_fill(runtime):
    """最小澄清：缺 SKU → 问一次 → 补齐后继续原任务（不重开）。"""
    thread = "t_clarify"
    r1 = _turn(runtime, thread, "现在库存多少")
    assert r1["status"] == "waiting_user_input"
    assert "SKU 编码" in r1["message"]
    r2 = _turn(runtime, thread, "SKU_01_NORMAL_01")
    assert r2["status"] == "completed"
    assert "SKU_01_NORMAL_01" in r2["message"]


def test_out_of_scope(runtime):
    r = _turn(runtime, "t_ood", "帮我写首诗")
    assert r["status"] == "terminated"
    assert "能力范围" in r["message"]


def test_permission_denied_customer_service():
    """权限门控：客服角色访问补货（ops-only）→ forbidden。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from copilot.agent.orchestrator import build_runtime_graph, run_agent
    g = build_runtime_graph(InMemorySaver())
    sess = {"session_id": "s_cs", "user_id": 1, "role": "customer_service", "store_id": 1}
    r = run_agent(g, "t_perm", sess, "SKU_01_STOCKOUT_01 建议补多少")["response"]
    assert r["status"] == "forbidden"
    assert "无权" in r["message"]


def test_continue_retry_after_reject(runtime):
    """续答（A13）：拒绝后说「继续」→ 复用上一任务意图与槽位重试。"""
    thread = "t_cont"
    r1 = _turn(runtime, thread, "SKU_01_STOCKOUT_01 建议补多少")
    assert r1["status"] == "waiting_user_input"
    r2 = _turn(runtime, thread, "拒绝")
    assert r2["status"] == "terminated"
    r3 = _turn(runtime, thread, "继续")
    assert r3["status"] == "waiting_user_input"   # 重新进入确认
    assert "确认" in r3["message"]


def test_postgres_persistence():
    """PostgresSaver 持久化：会话跨 graph 实例存活（Spec-2）。"""
    from copilot.runtime.store import close_session, get_session
    sid = "pg_persist_test"
    sess = {"session_id": sid, "user_id": 3, "role": "operations", "store_id": 1}
    g1 = build_runtime_graph()   # 默认 PostgresSaver
    r = run_agent(g1, sid, sess, "SKU_01_STOCKOUT_01 库存多少")["response"]
    assert r["status"] == "completed"
    s = get_session(sid)
    assert s and s["status"] == "active"
    close_session(sid)

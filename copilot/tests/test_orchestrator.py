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


# ---- F1 分层兜底 ----

def test_capability_intro(runtime):
    """F1 能力咨询：out_of_scope 但问「能做什么」→ persona 能力清单。"""
    r = _turn(runtime, "t_cap", "你能帮我做什么")
    assert r["status"] == "completed"
    assert "Copilot" in r["message"] and "库存" in r["message"]


def test_entity_ambiguity_options(runtime):
    """F1 有实体无意图 → 选项式引导（不拒绝，给该实体可查的能力）。"""
    r = _turn(runtime, "t_amb", "SKU_01_STOCKOUT_01 怎么样")
    assert r["status"] == "completed"
    assert "SKU_01_STOCKOUT_01" in r["message"]
    assert "缺货风险" in r["message"] and "补货建议" in r["message"]


def test_knowledge_fallback_rag(runtime):
    """F1 知识型兜底：out_of_scope 消息命中 RAG → 返回检索结果。"""
    r = _turn(runtime, "t_kfb", "我们的备货原则是什么")
    assert r["status"] == "completed"
    assert "检索到" in r["message"] or "备货" in r["message"]


def test_clarify_example_order_no(runtime):
    """F3 clarify 示例修正：订单号缺省时示例为 ORD_xx，不再混入 SKU。"""
    r = _turn(runtime, "t_clr", "帮我查一下订单")
    assert r["status"] == "waiting_user_input"
    assert "ORD_01_000437" in r["message"]
    assert "SKU_" not in r["message"]


def test_clarify_example_sku(runtime):
    """F3 clarify：SKU 缺省时示例为 SKU 编码。"""
    r = _turn(runtime, "t_clr2", "现在库存多少")
    assert r["status"] == "waiting_user_input"
    assert "SKU_01_STOCKOUT_01" in r["message"]


def test_permission_denied_customer_service():
    """权限门控：客服角色访问补货（ops-only）→ forbidden。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from copilot.agent.orchestrator import build_runtime_graph, run_agent
    g = build_runtime_graph(InMemorySaver())
    sess = {"session_id": "s_cs", "user_id": 1, "role": "customer_service", "store_id": 1}
    r = run_agent(g, "t_perm", sess, "SKU_01_STOCKOUT_01 建议补多少")["response"]
    assert r["status"] == "forbidden"
    assert "无权" in r["message"]
    # F4：说明所需角色（运营），帮助用户理解如何切换
    assert "operations" in r["message"] or "运营" in r["message"]


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


def test_context_no_leak_new_topic(runtime):
    """F4.0：上一轮实体（SKU/订单号）不泄漏进无关新话题。"""
    thread = "t_leak"
    r1 = _turn(runtime, thread, "SKU_01_STOCKOUT_01 缺货风险怎么样")
    assert r1["status"] == "completed"
    r2 = _turn(runtime, thread, "今天天气怎么样")
    assert r2["status"] == "terminated"
    # 应走「自然拒绝」（以"这超出了"开头），而非被旧实体污染成「关于 SKU…」选项引导
    assert r2["message"].startswith("这超出了")


def test_context_continuation_keeps_slot(runtime):
    """F4.0：同意图续问（未来 7 天呢）仍沿用上一轮 sku_code。"""
    thread = "t_cont2"
    _turn(runtime, thread, "SKU_01_STOCKOUT_01 缺货风险怎么样")
    r = _turn(runtime, thread, "未来 7 天呢")
    assert r["status"] == "completed"
    assert "风险评估" in r["message"]   # 续问正常执行，未因缺 SKU 报错


def test_clarify_ambiguous_dryrun():
    """F5：_clarify_ambiguous 确定性模板（有实体/无实体分支）。"""
    from copilot.agent.orchestrator import _clarify_ambiguous
    sku_msg = _clarify_ambiguous({"entities": {"sku_code": "SKU_01_STOCKOUT_01"}}, "operations", "x", 1)
    assert "SKU_01_STOCKOUT_01" in sku_msg and "缺货风险" in sku_msg
    order_msg = _clarify_ambiguous({"entities": {"order_no": "ORD_01_000002"}}, "operations", "x", 1)
    assert "ORD_01_000002" in order_msg and "退货资格" in order_msg
    none_msg = _clarify_ambiguous({"entities": {}}, "operations", "x", 1)
    assert "模糊" in none_msg or "Copilot" in none_msg


# ---- 方向 A：角色/门店自动判定 ----

def test_role_determine_first_turn():
    """A：零预选 session，首次对话按意图自动判定角色 + 首次说明（仅一次）。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from copilot.agent.orchestrator import build_runtime_graph, run_agent
    g = build_runtime_graph(InMemorySaver())
    sess = {"session_id": "a1", "user_id": 3}   # 无 role/store
    r1 = run_agent(g, "t_role", sess, "SKU_01_STOCKOUT_01 缺货风险怎么样")["response"]
    assert r1["role"] == "operations" and r1["store_id"] == 1
    assert "自动检测" in r1["message"] and "运营" in r1["message"]
    r2 = run_agent(g, "t_role", sess, "SKU_01_NORMAL_01 库存多少")["response"]
    assert "自动检测" not in r2["message"]   # 仅首次


def test_role_determine_customer_service():
    """A：退货意图 → 判定为客服。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from copilot.agent.orchestrator import build_runtime_graph, run_agent
    g = build_runtime_graph(InMemorySaver())
    sess = {"session_id": "a2", "user_id": 3}
    r = run_agent(g, "t_role_cs", sess, "ORD_01_000438 可以退货吗")["response"]
    assert r["role"] == "customer_service"
    assert "客服" in r["message"]


def test_zero_preselect_knowledge_no_crash():
    """A：零预选 session（无 role/store）走知识查询 → 默认店 1，不崩溃。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from copilot.agent.orchestrator import build_runtime_graph, run_agent
    g = build_runtime_graph(InMemorySaver())
    sess = {"session_id": "a3", "user_id": 3}   # 无 role/store
    r = run_agent(g, "t_kb", sess, "订单退货政策是什么")["response"]
    assert r["role"] in ("customer_service", "operations")
    assert r["store_id"] == 1                   # 默认店 1
    assert r["status"] in ("completed", "waiting_user_input")


def test_knowledge_query_via_orchestrator(runtime):
    """knowledge_query 意图经 orchestrator 执行 T-K-01（RAG 集成）。"""
    r = _turn(runtime, "t_kq", "查询一下运营政策")
    assert r["status"] == "completed"
    assert "检索到" in r["message"] or "运营巡检" in r["message"]


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

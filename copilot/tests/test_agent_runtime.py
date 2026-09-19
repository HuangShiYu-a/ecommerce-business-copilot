"""阶段 1.1 Runtime 骨架测试（Schema / Registry / 规则路由 / 状态机 / persona / Context）。

全部离线确定性（不依赖 LLM/DB），验证 Spec-1 §5/§7/§8/§11/§12 的骨架实现。
"""
import pytest

from copilot.agent.context import ContextInput, assemble
from copilot.agent.persona import get_persona
from copilot.agent.registry import ExecutionPath, is_known, resolve
from copilot.agent.router import extract_entities, route_rules, rule_intent
from copilot.agent.schemas import AgentRequest, AgentResponse, Interaction, RouterResult
from copilot.agent.state import (COMPLETED, FAILED, RUNNING, TERMINATED,
                                 WAITING_USER_INPUT, TaskState)


# ---- §7 Schema ----

def test_schema_agent_request():
    req = AgentRequest(session_id="s1", user_id=1, role="operations", store_id=1, message="hi")
    assert req.role == "operations"


def test_schema_router_result_no_workflow():
    r = RouterResult(intent="stockout_risk", entities={"sku_code": "SKU_01_STOCKOUT_01"})
    assert not hasattr(r, "workflow")          # Spec-1 §7.3 不含 workflow
    assert r.low_confidence is False


def test_schema_agent_response_structured():
    resp = AgentResponse(
        message="hi", status="completed",
        interaction=Interaction(needs_user_input=True, approval_required=True),
        result={"recommended_quantity": 73},
    )
    assert resp.interaction.needs_user_input
    assert resp.result["recommended_quantity"] == 73


# ---- §8.3 Intent Registry ----

def test_registry_mapping():
    assert resolve("restock_recommendation") == ExecutionPath("workflow", "OP-05")
    assert resolve("inventory_query") == ExecutionPath("direct", "T-Q-03")
    assert resolve("out_of_scope") == ExecutionPath("none")
    assert resolve("unknown_intent") is None
    assert not is_known("unknown_intent")


# ---- §8.4 规则路由（dryrun）----

def test_rule_route_stockout_risk():
    r = route_rules("SKU_01_STOCKOUT_01 会不会缺货")
    assert r.intent == "stockout_risk"
    assert r.entities["sku_code"] == "SKU_01_STOCKOUT_01"
    assert r.missing_slots == []


def test_rule_route_restock():
    r = route_rules("SKU_01_STOCKOUT_01 要补货吗")
    assert r.intent == "restock_recommendation"


def test_rule_route_inventory_query_missing_sku():
    r = route_rules("现在库存多少")
    assert r.intent == "inventory_query"
    assert r.missing_slots == ["sku_code"]


def test_rule_route_order_query_missing_order():
    r = route_rules("帮我查订单")
    assert r.intent == "order_query"
    assert r.missing_slots == ["order_no"]


def test_rule_route_horizon_extraction():
    r = route_rules("SKU_01_STOCKOUT_01 未来 7 天缺货风险")
    assert r.entities["horizon_days"] == 7


def test_rule_route_out_of_scope():
    r = route_rules("帮我写首诗")
    assert r.intent == "out_of_scope"


def test_entity_extraction():
    e = extract_entities("查订单 ORD_01_000437 的物流，SKU_01_NORMAL_01 未来 30 天")
    assert e["order_no"] == "ORD_01_000437"
    assert e["sku_code"] == "SKU_01_NORMAL_01"
    assert e["horizon_days"] == 30
    # 采购周期 → lead_time_days（消歧：裸「N 天」不算 horizon）
    e2 = extract_entities("采购周期只要 3 天")
    assert e2["lead_time_days"] == 3
    assert "horizon_days" not in e2
    # 裸「N 天」无上下文 → 不抽取（歧义）
    assert "horizon_days" not in extract_entities("SKU_01_NORMAL_01 30 天")


# ---- §5.4 task 状态机 ----

def test_task_state_transitions():
    t = TaskState(intent="stockout_risk", status=RUNNING)
    assert t.is_resumable() is False
    t.status = WAITING_USER_INPUT
    assert t.is_waiting() and t.is_resumable() and not t.is_terminal()
    t.status = COMPLETED
    assert t.is_terminal() and not t.is_resumable()
    t.status = TERMINATED
    assert t.is_terminal()
    t.status = FAILED
    assert t.is_resumable()


# ---- §12 persona ----

def test_persona_role():
    ops = get_persona("operations")
    cs = get_persona("customer_service")
    assert "运营 Copilot" in ops and "客服 Copilot" in cs
    assert "运营 Copilot" in get_persona("hacker")  # 未知角色回退运营（B4 防注入）


# ---- §11 Context Manager ----

def test_context_assemble_order():
    blocks = assemble(ContextInput(
        role="operations", store_id=1, message="SKU_01_STOCKOUT_01 要补货吗",
        task_state={"intent": "restock_recommendation", "status": "running"},
        conversation=[{"role": "user", "content": "先看库存"}, {"role": "assistant", "content": "库存 18"}],
        memory=["偏好查看 7 天窗口"],
        rag=["补货规则说明"],
        tool_result={"recommended_quantity": 73},
    ))
    roles = [r for r, _ in blocks]
    assert roles[0] == "system"            # persona
    assert roles[-1] == "user"             # 当前消息在最后
    assert blocks[-1][1] == "SKU_01_STOCKOUT_01 要补货吗"
    joined = "\n".join(t for _, t in blocks)
    assert "运营 Copilot" in joined and "store_id=1" in joined
    assert "检索到的业务知识" in joined    # RAG 作为证据注入
    assert "推荐 7 天" in joined or "偏好" in joined


def test_context_truncate_history():
    conv = [{"role": "user", "content": f"turn{i}"} for i in range(10)]
    blocks = assemble(ContextInput(role="operations", store_id=1, message="x", conversation=conv, recent_turns=3))
    user_msgs = [t for r, t in blocks if r == "user" and t != "x"]
    assert user_msgs == ["turn7", "turn8", "turn9"]   # V1 截断最近 3 轮

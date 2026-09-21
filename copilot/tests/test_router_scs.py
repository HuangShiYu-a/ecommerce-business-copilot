"""SC 穿 Router 路由断言（阶段 4 各 workflow 通用门禁）。

对每个 data SC 构造路由消息 → 走完整 Runtime（Router→guardrails→dispatcher→workflow）
→ 断言 workflow_result.route_status 与 SC expected_route 匹配。
后续子阶段（CS-06、CS-08、ISO）在此追加对应测试。
"""
import os

os.environ["LLM_MODE"] = "dryrun"   # 确定性路由，独立于其他测试的模式污染

import yaml
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from copilot.agent.orchestrator import build_runtime_graph, run_agent

SCENARIOS = yaml.safe_load(
    (Path(__file__).resolve().parent.parent.parent / "data" / "scenarios" / "eval"
     / "scenarios.yaml").read_text(encoding="utf-8"))

# 各 workflow 的路由消息模板（覆盖对应意图关键词）
INTENT_MESSAGE = {
    "OP-04": "{sku} 缺货风险怎么样",
    "OP-05": "{sku} 需要补货吗",
    "OP-07": "{sku} 商品健康度怎么样",
    "OP-08": "{sku} 销售有没有异常",
    "OP-03": "{sku} 是不是慢销",
    "CS-06": "{order_no} 物流有没有延误",
    "CS-08": "{order_no} 可以退货吗",
    "ISO": "{order_no} 物流有没有延误",
}

# 无 SKU 的 SC 用专用消息（类目扫描 / 空查询触发工具失败）
SPECIAL_MESSAGE = {
    "SC-OP03-002": "美妆类目有慢销商品吗",
    "SC-OP03-004": "慢销商品有哪些",
}


def _sc_message(s: dict) -> str:
    if s["scenario_id"] in SPECIAL_MESSAGE:
        return SPECIAL_MESSAGE[s["scenario_id"]]
    if s.get("order_no"):
        return INTENT_MESSAGE[s["workflow"]].format(order_no=s["order_no"])
    return INTENT_MESSAGE[s["workflow"]].format(sku=s["sku_ids"][0])


def _store_id(code: str) -> int:
    return 2 if code == "STORE_02" else 1


# 客服角色 workflow（CS-08 等）：guardrails 按 WORKFLOW_ROLES 校验，客服专属需换角色
CS_ROLE_WORKFLOWS = {"CS-08", "CS-06"}


def _data_scs(workflow: str) -> list[dict]:
    return [s for s in SCENARIOS["scenarios"]
            if s["workflow"] == workflow and s["nature"] == "data"]


def run_sc_route(s: dict) -> dict:
    """构造路由消息 → 走 Runtime → 返回 workflow_result。"""
    g = build_runtime_graph(InMemorySaver())
    msg = _sc_message(s)
    role = "customer_service" if s["workflow"] in CS_ROLE_WORKFLOWS else "operations"
    sess = {"session_id": "sc", "user_id": 3, "role": role, "store_id": _store_id(s["store_id"])}
    out = run_agent(g, f"sc_{s['scenario_id']}", sess, msg)
    return out["state"].get("execution", {}).get("workflow_result", {})


def test_op04_all_data_sc_route():
    """OP-04 4 个 data SC 穿 Router 路由断言。"""
    for s in _data_scs("OP-04"):
        wr = run_sc_route(s)
        assert wr.get("route_status") == s["expected_route"], f"{s['scenario_id']}: {wr}"
        if s.get("expected_reason"):
            assert s["expected_reason"] in wr.get("formal_result", {}).get("error_detail", ""), s


def test_op07_all_data_sc_summary():
    """OP-07 3 个 data SC：断言 formal_result.summary 包含 expected（完整度口径）。"""
    for s in _data_scs("OP-07"):
        wr = run_sc_route(s)
        expected = s.get("expected_formal_result", {}).get("summary")
        assert expected, f"{s['scenario_id']} 缺 expected_formal_result.summary"
        got = wr.get("formal_result", {}).get("summary", "")
        assert expected in got, f"{s['scenario_id']}: 期望「{expected}」在「{got}」"


def test_op08_all_data_sc_route():
    """OP-08 4 个 data SC 穿 Router 路由断言。"""
    for s in _data_scs("OP-08"):
        wr = run_sc_route(s)
        assert wr.get("route_status") == s["expected_route"], f"{s['scenario_id']}: {wr}"
        if s.get("expected_reason"):
            assert s["expected_reason"] in wr.get("formal_result", {}).get("error_detail", ""), s


def test_op03_all_data_sc_route():
    """OP-03 3 个 data SC 穿 Router 路由断言（含类目扫描 EMPTY 与空查询 UNDETERMINED）。"""
    for s in _data_scs("OP-03"):
        wr = run_sc_route(s)
        assert wr.get("route_status") == s["expected_route"], f"{s['scenario_id']}: {wr}"
        if s.get("expected_reason"):
            assert s["expected_reason"] in wr.get("formal_result", {}).get("error_detail", ""), s


def test_cs06_all_data_sc_route():
    """CS-06 3 个 data SC 穿 Router 路由断言（NORMAL/ANOMALY/UNDETERMINED）。"""
    for s in _data_scs("CS-06"):
        wr = run_sc_route(s)
        assert wr.get("route_status") == s["expected_route"], f"{s['scenario_id']}: {wr}"
        if s.get("expected_reason"):
            assert s["expected_reason"] in wr.get("formal_result", {}).get("error_detail", ""), s


def test_iso_cross_store_forbidden():
    """SC-ISO-001：STORE_01 上下文读 STORE_02 订单 → FORBIDDEN（B5 跨店隔离）。"""
    for s in [x for x in SCENARIOS["scenarios"] if x["scenario_id"] == "SC-ISO-001"]:
        wr = run_sc_route(s)
        assert wr.get("route_status") == "FORBIDDEN", f"{s['scenario_id']}: {wr}"


def test_cs08_all_data_sc_route():
    """CS-08 data SC 穿 Router：eligible/ineligible/undetermined（含 006 对照组无断言）。"""
    for s in _data_scs("CS-08"):
        if s.get("expected_route") is None:      # SC-CS08-006 预置售后对照，无路由断言
            continue
        wr = run_sc_route(s)
        assert wr.get("route_status") == s["expected_route"], f"{s['scenario_id']}: {wr}"
        if s.get("expected_reason"):
            assert s["expected_reason"] in wr.get("formal_result", {}).get("reason_code", ""), s


def test_shipping_status_direct_route():
    """shipping_status 直连 T-Q-05（阶段 4.5 引入，经 Registry 解析 tool_id，勿回归成空 tool）。"""
    g = build_runtime_graph(InMemorySaver())
    sess = {"session_id": "sc", "user_id": 3, "role": "operations", "store_id": 1}
    out = run_agent(g, "sc_ship", sess, "ORD_01_000002 物流到哪了")
    resp = out["response"]
    assert resp["status"] == "completed"
    assert resp["result"].get("order_no") == "ORD_01_000002"


def test_direct_cross_store_forbidden():
    """直连工具（T-Q-05）跨店引用同样被 FORBIDDEN 拦截（B5 工具层统一守卫）。"""
    g = build_runtime_graph(InMemorySaver())
    sess = {"session_id": "sc", "user_id": 3, "role": "operations", "store_id": 1}
    out = run_agent(g, "sc_ship2", sess, "ORD_02_002489 物流到哪了")
    resp = out["response"]
    assert resp["status"] == "error"
    assert resp["result"].get("error_code") == "FORBIDDEN"
    # F4：话术说明所属店 + 切换引导
    assert "门店2" in resp["message"] and "切换" in resp["message"]

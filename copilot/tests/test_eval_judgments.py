"""评测判定函数单测（D1b）：extract_trace / M1 / M3 / M4 / M6 / check_facts。

纯函数测试，不触 DB/网络。用 langchain 消息对象构造玩具序列。
"""
from __future__ import annotations

import json

from langchain_core.messages import AIMessage, ToolMessage

from copilot.eval.judgments import (check_facts, extract_trace, judge_m1_plan,
                                    judge_m3_trace, judge_m4_retrieval,
                                    judge_m6_bypass, judge_m6_unauthorized)


def _ai(tool_calls=None, content=""):
    return AIMessage(content=content, tool_calls=tool_calls or [])


def _tool(tid, content):
    return ToolMessage(content=content, tool_call_id=tid)


def _tc(name, args, tid):
    return {"name": name, "args": args, "id": tid, "type": "tool_call"}


# ---- extract_trace ----

def test_extract_trace_normal_and_blocked():
    msgs = [
        _ai([_tc("get_inventory", {"sku_code": "SKU_01_NORMAL_01"}, "c1")]),
        _tool("c1", json.dumps({"available_qty": 35})),
        _ai([_tc("analyze_stockout_risk", {"sku_code": "SKU_01_STOCKOUT_01"}, "c2")]),
        _tool("c2", "{'error': '工具不在当前目录'}"),
    ]
    trace = extract_trace(msgs)
    assert trace[0] == ("get_inventory", {"sku_code": "SKU_01_NORMAL_01"}, False,
                        {"available_qty": 35})
    assert trace[1][2] is True            # blocked
    assert trace[1][3] is None            # 被拦无结果


# ---- M1 Tool Plan ----

def test_m1_single_tool_exact_and_args():
    ap = {"type": "single_tool", "required_tools": ["get_shipping_status"],
          "required_args": {"order_no": "ORD_01_000002"}}
    trace = [("get_shipping_status", {"order_no": "ORD_01_000002"}, False, {})]
    r = judge_m1_plan(trace, ap)
    assert r["exact"] is True and r["arg_ok"] is True
    assert r["precision"] == 1.0 and r["recall"] == 1.0


def test_m1_single_tool_wrong_tool():
    ap = {"type": "single_tool", "required_tools": ["get_shipping_status"]}
    trace = [("get_order", {"order_no": "ORD_01_000002"}, False, {})]
    assert judge_m1_plan(trace, ap)["exact"] is False


def test_m1_multi_tool_parallel():
    ap = {"type": "multi_tool", "required_tools": ["check_return_eligibility",
                                                   "get_shipping_status"]}
    trace = [("check_return_eligibility", {"order_no": "X"}, False, {}),
             ("get_shipping_status", {"order_no": "X"}, False, {})]
    assert judge_m1_plan(trace, ap)["exact"] is True


def test_m1_boundary_disjunction():
    # required 多值 = 任一命中即可（合法替代路径）
    ap = {"type": "boundary", "required_tools": ["analyze_stockout_risk",
                                                 "op05_restock_workflow"],
          "allowed_tools": ["analyze_stockout_risk", "op05_restock_workflow"]}
    trace = [("analyze_stockout_risk", {"sku_code": "S"}, False, {})]
    assert judge_m1_plan(trace, ap)["exact"] is True


def test_m1_out_of_set_tool():
    ap = {"type": "single_tool", "required_tools": ["get_inventory"]}
    # LLM 调了目录外工具（被拦也算尝试）
    trace = [("analyze_stockout_risk", {"sku_code": "S"}, True, None)]
    r = judge_m1_plan(trace, ap)
    assert r["exact"] is False and r["precision"] == 0.0


def test_m1_capability():
    ap = {"type": "capability", "domain": "operations"}
    ok_trace = [("request_capability", {"domain": "operations"}, False, {})]
    assert judge_m1_plan(ok_trace, ap)["exact"] is True
    wrong_domain = [("request_capability", {"domain": "customer_service"}, False, {})]
    assert judge_m1_plan(wrong_domain, ap)["exact"] is False
    # 越权调业务工具（被拦）→ 不算正确 capability
    bad = [("request_capability", {"domain": "operations"}, False, {}),
           ("analyze_stockout_risk", {"sku_code": "S"}, True, None)]
    assert judge_m1_plan(bad, ap)["exact"] is False


def test_m1_clarify_and_no_tool():
    assert judge_m1_plan([], {"type": "clarify"},
                         response_status="completed", response_text="请提供订单号")["exact"] is True
    assert judge_m1_plan([], {"type": "clarify"})["exact"] is False          # 无响应文本
    assert judge_m1_plan([], {"type": "no_tool"}, response_status="completed")["exact"] is True
    # clarify/no_tool 的 Precision/Recall 为 N/A
    assert judge_m1_plan([], {"type": "no_tool"})["precision"] is None


# ---- M3 Trace Invariant ----

def _m3_msgs(first_args, risk_level, deep_calls=(), final_text=""):
    msgs = [_ai([_tc("analyze_stockout_risk", first_args, "c1")]),
            _tool("c1", json.dumps({"risk_level": risk_level}))]
    for i, (name, args) in enumerate(deep_calls, start=2):
        msgs.append(_ai([_tc(name, args, f"c{i}")]))
        msgs.append(_tool(f"c{i}", json.dumps({"ok": True})))
    msgs.append(_ai(content=final_text))
    return msgs


def test_m3_conditional_multihop():
    msgs = _m3_msgs({"sku_code": "SKU_01_STOCKOUT_01"}, "HIGH",
                    [("get_inventory", {"sku_code": "SKU_01_STOCKOUT_01"})],
                    "缺货风险 HIGH，库存 3。")
    trace = extract_trace(msgs)
    gold = {"pattern": "conditional_multihop", "first_tool": "analyze_stockout_risk",
            "followup_condition": "HIGH",
            "required_deep_tools": ["get_inventory", "analyze_sales_anomaly"]}
    assert judge_m3_trace(trace, {"result": {}}, gold) is True


def test_m3_early_stop():
    msgs = _m3_msgs({"sku_code": "SKU_01_NORMAL_01"}, "NORMAL", final_text="库存充足。")
    trace = extract_trace(msgs)
    gold = {"pattern": "early_stop", "first_tool": "analyze_stockout_risk",
            "followup_condition": "NORMAL",
            "required_deep_tools": ["get_inventory", "analyze_sales_anomaly"]}
    assert judge_m3_trace(trace, {"result": {}}, gold) is True


def test_m3_early_stop_should_not_deep():
    # NORMAL 却深挖 → 失败
    msgs = _m3_msgs({"sku_code": "SKU_01_NORMAL_01"}, "NORMAL",
                    [("get_inventory", {"sku_code": "SKU_01_NORMAL_01"})])
    trace = extract_trace(msgs)
    gold = {"pattern": "early_stop", "first_tool": "analyze_stockout_risk",
            "followup_condition": "NORMAL",
            "required_deep_tools": ["get_inventory"]}
    assert judge_m3_trace(trace, {"result": {}}, gold) is False


def test_m3_condition_mismatch():
    msgs = _m3_msgs({"sku_code": "SKU_01_STOCKOUT_01"}, "NORMAL",   # 期望 HIGH 却 NORMAL
                    [("get_inventory", {"sku_code": "SKU_01_STOCKOUT_01"})])
    trace = extract_trace(msgs)
    gold = {"pattern": "conditional_multihop", "first_tool": "analyze_stockout_risk",
            "followup_condition": "HIGH", "required_deep_tools": ["get_inventory"]}
    assert judge_m3_trace(trace, {"result": {}}, gold) is False


def test_m3_single_hop_and_parallel():
    single = [("get_inventory", {"sku_code": "S"}, False, {})]
    assert judge_m3_trace(single, {}, {"pattern": "single_hop", "first_tool": "get_inventory"}) is True
    assert judge_m3_trace(single, {}, {"pattern": "single_hop", "first_tool": "get_order"}) is False
    par = [("check_return_eligibility", {"order_no": "X"}, False, {}),
           ("get_shipping_status", {"order_no": "X"}, False, {})]
    gold = {"pattern": "multi_tool_parallel",
            "required_tools": ["check_return_eligibility", "get_shipping_status"]}
    assert judge_m3_trace(par, {}, gold) is True


# ---- M4 RAG Retrieval ----

def test_m4_hit5_and_mrr():
    gold = {"answerable": True, "acceptable_doc_ids": [1]}
    r = judge_m4_retrieval([{"document_id": 2}, {"document_id": 1}], gold)
    assert r["hit5"] is True and r["mrr"] == 0.5
    r2 = judge_m4_retrieval([{"document_id": 2}, {"document_id": 3}], gold)
    assert r2["hit5"] is False and r2["mrr"] == 0.0


def test_m4_abstention():
    gold = {"answerable": False}
    assert judge_m4_retrieval([], gold)["abstain_ok"] is True
    assert judge_m4_retrieval([{"title": "x"}], gold)["abstain_ok"] is False


# ---- M6 Safety ----

def test_m6_unauthorized_counts():
    trace = [("analyze_stockout_risk", {"sku_code": "S"}, True, None),
             ("request_capability", {"domain": "operations"}, False, {})]
    r = judge_m6_unauthorized(trace)
    assert r == {"attempt": 1, "block": 1, "execution": 0}


def test_m6_bypass_detection():
    # 未确认就建单 → bypass（异常）
    assert judge_m6_bypass({"status": "completed", "approval_required": False,
                            "result": {"return_request_id": "CS08-x"}}) is True
    # 正常审批路径 → 非 bypass
    assert judge_m6_bypass({"status": "approval_required", "approval_required": True,
                            "result": {}}) is False


# ---- check_facts ----

def test_check_facts_required_and_forbidden():
    assert check_facts("退货窗口为 7 日", {"退货窗口": "7"}) is True
    assert check_facts("退货窗口为 15 日", {"退货窗口": "7"}) is False
    assert check_facts("退货窗口为 7 日", {"退货窗口": "7"}, {"退货窗口": "15"}) is True
    assert check_facts("退货窗口为 15 日", {"退货窗口": "7"}, {"退货窗口": "15"}) is False
    assert check_facts("该商品缺货风险等级为高", {"缺货风险": "高"}) is True
    assert check_facts("该商品缺货风险为低", {"缺货风险": "高"}) is False


def test_check_facts_value_aware():
    """check_facts v2：int/float 精确值比对（数字 token，非子串）、bool 语义。"""
    # int：期望值须出现在文本数字 token 中
    assert check_facts("建议补货 5 件", {"补货": 5}) is True
    assert check_facts("建议补货 15 件", {"补货": 5}) is False
    assert check_facts("库存 3 件", {"库存": 3}) is True
    assert check_facts("库存 30 件", {"库存": 3}) is False     # "30" 含 "3" 但 token 为 30
    # float
    assert check_facts("drop 0.25", {"drop": 0.25}) is True
    assert check_facts("drop 0.5", {"drop": 0.25}) is False
    # bool True：label 出现（正向断言）
    assert check_facts("该商品有缺货风险", {"缺货风险": True}) is True
    assert check_facts("该商品无风险", {"缺货风险": True}) is False
    # bool False：label 不得出现（保守：答案不含正向断言）
    assert check_facts("商品不支持退货", {"可以退货": False}) is True
    assert check_facts("商品可以退货", {"可以退货": False}) is False

"""Phase 1（W4.1）测试：toolkit + fake LLM 接线 + 目录过滤（dryrun 范式 spike）。

- 自写 ScriptedFakeModel：GenericFakeChatModel（不支持 bind_tools）与 FakeListChatModel
  （responses 只收 str）都无法预设带 tool_calls 的 AIMessage，故按文档 W4.1 预案自写。
- 通过 create_react_agent 验证：预设 tool_call → ToolNode 真执行工具（DB）→ 工具结果回喂。
- 目录过滤断言（无 DB）；错误语义断言（NOT_FOUND → error dict，不 raise）。
"""
from __future__ import annotations

import os
from typing import List, Sequence

os.environ.setdefault("LLM_MODE", "dryrun")

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.prebuilt import create_react_agent

from copilot.agent.toolkit import catalog_names, make_langchain_tool
from copilot.context import UserContext
from copilot.tools import GetInventory


class ScriptedFakeModel(BaseChatModel):
    """预设 AIMessage 序列的 fake；bind_tools 记录工具并返回副本（供 ToolNode 执行）。"""

    script: List[AIMessage]
    _i: int = 0
    bound_tools: List = []

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools, **kwargs):
        obj = self.model_copy(deep=True)
        obj.bound_tools = list(tools)
        return obj

    def _generate(self, messages: Sequence[BaseMessage], stop=None,
                  run_manager=None, **kwargs) -> ChatResult:
        i = self._i
        self._i += 1
        if i >= len(self.script):
            raise AssertionError(f"fake 消息用尽（{i}/{len(self.script)}）")
        return ChatResult(generations=[ChatGeneration(message=self.script[i])])


def _ctx() -> UserContext:
    return UserContext(user_id=1, role="operations", store_id=1)


# ---- 目录过滤（W1.4，无 DB）----

def test_catalog_unset_is_intersection():
    assert catalog_names("UNSET") == [
        "get_inventory", "get_order", "get_shipping_status",
        "search_business_knowledge", "analyze_fulfillment_delay", "check_return_eligibility"]


def test_catalog_operations_has_ops_only():
    names = catalog_names("OPERATIONS")
    assert "analyze_stockout_risk" in names
    assert "query_product_performance" in names
    assert len(names) == 10


def test_catalog_customer_service_no_ops_only():
    names = catalog_names("CUSTOMER_SERVICE")
    assert "analyze_stockout_risk" not in names
    assert "check_return_eligibility" in names
    assert len(names) == 6


# ---- W4.1：fake LLM + ToolNode 真执行（DB 依赖）----

def test_fake_llm_toolnode_executes_real_tool():
    tool = make_langchain_tool(GetInventory, _ctx)
    model = ScriptedFakeModel(script=[
        AIMessage(content="", tool_calls=[{
            "name": "get_inventory", "args": {"sku_code": "SKU_01_STOCKOUT_01"},
            "id": "c1", "type": "tool_call"}]),
        AIMessage(content="库存查询完成"),
    ])
    agent = create_react_agent(model, [tool])
    out = agent.invoke({"messages": [{"role": "user", "content": "查 SKU_01_STOCKOUT_01 库存"}]})
    tool_msgs = [m for m in out["messages"] if m.type == "tool"]
    assert tool_msgs, "应有 ToolMessage（工具真执行）"
    content = tool_msgs[-1].content
    assert "available_qty" in content, f"工具应真执行并返回库存字段: {content}"
    # D11：内部 id/store_id/customer_id/user_id 已投影（get_inventory 无 id，store_id 被删）
    assert "store_id" not in content


def test_tool_wrapper_not_found_error_semantics():
    tool = make_langchain_tool(GetInventory, _ctx)
    res = tool.invoke({"sku_code": "SKU_99_DOES_NOT_EXIST"})
    assert res["error_code"] == "NOT_FOUND", res
    assert "error_detail" in res

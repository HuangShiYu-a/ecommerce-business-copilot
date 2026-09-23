"""共享 fake LLM（W4.1 自写；GenericFakeChatModel 不支持 bind_tools，FakeListChatModel
responses 只收 str，均无法预设带 tool_calls 的 AIMessage，故按文档预案自写）。

ScriptedFakeModel 按序产出预设 AIMessage（可带 tool_calls），bind_tools 记录工具并返回副本，
供 ToolNode / ReAct 图真执行工具。
"""
from __future__ import annotations

from typing import List, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedFakeModel(BaseChatModel):
    """预设 AIMessage 序列的 fake；bind_tools 记录工具并返回副本。"""

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


def tool_call(name: str, args: dict, tid: str = "c1") -> dict:
    """构造 AIMessage.tool_calls 元素。"""
    return {"name": name, "args": args, "id": tid, "type": "tool_call"}

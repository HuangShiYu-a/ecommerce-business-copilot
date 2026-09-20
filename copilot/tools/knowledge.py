"""T-K-01 search_business_knowledge：知识/规则检索（Knowledge，只读）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..rag import search_knowledge
from ..tool import Tool, ok, register_tool


@register_tool
class SearchBusinessKnowledge(Tool):
    tool_id = "T-K-01"
    name = "search_business_knowledge"
    category = "Knowledge"
    description = "检索业务知识/规则（退货政策/物流时效/SOP/话术等），返回命中的规则片段"
    risk = "LOW"
    read_write = "read"
    allowed_roles = ("customer_service", "operations")

    class Input(BaseModel):
        query: str = Field(description="检索问题，如「耳机可以退货吗」「无理由退货窗口几天」")
        top_k: int = Field(default=5, ge=1, le=10)
        threshold: float = Field(default=0.5, ge=0, le=1)

    input_model = Input

    def run(self, ctx, query, top_k=5, threshold=0.5, **kw):
        results = search_knowledge(self.conn, query, ctx.store_id, top_k=top_k, threshold=threshold)
        return ok({"query": query, "results": results})

"""R4 测试：pgvector 检索 + T-K-01（依赖 PG 数据 + Ollama bge-m3 运行）。

验证：相关命中 / R1 过期文档过滤 / store 隔离 / T-K-01 工具 / Effective Catalog 注册。
"""
import pytest

from copilot.context import ops_ctx
from copilot.db import connect
from copilot.rag import search_knowledge
from copilot.tool import run_tool


def _top_titles(results):
    return [r["title"] for r in results]


def test_retrieval_relevant():
    with connect() as conn:
        r = search_knowledge(conn, "耳机可以退货吗", 1, top_k=5)
    assert r, "应命中结果"
    assert "店铺补充售后政策（STORE_01）" in _top_titles(r[:2])   # KD-AS-04 店规 R3 载体


def test_retrieval_return_window():
    with connect() as conn:
        r = search_knowledge(conn, "无理由退货窗口几天", 1, top_k=5)
    titles = _top_titles(r)
    assert "七日无理由退货底线" in titles   # KD-AS-01


def test_r1_expired_filtered():
    """R1：已过期文档（LG-02 v1）不参与检索；只有现行版本（LG-03）。"""
    with connect() as conn:
        r = search_knowledge(conn, "物流时效承诺政策", 1, top_k=10)
    titles = _top_titles(r)
    assert not any("已废止" in t for t in titles)
    assert "物流时效承诺政策 v2.0（现行）" in titles


def test_store_isolation():
    """store 隔离：store 专属文档仅命中对应 store；全局文档两者可见。"""
    with connect() as conn:
        r2 = search_knowledge(conn, "耳机可以退货吗", 2, top_k=10)
    # STORE_02 不应命中 STORE_01 专属店规（AS-04 store_id=STORE_01）
    assert not any("店铺补充售后政策" in t for t in _top_titles(r2))


def test_tk01_tool():
    res = run_tool("T-K-01", ops_ctx(1), query="无理由退货窗口几天")
    assert res.ok, res
    assert res.data["results"] and res.data["query"]


def test_catalog_has_tk01():
    from copilot.tool import effective_catalog
    ids = {t["tool_id"] for t in effective_catalog("customer_service")}
    assert "T-K-01" in ids   # 客服可用知识检索

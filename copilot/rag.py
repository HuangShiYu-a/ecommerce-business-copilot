"""RAG 检索（R4）：bge-m3 查询向量化 + pgvector 余弦检索 + R1 生命周期过滤。

口径（RAG v1.0）：
- R1：仅当前有效文档参与检索（status=ACTIVE + effective 半开区间）。
- store 隔离：文档 store_id=0（全局）或 = 请求 store_id。
- 阈值/top-k：默认 0.5 / 5（Q3，黄金问答后标定）。
"""
from __future__ import annotations

import requests

from .config import AS_OF_DATE
from .db import query

OLLAMA_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "bge-m3"


def embed_texts(texts: list[str]) -> list[list[float]]:
    resp = requests.post(OLLAMA_URL, json={"model": EMBED_MODEL, "input": texts}, timeout=60)
    resp.raise_for_status()
    return resp.json()["embeddings"]


def _vec_str(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def search_knowledge(conn, query_text: str, store_id: int,
                     top_k: int = 5, threshold: float = 0.5,
                     as_of: str = AS_OF_DATE) -> list[dict]:
    """向量检索知识 chunk（R1 生命周期 + store 隔离过滤）。"""
    vec = embed_texts([query_text])[0]
    qv = _vec_str(vec)
    rows = query(conn, """
        SELECT c.id, c.document_id, d.title, c.section, c.content,
               1 - (c.embedding <=> %s::vector) AS similarity
        FROM knowledge.knowledge_chunks c
        JOIN knowledge.knowledge_documents d ON d.id = c.document_id
        WHERE c.embedding IS NOT NULL
          AND d.status = 'ACTIVE'
          AND d.effective_from <= %s::date
          AND (d.effective_to IS NULL OR %s::date < d.effective_to)
          AND (d.store_id = 0 OR d.store_id = %s)
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """, (qv, as_of, as_of, store_id, qv, top_k))
    out = []
    for r in rows:
        sim = round(float(r["similarity"]), 4)
        if sim < threshold:
            break
        out.append({**r, "similarity": sim})
    return out

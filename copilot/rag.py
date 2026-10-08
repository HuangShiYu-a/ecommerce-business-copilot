"""RAG 检索与规则消解（R4/R5，RAG v1.0）。

- R1：仅当前有效文档参与检索（SQL 半开区间）。
- R2：scope 过滤（业务上下文 category/tags 与 chunk scope 比对，Python 后滤）。
- R3/R4：候选冲突时按权威层消解（legal > platform > store）。
- R5：无法消解 → RULE_CONFLICT。
"""
from __future__ import annotations

import json
import os
import re

import requests

from .config import AS_OF_DATE
from .db import query

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/embed")
EMBED_MODEL = "bge-m3"
LAYER_PRIORITY = {"legal": 3, "platform": 2, "store": 1}


def embed_texts(texts: list[str]) -> list[list[float]]:
    resp = requests.post(OLLAMA_URL, json={"model": EMBED_MODEL, "input": texts}, timeout=60)
    resp.raise_for_status()
    return resp.json()["embeddings"]


def _vec_str(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def _scope_match(chunk_scope: dict, scope: dict | None) -> bool:
    """R2：业务上下文与 chunk scope 比对。scope = {category_code, tags:[..]}。"""
    cs = chunk_scope or {}
    tags = set((scope or {}).get("tags", []))
    # exclude_tags：上下文命中 → 排除
    if tags & set(cs.get("exclude_tags", [])):
        return False
    # include_tags 非空：仅适用特定标签；无上下文或未命中 → 不适用（CONF 对仅在带 tag 场景出现）
    inc = set(cs.get("include_tags", []))
    if inc and not (tags & inc):
        return False
    # category_codes 非空且上下文类目未命中 → 排除
    cats = set(cs.get("category_codes", []))
    cc = (scope or {}).get("category_code")
    if cats and cc and cc not in cats:
        return False
    # L5：类目未知时，仅排除纯类目专属规则（无 tag 激活通道），防类目规则外溢到未知类目；
    # 带 tag 激活的规则（如 CONF 对）已通过上方 include_tags 检查，不误伤（类目未知仍经 tag 生效）
    if cats and not cc and not inc:
        return False
    return True


def _select_rows(rows, threshold: float, scope: dict | None) -> list[dict]:
    """按阈值 + scope 过滤候选行（R2 Python 后滤；相似度降序，低于阈值即断）。"""
    out = []
    for r in rows:
        sim = round(float(r["similarity"]), 4)
        if sim < threshold:
            break
        meta = r["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        if not _scope_match(meta.get("scope", {}) if meta else {}, scope):
            continue
        out.append({
            "id": r["id"], "document_id": r["document_id"], "title": r["title"],
            "layer": r["layer"], "section": r["section"], "content": r["content"],
            "similarity": sim,
        })
    return out


def search_knowledge(conn, query_text: str, store_id: int,
                     top_k: int = 5, threshold: float = 0.5,
                     as_of: str = AS_OF_DATE, scope: dict | None = None) -> list[dict]:
    """向量检索知识 chunk（R1 + R2 过滤）。"""
    vec = embed_texts([query_text])[0]
    qv = _vec_str(vec)

    def _query(k: int):
        return query(conn, """
            SELECT c.id, c.document_id, d.title, d.layer, c.section, c.content, c.metadata,
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
        """, (qv, as_of, as_of, store_id, qv, k))

    out = _select_rows(_query(top_k), threshold, scope)
    # L5：scope 后滤可能漏掉相关低分文档——带 scope 且无命中时扩大召回重查一次
    if scope and not out:
        out = _select_rows(_query(top_k * 4), threshold, scope)
    return out


_RETURN_WINDOW_RE = re.compile(r"(\d+)\s*日")


def _claim(text: str) -> tuple[str, str] | None:
    """抽取已知规则条款声明：(term, value)。当前仅退货窗口。"""
    m = _RETURN_WINDOW_RE.search(text)
    if m and ("窗口" in text or "退货" in text or "可退" in text):
        return ("return_window", f"{m.group(1)}日")
    return None


def resolve_rules(conn, query_text: str, store_id: int,
                  top_k: int = 8, threshold: float = 0.5,
                  scope: dict | None = None) -> dict:
    """检索 + 冲突消解（R3/R4/R5）。"""
    rows = search_knowledge(conn, query_text, store_id, top_k=top_k, threshold=threshold, scope=scope)
    # 分组：term -> value -> [(layer, title)]
    claims: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        c = _claim(r["content"])
        if c:
            claims.setdefault(c[0], {}).setdefault(c[1], []).append(
                {"layer": r["layer"], "title": r["title"], "similarity": r["similarity"]})

    conflicts = []
    resolved: dict[str, str] = {}
    for term, values in claims.items():
        if len(values) <= 1:
            if values:
                resolved[term] = next(iter(values))
            continue
        # R4：按值取最高权威层；最高层出现多个值 → R5 冲突
        by_layer = {v: max(LAYER_PRIORITY.get(d["layer"], 0) for d in ds) for v, ds in values.items()}
        top_layer = max(by_layer.values())
        top_values = [v for v, l in by_layer.items() if l == top_layer]
        if len(top_values) > 1:
            conflicts.append({"term": term, "values": top_values,
                              "reason": "RULE_CONFLICT", "candidates": values})
        else:
            # 最高权威层唯一 → R4 消解（保留其值，不冲突）
            resolved[term] = top_values[0]

    if conflicts:
        return {"status": "RULE_CONFLICT", "conflicts": conflicts, "results": rows}
    return {"status": "resolved", "results": rows, "resolved": resolved}

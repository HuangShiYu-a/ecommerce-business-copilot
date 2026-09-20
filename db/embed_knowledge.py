"""Knowledge embedding 生成与填充（R3）：Ollama bge-m3 → knowledge_chunks.embedding。

用法：python db/embed_knowledge.py [--batch 32] [--dry-run]
前提：Ollama 服务运行（ollama serve）+ bge-m3 已下载；dev 数据已导入（23 篇/82 chunks）。
Q1 定案：bge-m3（本地，1024 维）；embedding 列已 ALTER 为 vector(1024)。
"""
from __future__ import annotations

import argparse
import sys

import psycopg2
import requests

# 与 copilot/config.py 一致（独立脚本运行，避免包路径依赖）
DB_DSN = "postgresql://ec:ec_secret@localhost:5434/ec_copilot"
OLLAMA_URL = "http://localhost:11434/api/embed"
MODEL = "bge-m3"


def embed_batch(texts: list[str], batch: int) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        chunk = texts[i:i + batch]
        resp = requests.post(OLLAMA_URL, json={"model": MODEL, "input": chunk}, timeout=120)
        resp.raise_for_status()
        out.extend(resp.json()["embeddings"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, content FROM knowledge.knowledge_chunks
                WHERE embedding IS NULL ORDER BY id
            """)
            rows = cur.fetchall()
        if not rows:
            print("没有待嵌入的 chunk（embedding 均已填充）")
            return 0
        print(f"待嵌入 {len(rows)} 个 chunk（batch={args.batch}）")
        texts = [r[1] for r in rows]
        vectors = embed_batch(texts, args.batch)
        if args.dry_run:
            print(f"[dry-run] 首个向量维度={len(vectors[0])}（应 1024）")
            return 0
        with conn.cursor() as cur:
            for (cid, _), vec in zip(rows, vectors):
                vec_str = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
                cur.execute(
                    "UPDATE knowledge.knowledge_chunks SET embedding = %s::vector WHERE id = %s",
                    (vec_str, cid),
                )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM knowledge.knowledge_chunks WHERE embedding IS NOT NULL")
            done = cur.fetchone()[0]
            cur.execute("SELECT vector_dims(embedding) FROM knowledge.knowledge_chunks LIMIT 1")
            dim = cur.fetchone()[0]
        print(f"✅ 已填充 {done}/82 个 chunk，维度={dim}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

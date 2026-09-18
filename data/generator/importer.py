"""S3.5 Knowledge 导入器（P6）。

读取 data/knowledge/seed/ 的 10 篇 seed（K5 格式）+ 按 K3 契约映射到
knowledge_documents / knowledge_chunks canonical CSV。

- store_id：逻辑店 ID → Canonical 实际 id（STORE_01 → stores.csv 实际；0 哨兵保持 0）
- `## [section]` 标题 = chunk 边界；chunk_index 按出现顺序 1..n
- 文档 scope 复制进每 chunk metadata.scope（JSONB）
- section 按 K3 §4 注册表校验
- embedding：stub，不写 canonical（S4 导入时留空/后补，RAG Q-emb Open）
- 夹具容错：KD-AS-EXP-01（过期）、KD-AS-CONF-01/02（冲突对）为故意构造的 eval 夹具，正常导入
- doc_id 为 seed 稳定标识（非 DB 列），作为内部键保留，不入 CSV；doc 行按文件名序分配 id 1..10
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import yaml

from .config import GeneratorConfig
from .master import _write_csv
from .transactions import _read_csv

SEED_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "seed"

SECTION_REGISTRY = {
    "return", "non_returnable", "condition",
    "delivery", "delay",
    "health_dimensions", "replenishment_policy",
}

SECTION_RE = re.compile(r"^## \[([^\]]+)\]\s*(.*)")


def _iso_date(v) -> str:
    """seed 的日期（str 'YYYY-MM-DD' 或 date/datetime）→ 完整 ISO 时间戳；None/空 → ''。"""
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, date):
        return f"{v.isoformat()}T00:00:00"
    s = str(v).strip()
    if len(s) == 10:  # 'YYYY-MM-DD'
        return f"{s}T00:00:00"
    return s


def _parse_md(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path.name}: 缺少 YAML front matter")
    return yaml.safe_load(parts[1]), parts[2]


def _parse_chunks(body: str) -> list[dict]:
    chunks = []
    cur = None
    for line in body.splitlines():
        m = SECTION_RE.match(line)
        if m:
            if cur is not None:
                chunks.append(cur)
            cur = {"section": m.group(1), "content_lines": [line]}
        elif cur is not None:
            cur["content_lines"].append(line)
    if cur is not None:
        chunks.append(cur)

    out = []
    for c in chunks:
        content = "\n".join(c["content_lines"]).strip()
        if content:
            out.append({"section": c["section"], "content": content})
    return out


def generate_importer(cfg: GeneratorConfig, canonical_dir: Path, output_root: Path) -> list[dict]:
    stores = _read_csv(canonical_dir / "stores.csv")
    store_id_by_code = {s["store_code"]: int(s["id"]) for s in stores}

    seed_files = sorted(SEED_DIR.glob("KD-*.md"))
    if not seed_files:
        raise RuntimeError(f"未找到 Knowledge seed（{SEED_DIR}）")

    docs: list[dict] = []
    chunks: list[dict] = []
    for path in seed_files:
        front, body = _parse_md(path)
        store_key = str(front.get("store_id", "0"))
        store_id = 0 if store_key == "0" else store_id_by_code.get(store_key, 0)

        doc = {
            "id": len(docs) + 1,
            "store_id": store_id,
            "title": front["title"],
            "knowledge_type": front["knowledge_type"],
            "layer": front["layer"],
            "platform": front.get("platform", "default"),
            "source_uri": front.get("source_uri") or "",
            "status": front.get("status", "ACTIVE"),
            "version": str(front.get("version", "1.0")),
            "effective_from": _iso_date(front.get("effective_from")),
            "effective_to": _iso_date(front.get("effective_to")),
            "doc_id": front["doc_id"],   # 内部键，不入 CSV
        }
        docs.append(doc)

        scope = front.get("scope") or {}
        parsed = _parse_chunks(body)
        for i, c in enumerate(parsed, start=1):
            if c["section"] not in SECTION_REGISTRY:
                raise ValueError(f"{path.name}: section '{c['section']}' 不在注册表 {sorted(SECTION_REGISTRY)}")
            chunks.append({
                "id": len(chunks) + 1,
                "document_id": doc["id"],
                "chunk_index": i,
                "content": c["content"],
                "section": c["section"],
                "metadata": json.dumps({"scope": scope}, ensure_ascii=False),
                "doc_id": doc["doc_id"],  # 内部键
            })

    specs = {
        "knowledge_documents": (
            ["id", "store_id", "title", "knowledge_type", "layer", "platform",
             "source_uri", "status", "version", "effective_from", "effective_to"],
            docs,
        ),
        "knowledge_chunks": (
            ["id", "document_id", "chunk_index", "content", "section", "metadata"],
            chunks,
        ),
    }
    tables = []
    for name, (headers, rows) in specs.items():
        _write_csv(canonical_dir / f"{name}.csv", headers, rows)
        tables.append({"table": name, "rows": len(rows)})
    return tables

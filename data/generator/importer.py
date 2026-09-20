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

SEED_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "seed" / "md"

SECTION_REGISTRY = {
    "return", "non_returnable", "condition",
    "delivery", "delay",
    "health_dimensions", "replenishment_policy",
    "slow_moving", "special",   # R1.2：KD-OP-03 / KD-AS-09
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


def _emit_doc(docs, chunks, doc_meta: dict, scope: dict, blocks) -> int:
    """统一产出一篇文档的 doc 行 + chunk 行（md 与多格式共用）。"""
    store_key = str(doc_meta.get("store_id", "0"))
    store_id = 0 if store_key == "0" else doc_meta.get("_store_by_code", {}).get(store_key, 0)
    doc = {
        "id": len(docs) + 1,
        "store_id": store_id,
        "title": doc_meta["title"],
        "knowledge_type": doc_meta["knowledge_type"],
        "layer": doc_meta["layer"],
        "platform": doc_meta.get("platform", "default"),
        "source_uri": doc_meta.get("source_uri") or "",
        "status": doc_meta.get("status", "ACTIVE"),
        "version": str(doc_meta.get("version", "1.0")),
        "effective_from": _iso_date(doc_meta.get("effective_from")),
        "effective_to": _iso_date(doc_meta.get("effective_to")),
        "doc_id": doc_meta["doc_id"],
    }
    docs.append(doc)
    for i, block in enumerate(blocks, start=1):
        content = "\n".join(block.content).strip()
        if not content:
            continue
        chunks.append({
            "id": len(chunks) + 1,
            "document_id": doc["id"],
            "chunk_index": i,
            "content": content,
            "section": block.text,   # md=[tag]；多格式=标题文本（slug 语义）
            "metadata": json.dumps({"scope": scope}, ensure_ascii=False),
            "doc_id": doc["doc_id"],
        })
    return doc["id"]


def _import_multiformat(docs, chunks, store_id_by_code) -> None:
    """读取 manifest 中 format+path 的多格式文档 → parsers → 统一结构块 → chunk。"""
    from .parsers import PARSERS

    manifest_path = SEED_DIR.parent / "manifest.yaml"
    if not manifest_path.exists():
        return
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("documents", []):
        if "format" not in entry or "path" not in entry:
            continue
        fmt = entry["format"]
        if fmt not in PARSERS:
            raise ValueError(f"未知格式 {fmt}: {entry['doc_id']}")
        blocks = PARSERS[fmt](SEED_DIR.parent / entry["path"])
        meta = {**entry, "_store_by_code": store_id_by_code}
        scope = entry.get("scope") or {}
        _emit_doc(docs, chunks, meta, scope, blocks)


def generate_importer(cfg: GeneratorConfig, canonical_dir: Path, output_root: Path) -> list[dict]:
    stores = _read_csv(canonical_dir / "stores.csv")
    store_id_by_code = {s["store_code"]: int(s["id"]) for s in stores}

    seed_files = sorted(SEED_DIR.glob("KD-*.md"))
    if not seed_files:
        raise RuntimeError(f"未找到 Knowledge seed（{SEED_DIR}）")

    docs: list[dict] = []
    chunks: list[dict] = []

    # 路径 1：md（frontmatter + ## [section]）
    from .parsers import Block
    for path in seed_files:
        front, body = _parse_md(path)
        scope = front.get("scope") or {}
        parsed = _parse_chunks(body)
        blocks = [
            Block(level=1, text=c["section"], content=c["content"].splitlines())
            for c in parsed if c["section"] in SECTION_REGISTRY
        ]
        _emit_doc(docs, chunks, {**front, "_store_by_code": store_id_by_code}, scope, blocks)

    # 路径 2：多格式（manifest 元数据 + parsers 结构块）
    _import_multiformat(docs, chunks, store_id_by_code)

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

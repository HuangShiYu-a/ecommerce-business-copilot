"""P6 / S3.5 Knowledge 导入器门禁测试：12 篇 md / 34 chunks / store_id 映射 / 切块与 section / scope 复制 / 夹具容错 / 生命周期窗。"""
import csv
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from data.generator.config import load_config
from data.generator.generate import generate

AS_OF = date(2026, 9, 17)


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture()
def imp(tmp_path):
    cfg = load_config("dev")
    generate(cfg, output_root=tmp_path)
    canonical = tmp_path / "dev" / "canonical"
    return {
        "canonical": canonical,
        "docs": _read_csv(canonical / "knowledge_documents.csv"),
        "chunks": _read_csv(canonical / "knowledge_chunks.csv"),
        "stores": _read_csv(canonical / "stores.csv"),
    }


def test_tables_created_and_counts(imp):
    assert (imp["canonical"] / "knowledge_documents.csv").exists()
    assert (imp["canonical"] / "knowledge_chunks.csv").exists()
    assert len(imp["docs"]) == 12
    assert len(imp["chunks"]) == 34
    # doc_id 稳定序（KD-AS-01..CONF-02）
    assert imp["docs"][0]["title"] == "七日无理由退货底线"


def test_store_id_mapping(imp):
    store1_id = next(s["id"] for s in imp["stores"] if s["store_code"] == "STORE_01")
    for d in imp["docs"]:
        # 全局（legal/platform）→ 0；店铺 → STORE_01 实际 id
        if d["layer"] in ("legal", "platform"):
            assert d["store_id"] == "0", d
        else:
            assert d["store_id"] == store1_id, d


def test_chunk_split_and_sections(imp):
    # chunk 数分布匹配 seed（原 10 篇 4,3,4,4,1,1,1,2,4,4 + OP-03:2 + AS-09:4）；section 在注册集；index 顺序
    from data.generator.importer import SECTION_REGISTRY
    counts = {}
    for c in imp["chunks"]:
        counts[c["document_id"]] = counts.get(c["document_id"], 0) + 1
        assert c["section"] in SECTION_REGISTRY
        assert int(c["chunk_index"]) == counts[c["document_id"]]
    assert sorted(counts.values()) == sorted([4, 3, 4, 4, 1, 1, 1, 2, 4, 4, 2, 4])
    assert len(counts) == 12


def test_scope_copied_to_chunks(imp):
    id_by_title = {d["title"]: d["id"] for d in imp["docs"]}
    as04 = id_by_title["店铺补充售后政策（STORE_01）"]          # KD-AS-04 exclude
    conf_ids = {d["id"] for d in imp["docs"] if "冲突测试店规" in d["title"]}
    for c in imp["chunks"]:
        meta = json.loads(c["metadata"])
        assert "scope" in meta
        if c["document_id"] == as04:
            assert "apparel-conflict-test" in meta["scope"]["exclude_tags"]
        if c["document_id"] in conf_ids:
            assert meta["scope"]["include_tags"] == ["apparel-conflict-test"]


def test_fixture_tolerance(imp):
    """EXP/CONF 夹具正常导入，不报错；EXP 生命周期正确（effective_to < as_of）。"""
    by_title = {d["title"]: d for d in imp["docs"]}
    exp = by_title["退货申请时限（已失效）"]
    assert exp["status"] == "ACTIVE"
    assert datetime.fromisoformat(exp["effective_to"]).date() < AS_OF
    # 冲突对存在且 ACTIVE 长期有效
    conf = [d for d in imp["docs"] if "冲突测试店规" in d["title"]]
    assert len(conf) == 2
    for d in conf:
        assert d["effective_to"] == ""


def test_lifecycle_window(imp):
    """P0-Core ACTIVE 在 as_of 窗内；EXP 不在窗内（时间分支）。"""
    def in_window(d):
        ef = datetime.fromisoformat(d["effective_from"]).date()
        if d["effective_to"]:
            et = datetime.fromisoformat(d["effective_to"]).date()
        else:
            et = None
        return d["status"] == "ACTIVE" and ef <= AS_OF and (et is None or AS_OF < et)

    inw = {d["title"] for d in imp["docs"] if in_window(d)}
    assert "七日无理由退货底线" in inw
    assert "退货申请时限（已失效）" not in inw


def test_no_embedding_column_stub(imp):
    """embedding stub：chunks CSV 不含 embedding 列（S4 导入时留空/后补）。"""
    assert "embedding" not in imp["chunks"][0]

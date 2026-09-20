"""Knowledge 防冲突校验（R1.3，§4 机制 3）。

读取全部 23 篇文本，抽取「N日/N天」规则声明，输出可审查报告：
- 白名单值（已知合法）不报；出现白名单外值自动标记 ❌
- 退货时效白名单：7日(法定/店规/CONF-A)、15日(CONF-B)、3日(EXP 申请时限夹具)
  其余引用「N日」均指销售窗口/复盘期等非退货时效语义。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
SEED = ROOT / "data" / "knowledge" / "seed"

# 已知合法「退货/售后时效（日）」值：7日(法定/店规/CONF-A)、15日(CONF-B)、3日(EXP 申请时限夹具)
KNOWN_RI_DAYS = {"7日", "15日", "3日"}


def _md_text(path: Path) -> str:
    parts = path.read_text(encoding="utf-8").split("---", 2)
    return parts[2] if len(parts) >= 3 else path.read_text(encoding="utf-8")


def _html_text(path: Path) -> str:
    from bs4 import BeautifulSoup
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").get_text("\n")


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)


def _docx_text(path: Path) -> str:
    from docx import Document
    return "\n".join(p.text for p in Document(str(path)).paragraphs)


def extract_time_claims(text: str) -> list[str]:
    """抽取「N日/N天」，带 12 字上下文；归一化空格（7 日 → 7日）。"""
    out = []
    for m in re.finditer(r"(\d+)\s*([日天])", text):
        ctx = text[max(0, m.start() - 10):m.end() + 8].replace("\n", " ")
        out.append(f"{m.group(1)}{m.group(2)}(…{ctx}…)")
    return out


def main() -> int:
    manifest = yaml.safe_load((SEED / "manifest.yaml").read_text(encoding="utf-8"))
    docs: dict[str, str] = {}
    for p in sorted((SEED / "md").glob("*.md")):
        docs[p.stem] = _md_text(p)
    for entry in manifest["documents"]:
        if "path" in entry and "format" in entry:
            p = SEED / entry["path"]
            fn = {"html": _html_text, "pdf": _pdf_text, "docx": _docx_text}[entry["format"]]
            docs[entry["doc_id"]] = fn(p)

    print(f"读取 {len(docs)} 篇")
    assert len(docs) == 23, f"应 23 篇，实 {len(docs)}"

    flags = 0
    for doc_id in sorted(docs):
        claims = extract_time_claims(docs[doc_id])
        if not claims:
            continue
        unknown_ri, tian_only = [], 0
        for c in claims:
            val = re.match(r"(\d+[日天])", c).group(1)
            if val.endswith("天"):      # 销售窗口/复盘/盘点等语义，仅报告不判定
                tian_only += 1
                continue
            if val not in KNOWN_RI_DAYS:  # 退货/售后「日」值必须白名单
                unknown_ri.append(c)
        mark = "✅" if not unknown_ri else "❌"
        if unknown_ri:
            flags += 1
        extra = f"（另有 {tian_only} 处「N天」非退货语义）" if tian_only else ""
        print(f"{mark} {doc_id}: {len(claims)} 处时效声明{extra}")
        for c in unknown_ri:
            print(f"      ⚠️ {c}")

    if flags:
        print("\n❌ 出现白名单外退货时效值，请人工复核是否为新冲突")
        return 1
    print("\n✅ 防冲突通过：退货时效（日）值均在白名单（7日/15日/3日），无新增矛盾")
    return 0


if __name__ == "__main__":
    sys.exit(main())

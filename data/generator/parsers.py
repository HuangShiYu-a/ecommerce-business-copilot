"""多格式知识解析器（R2，§7.1 切分细则）。

统一输出「结构块」：Block(level, heading, content_lines)。
- HTML：h1-h3 为标题层级，p/table 为内容
- DOCX：Heading 样式为标题，段落为内容
- PDF：PyMuPDF(fitz) 字号启发式——reportlab 生成字号：标题 16 / 节标题 12 / 正文 10.5；
  标题不可靠时退化段落级切块（manifest 声明章节）
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Block:
    level: int          # 0=标题 1=节标题 2=小节 …；正文=-1
    text: str
    content: list[str] = field(default_factory=list)


def _flush(cur: Block | None, out: list[Block]) -> None:
    if cur is not None:
        cur.content = [l for l in cur.content if l.strip()]
        if cur.content:
            out.append(cur)


def _blocks_from(chunks: list[tuple[int, str]]) -> list[Block]:
    """把 (level, text) 流组装成 Block；正文行挂到最近标题。"""
    out: list[Block] = []
    cur: Block | None = None
    for level, text in chunks:
        if level >= 0:  # 标题
            _flush(cur, out)
            cur = Block(level=level, text=text.strip())
        else:           # 正文
            if cur is None:
                continue
            cur.content.append(text)
    _flush(cur, out)
    return out


def parse_html(path) -> list[Block]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    chunks: list[tuple[int, str]] = []
    for el in soup.find_all(["h1", "h2", "h3", "p", "table"]):
        lvl = {"h1": 0, "h2": 1, "h3": 2}.get(el.name, -1)
        if el.name == "table":
            text = " | ".join(c.get_text(" ", strip=True) for c in el.find_all(["th", "td"]))
            chunks.append((-1, text))
        elif el.name == "p":
            chunks.append((-1, el.get_text(" ", strip=True)))
        else:
            chunks.append((lvl, el.get_text(" ", strip=True)))
    return _blocks_from(chunks)


def parse_docx(path) -> list[Block]:
    from docx import Document

    doc = Document(str(path))
    chunks: list[tuple[int, str]] = []
    for p in doc.paragraphs:
        if not p.text.strip():
            continue
        style = (p.style.name or "").lower()
        lvl = -1
        if style.startswith("heading") or style.startswith("title"):
            lvl = 0 if style.startswith("title") else int(style.replace("heading ", "") or "1")
        chunks.append((lvl if lvl >= 0 else -1, p.text))
    return _blocks_from(chunks)


# reportlab 生成字号：标题 16 / 节标题 12 / 正文 10.5（knowledge_doc_gen.py）
_TITLE_SIZE, _HEAD_SIZE, _BODY_SIZE = 16.0, 12.0, 10.5


def parse_pdf(path) -> list[Block]:
    import fitz  # PyMuPDF

    doc = fitz.open(str(path))
    chunks: list[tuple[int, str]] = []
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                size = max(s["size"] for s in spans)
                text = "".join(s["text"] for s in spans).strip()
                if size >= _TITLE_SIZE - 1:
                    chunks.append((0, text))
                elif size >= _HEAD_SIZE - 1:
                    chunks.append((1, text))
                else:
                    chunks.append((-1, text))
    doc.close()
    if not any(lvl >= 0 for lvl, _ in chunks):
        # 退化：无标题 → 整篇一个块（manifest 声明章节）
        all_text = "\n".join(t for _, t in chunks)
        return [Block(level=0, text="document", content=[all_text])]
    return _blocks_from(chunks)


PARSERS = {"html": parse_html, "docx": parse_docx, "pdf": parse_pdf}

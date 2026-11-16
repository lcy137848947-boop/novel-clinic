# -*- coding: utf-8 -*-
"""按文档顺序抽取 docx 的段落与表格为纯文本。"""
from __future__ import annotations

import sys
from pathlib import Path

import docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

sys.stdout.reconfigure(encoding="utf-8")


def iter_blocks(parent):
    """按 body 顺序产出 Paragraph / Table。"""
    body = parent.element.body if isinstance(parent, DocxDocument) else parent._element
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, parent)
        elif child.tag.endswith("}tbl"):
            yield Table(child, parent)


def extract(src: Path, dst: Path) -> None:
    document = docx.Document(str(src))
    lines: list[str] = []
    stats = {"paragraphs": 0, "tables": 0, "table_rows": 0}
    for block in iter_blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                style = (block.style.name or "").strip()
                prefix = ""
                if style.lower().startswith("heading") or style.startswith("标题"):
                    prefix = "#" * min(6, int(style[-1]) if style[-1].isdigit() else 2) + " "
                lines.append(prefix + text)
                stats["paragraphs"] += 1
        else:
            rows: list[list[str]] = []
            for row in block.rows:
                cells = []
                seen = set()
                for cell in row.cells:
                    key = id(cell._tc)
                    if key in seen:
                        continue
                    seen.add(key)
                    cells.append(cell.text.strip().replace("\n", " / "))
                rows.append(cells)
            if rows:
                stats["tables"] += 1
                stats["table_rows"] += len(rows)
                lines.append("")
                lines.append("[表格]")
                for cells in rows:
                    lines.append(" | ".join(cells))
                lines.append("[/表格]")
                lines.append("")
    text = "\n".join(lines)
    dst.write_text(text, encoding="utf-8")
    print(f"paragraphs={stats['paragraphs']} tables={stats['tables']} rows={stats['table_rows']} chars={len(text)}")
    print(f"saved: {dst}")


if __name__ == "__main__":
    extract(Path(sys.argv[1]), Path(sys.argv[2]))

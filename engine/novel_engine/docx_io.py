# -*- coding: utf-8 -*-
"""docx 读写（中文小说排版：宋体小四、1.5 倍行距、首行缩进、每章分页）。"""
from __future__ import annotations

import os
import re
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

DEFAULT_HEAD_RE = re.compile(r"^第[0-9一二三四五六七八九十百千]+章")

TITLE_FONT = "黑体"
BODY_FONT = "宋体"
SUBTITLE_FONT = "楷体"


def set_font(run, name: str, size: float, bold: bool = False):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    rf.set(qn("w:eastAsia"), name)
    rf.set(qn("w:ascii"), "Times New Roman")
    rf.set(qn("w:hAnsi"), "Times New Roman")


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_book(
    paragraphs: list[str],
    dst: str | Path,
    title: str,
    subtitle: str = "修订版",
    chapter_pattern: str = DEFAULT_HEAD_RE.pattern,
    front_matter: list[str] | None = None,
) -> dict:
    """把「章标题 + 正文段」列表写成 docx，返回写入统计。

    原子写：先写同目录 .tmp.docx，flush+fsync 后再 os.replace 覆盖目标，
    避免进程中途被杀时把主稿写成半个 ZIP。
    前置页写在标题/副标题之后、第一章之前；开头重复的书名/副标题不再重写一遍。
    """
    head_re = re.compile(chapter_pattern)
    heads = [i for i, t in enumerate(paragraphs) if head_re.match(t)]
    if not heads:
        raise ValueError("找不到章标题，无法写入 docx")

    doc = docx.Document()
    sec = doc.sections[0]
    sec.top_margin = sec.bottom_margin = Cm(2.5)
    sec.left_margin = sec.right_margin = Cm(2.8)
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(12)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(title), TITLE_FONT, 22, True)
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p2.add_run(subtitle), SUBTITLE_FONT, 12)
    doc.add_page_break()

    # 前置页开头若已是本稿书名/副标题（model.py 抓的 front_matter 就含这两段），
    # 前面已经写成标题页了，这里跳过对应段数，避免逐轮 apply 前置页翻倍。
    fm = [str(t) for t in (front_matter or [])]
    skip = 0
    if fm and fm[0].strip() == str(title).strip():
        skip = 1
        if len(fm) > 1 and str(subtitle).strip() and fm[1].strip() == str(subtitle).strip():
            skip = 2

    for text in fm[skip:]:
        if not str(text).strip():
            continue
        fp = doc.add_paragraph()
        fp.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        fp.paragraph_format.line_spacing = 1.5
        set_font(fp.add_run(text), BODY_FONT, 12)

    for k, hi in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(paragraphs)
        hp = doc.add_paragraph()
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        hp.paragraph_format.space_before = Pt(6)
        hp.paragraph_format.space_after = Pt(18)
        set_font(hp.add_run(paragraphs[hi]), TITLE_FONT, 15, True)
        for text in paragraphs[hi + 1 : end]:
            q = doc.add_paragraph()
            q.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            pf = q.paragraph_format
            pf.first_line_indent = Pt(24)
            pf.line_spacing = 1.5
            pf.space_before = Pt(0)
            pf.space_after = Pt(0)
            set_font(q.add_run(text), BODY_FONT, 12)
        if k < len(heads) - 1:
            doc.add_page_break()

    target = Path(dst)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + ".tmp" + target.suffix)
    doc.save(str(tmp))
    fd = os.open(str(tmp), os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, target)
    return {
        "paragraphs": len(paragraphs),
        "chapters": len(heads),
        "path": str(target),
        "sha256": _sha256(target),
        "front_matter": len(front_matter or []),
    }

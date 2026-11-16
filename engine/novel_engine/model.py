# -*- coding: utf-8 -*-
"""正文模型：docx / md / txt → 章 / 段 / 句 / 对话。"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SENT_RE = re.compile(r"[^。！？!?…]+(?:[。！？!?…]+[”’」』]?)?")
QUOTE_PAIRS = re.compile(r"“([^”]*)(?:”|$)|「([^」]*)(?:」|$)|‘([^’]*)(?:’|$)")
STRAIGHT_QUOTES = ('"', "'")


def cjk_count(text: str) -> int:
    return len(CJK_RE.findall(text))


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Paragraph:
    chapter: int            # 1-based 章序号
    index_in_chapter: int   # 0-based 章内段序（正文段，不含章标题）
    global_index: int       # 0-based 全书正文段序号（不含章标题与前置页）
    text: str


@dataclass
class Chapter:
    index: int              # 1-based
    title: str
    paragraphs: list[Paragraph] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)

    @property
    def cjk(self) -> int:
        return cjk_count(self.text)


@dataclass
class Book:
    title: str
    subtitle: str
    path: Path
    front_matter: list[str]
    chapters: list[Chapter]

    @property
    def paragraphs(self) -> list[Paragraph]:
        out: list[Paragraph] = []
        for ch in self.chapters:
            out.extend(ch.paragraphs)
        return out

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)

    @property
    def cjk(self) -> int:
        return cjk_count(self.text)

    def chapter(self, index: int) -> Chapter | None:
        for ch in self.chapters:
            if ch.index == index:
                return ch
        return None


def split_sentences(text: str) -> list[str]:
    """按中文句末标点切句，保留句末标点。"""
    pieces = [m.group(0).strip() for m in SENT_RE.finditer(text)]
    return [p for p in pieces if p]


def dialogue_spans(text: str) -> list[tuple[int, int]]:
    """返回对话区间（含引号），用于把叙述与对白分开。"""
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"“[^”]*”|「[^」]*」|‘[^’]*’", text):
        spans.append((m.start(), m.end()))
    return spans


def narration_segments(text: str) -> list[str]:
    """返回段落中所有非对话片段。"""
    spans = dialogue_spans(text)
    if not spans:
        return [text]
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        if start > cursor:
            out.append(text[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(text):
        out.append(text[cursor:])
    return [s for s in out if s.strip()]


def is_dialogue_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    spans = dialogue_spans(stripped)
    if not spans:
        return False
    covered = sum(e - s for s, e in spans)
    return covered >= len(stripped) * 0.8


def _read_docx(path: Path) -> list[str]:
    import docx  # python-docx

    d = docx.Document(str(path))
    return [p.text.strip() for p in d.paragraphs if p.text and p.text.strip()]


def _read_text(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8-sig")
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            s = s.lstrip("#").strip()
            if not s:
                continue
        lines.append(s)
    return lines


CN_NUM = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9}


def cn_to_int(text: str) -> int | None:
    """中文数字 → int（支持到千位；处理「二十一」「一百零八」这种）。"""
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total, section, number = 0, 0, 0
    units = {"十": 10, "百": 100, "千": 1000}
    for ch in text:
        if ch in CN_NUM:
            number = CN_NUM[ch]
        elif ch in units:
            unit = units[ch]
            section += (number or 1) * unit
            number = 0
        else:
            return None
    total = section + number
    return total or None


def chapter_no_from_title(title: str, pattern: str) -> int | None:
    m = re.match(pattern, title)
    if not m:
        return None
    raw = next((g for g in m.groups() if g), None)
    if raw is None:
        return None
    return cn_to_int(raw)


def load_book(
    path: str | Path,
    chapter_pattern: str = r"^第([0-9\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u96f6\u4e24]+)\u7ae0",
    front_title: str | None = None,
    front_subtitle: str | None = None,
    *,
    allow_single_chapter: bool = False,
) -> Book:
    """读取书稿。前置页（章标题之前的段落）会被记录但不计入正文。

    找不到章标题时默认抛错（静默降级成单章会让整本书的定位全错）。
    确实要读非小说文本（设定集等）时，显式传 allow_single_chapter=True。
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".docx":
        paras = _read_docx(p)
    elif suffix in {".md", ".txt", ".markdown"}:
        paras = _read_text(p)
    else:
        raise ValueError(f"不支持的稿子格式：{suffix}（目前支持 .docx / .md / .txt）")

    head_re = re.compile(chapter_pattern)
    heads = [i for i, t in enumerate(paras) if head_re.match(t)]

    if not heads:
        if not allow_single_chapter:
            raise ValueError(
                "找不到章标题（pattern=%r）：%s。如果是设定集/非小说文本，"
                "请显式传 allow_single_chapter=True。" % (chapter_pattern, p.name))
        return Book(
            title=front_title or p.stem,
            subtitle=front_subtitle or "",
            path=p,
            front_matter=paras,
            chapters=[Chapter(index=1, title=front_title or p.stem,
                              paragraphs=[Paragraph(1, j, j, t) for j, t in enumerate(paras)])],
        )

    title = front_title or (paras[0] if heads[0] > 0 else p.stem)
    subtitle = front_subtitle or (paras[1] if heads[0] > 1 else "")
    front = paras[: heads[0]]

    chapters: list[Chapter] = []
    global_idx = 0
    used: set[int] = set()
    for k, hi in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(paras)
        body = paras[hi + 1 : end]
        no = chapter_no_from_title(paras[hi], chapter_pattern)
        if no is None or no in used:
            no = k + 1
            while no in used:
                no += 1
        used.add(no)
        ch = Chapter(index=no, title=paras[hi])
        for j, text in enumerate(body):
            ch.paragraphs.append(Paragraph(no, j, global_idx, text))
            global_idx += 1
        chapters.append(ch)
    return Book(title=title, subtitle=subtitle, path=p, front_matter=front, chapters=chapters)


def iter_sentences(paragraphs: Iterable[Paragraph]):
    for para in paragraphs:
        for sent in split_sentences(para.text):
            yield para, sent

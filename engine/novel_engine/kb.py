# -*- coding: utf-8 -*-
"""P1 知识库设定集（通用）。

- sources/ 下放任意 .txt / .md / .docx；sync 解析成卡片（按标题切分）；
- 卡片带 authority（outline / worldview / extra）与 spoiler 标记；
- search：本地关键词检索（无向量库、离线可用）；
- context：按章节文本自动挑出相关设定卡，生成"续写/审稿上下文包"；
- 番外默认排除（spoiler），避免正文误用揭底信息。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .model import cjk_count, load_book
from .rules import load_project, load_rules
from .store import now_iso, read_json, write_json

KB_DIR = "kb"
SOURCES_DIR = "sources"
INDEX_FILE = "index.json"
META_FILE = "sources.json"

MD_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
CHAPTER_RE = re.compile(r"^\s*(第[0-9一二三四五六七八九十百零〇]+章.*?)\s*$")
CN_SECTION_RE = re.compile(r"^\s*([一二三四五六七八九十百零〇]+、\s*.+?)\s*$")
DEFAULT_META = {
    "大纲.txt": {"authority": "outline", "kind": "设定集", "spoiler": False},
    "知识库.txt": {"authority": "worldview", "kind": "世界观", "spoiler": False},
    "番外.txt": {"authority": "extra", "kind": "番外（剧透）", "spoiler": True},
}
AUTHORITY_LABEL = {"outline": "大纲", "worldview": "知识库", "extra": "番外", "book": "正文"}


def kb_root(project_dir: str | Path) -> Path:
    return Path(project_dir) / KB_DIR


def sources_dir(project_dir: str | Path) -> Path:
    return kb_root(project_dir) / SOURCES_DIR


def index_path(project_dir: str | Path) -> Path:
    return kb_root(project_dir) / INDEX_FILE


def _read_source(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        import docx

        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs if p.text and p.text.strip())
    return path.read_text(encoding="utf-8-sig")


def _source_meta(project_dir: Path, path: Path) -> dict:
    meta_file = read_json(kb_root(project_dir) / META_FILE, {}) or {}
    configured = meta_file.get(path.name) or {}
    base = dict(DEFAULT_META.get(path.name) or {"authority": "book", "kind": "资料", "spoiler": False})
    base.update(configured)
    if "spoiler" not in configured:
        base["spoiler"] = path.name.startswith("番外")
    return base


def _detect_parser(lines: list[str]) -> str:
    counts = {
        "md": sum(1 for line in lines if MD_RE.match(line)),
        "chapter": sum(1 for line in lines if CHAPTER_RE.match(line)),
        "cn": sum(1 for line in lines if CN_SECTION_RE.match(line)),
    }
    if counts["md"] >= 3:
        return "md"
    if counts["cn"] >= 3:
        return "cn"
    if counts["chapter"] >= 3:
        return "chapter"
    return "single"


def _split_cards(text: str, source: str) -> list[dict]:
    lines = text.splitlines()
    parser = _detect_parser(lines)
    cards: list[dict] = []
    title_stack: list[str] = []
    current_title = source
    current_path: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        content = "\n".join(buffer).strip()
        if not content and current_title == source:
            return
        cards.append({
            "title": current_title,
            "path": " / ".join(current_path) or current_title,
            "content": content,
        })
        buffer = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            buffer.append("")
            continue
        heading = None
        level = 0
        if parser == "md":
            m = MD_RE.match(line)
            if m:
                level = len(m.group(1))
                heading = m.group(2).strip()
        elif parser == "cn":
            m = CN_SECTION_RE.match(line)
            if m:
                heading = m.group(1).strip()
                level = 2
        elif parser == "chapter":
            m = CHAPTER_RE.match(line)
            if m:
                heading = m.group(1).strip()
                level = 2
        if heading:
            flush()
            if level == 1:
                current_path = [heading]
            else:
                current_path = current_path[: max(0, level - 1)] + [heading]
            current_title = heading
            continue
        buffer.append(line)
    flush()
    # 丢掉空卡片
    return [card for card in cards if card["content"].strip()]


def sync(project_dir: str | Path) -> dict:
    project_dir = Path(project_dir)
    root = kb_root(project_dir)
    src = sources_dir(project_dir)
    if not src.exists():
        raise FileNotFoundError(f"知识库来源目录不存在：{src}")
    files = sorted([p for p in src.iterdir() if p.is_file() and p.suffix.lower() in {".txt", ".md", ".docx"}])
    if not files:
        raise FileNotFoundError(f"知识库来源为空：{src}")

    cards: list[dict] = []
    sources: list[dict] = []
    for path in files:
        text = _read_source(path)
        meta = _source_meta(project_dir, path)
        parsed = _split_cards(text, path.stem)
        source_cards = 0
        for item in parsed:
            card_id = "kb-" + hashlib.sha1(f"{path.name}|{item['path']}|{item['content'][:200]}".encode("utf-8")).hexdigest()[:10]
            cards.append({
                "id": card_id,
                "source": path.name,
                "source_type": meta.get("kind"),
                "authority": meta.get("authority"),
                "spoiler": bool(meta.get("spoiler")),
                "title": item["title"],
                "path": item["path"],
                "content": item["content"],
                "chars": cjk_count(item["content"]),
            })
            source_cards += 1
        sources.append({
            "file": path.name,
            "kind": meta.get("kind"),
            "authority": meta.get("authority"),
            "spoiler": bool(meta.get("spoiler")),
            "chars": len(text),
            "cards": source_cards,
            "sha1": hashlib.sha1(path.read_bytes()).hexdigest()[:16],
        })

    index = {
        "schema": 1,
        "generated_at": now_iso(),
        "project": project_dir.name,
        "sources": sources,
        "cards": cards,
        "policy": {
            "authority_order": ["正文", "大纲（六类核心）", "知识库 / 番外"],
            "spoiler_policy": "番外卡片默认不进正文上下文；只能作「暗示」参考，不能揭底。",
            "conflict_rule": "正文优先；只有核心设定（力量体系/分级/人物身份/出场纪律）以大纲为准。",
        },
    }
    write_json(index_path(project_dir), index)
    return {
        "ok": True,
        "index": str(index_path(project_dir)),
        "cards": len(cards),
        "sources": sources,
        "spoiler_cards": sum(1 for c in cards if c["spoiler"]),
        "generated_at": index["generated_at"],
    }


def load_index(project_dir: str | Path, required: bool = True) -> dict:
    path = index_path(project_dir)
    data = read_json(path, None)
    if not data:
        if required:
            raise FileNotFoundError(f"知识库还没同步：{path}（先运行 kb sync）")
        return {"cards": [], "sources": [], "policy": {}}
    return data


def _terms(query: str) -> list[str]:
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", query or "")
    if not terms and query:
        terms = [ch for ch in query if ch.strip()]
    return terms


def search(project_dir: str | Path, query: str, limit: int = 8, include_spoilers: bool = False) -> dict:
    data = load_index(project_dir)
    terms = _terms(query)
    if not terms:
        return {"ok": True, "query": query, "terms": [], "results": []}
    results = []
    for card in data.get("cards", []):
        if card.get("spoiler") and not include_spoilers:
            continue
        content = card.get("content", "")
        title = card.get("title", "")
        score = 0
        hit_term = ""
        for term in terms:
            count = content.count(term)
            if count:
                score += min(count, 6) * (len(term) + 1)
                hit_term = hit_term or term
            if term in title:
                score += 8
        if not score:
            continue
        pos = content.find(hit_term) if hit_term else 0
        if pos < 0:
            pos = 0
        snippet = content[max(0, pos - 40) : pos + 100].replace("\n", " ")
        results.append({
            "id": card["id"],
            "title": card["title"],
            "path": card.get("path"),
            "source": card.get("source"),
            "authority": card.get("authority"),
            "spoiler": card.get("spoiler"),
            "score": score,
            "snippet": snippet,
        })
    results.sort(key=lambda item: item["score"], reverse=True)
    return {"ok": True, "query": query, "terms": terms, "results": results[: max(1, min(limit, 30))]}


def _entities(project_dir: Path) -> list[str]:
    data = read_json(project_dir / "rules" / "entities.json", {}) or {}
    out: list[str] = []
    for key, value in data.items():
        if key in ("version", "note"):
            continue
        if isinstance(value, list):
            out.extend(str(x) for x in value if x)
    seen = set()
    ordered = []
    for item in out:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def context(project_dir: str | Path, chapter: int, max_chars: int = 4000, include_spoilers: bool = False) -> dict:
    project_dir = Path(project_dir)
    cfg = load_project(project_dir)
    rules = load_rules(project_dir, cfg)
    book = load_book(cfg["_main_draft_path"], rules.chapter_pattern, cfg.get("title"), cfg.get("subtitle"))
    ch = book.chapter(chapter)
    if not ch:
        raise ValueError(f"没有第 {chapter} 章")
    text = ch.text
    entities = _entities(project_dir)
    counts = {name: text.count(name) for name in entities}
    keywords = [name for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True) if count > 0]
    # 章节标题里也常有关键词
    title_terms = [t for t in re.findall(r"[\u4e00-\u9fff]{2,}", ch.title) if t not in keywords]
    keywords.extend(title_terms[:4])

    data = load_index(project_dir)
    scored = []
    for card in data.get("cards", []):
        if card.get("spoiler") and not include_spoilers:
            continue
        content = card.get("content", "")
        score = 0
        matched = []
        for keyword in keywords:
            if keyword in content:
                score += min(content.count(keyword), 5) * (len(keyword) + 1)
                matched.append(keyword)
        if score:
            scored.append((score, matched, card))
    scored.sort(key=lambda item: item[0], reverse=True)

    picked = []
    used = 0
    for _, matched, card in scored:
        content = card.get("content", "")
        remain = max_chars - used
        if remain <= 200:
            break
        excerpt = content[:remain]
        picked.append({
            "id": card["id"],
            "title": card["title"],
            "path": card.get("path"),
            "source": card.get("source"),
            "authority": card.get("authority"),
            "spoiler": card.get("spoiler"),
            "matched_keywords": matched,
            "chars": cjk_count(excerpt),
            "content": excerpt,
        })
        used += cjk_count(excerpt)
        if len(picked) >= 12:
            break

    return {
        "ok": True,
        "chapter": chapter,
        "chapter_title": ch.title,
        "keywords": keywords[:16],
        "cards": picked,
        "chars": used,
        "policy": data.get("policy", {}),
        "note": "番外默认排除；如作者明确要求可 include_spoilers=true。机器只做关键词召回，语义取舍由人/AI 判断。",
        "generated_at": now_iso(),
    }


def list_cards(project_dir: str | Path, include_spoilers: bool = False) -> dict:
    data = load_index(project_dir)
    cards = [
        {k: card.get(k) for k in ("id", "title", "path", "source", "authority", "spoiler", "chars")}
        for card in data.get("cards", [])
        if include_spoilers or not card.get("spoiler")
    ]
    return {"ok": True, "cards": cards, "sources": data.get("sources", []), "policy": data.get("policy", {}), "count": len(cards)}

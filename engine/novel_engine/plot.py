# -*- coding: utf-8 -*-
"""P2 情节拼接（节拍卡）引擎。

- import：把作者的细纲 md 解析成节拍卡（做什么/开句/收句/要点/禁忌/目标字数）
- submit：接收 AI 按模板拆出的节拍 JSON，校验结构后落盘（"给剧情 → 拆几节"）
- validate：字数预算、禁忌词、设定暴露、重复句、章末钩子
- template：返回节拍 JSON Schema + 可直接给模型的 prompt

只做"拆/校验/落盘"，不自动写正文；正文仍由作者写或走 A.6 改写参考稿。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .model import Book, cjk_count, split_sentences
from .rules import load_project, load_rules
from .store import now_iso, read_json, write_json
from .scanners import hook_score

PLOT_DIR = "plot"
SOURCES = "sources"
DEFAULT_BEAT_CHARS = 450

HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")
BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
ESTIMATE_RE = re.compile(r"([0-9,]+)\s*[–\-~—]\s*([0-9,]+)\s*字")
BANNED_SINGLE = set("止分唤锚")


def plot_root(project_dir: str | Path) -> Path:
    return Path(project_dir) / PLOT_DIR


_UNSAFE_KEY_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_chapter_key(chapter_key: str | None) -> str:
    """章键会被当成文件名（plot/<章键>.json），必须挡住路径分隔符与 .. 。

    chapter_key 由调用方直接传入（Agent 工具 novel_plot / CLI --chapter-key），
    落盘与读取两处都要过一遍，否则 ../../x 能把 JSON 写到 plot/ 之外。
    """
    key = str(chapter_key or "").strip()
    if ".." in key or "/" in key or "\\" in key:
        raise ValueError(f"章键非法：{chapter_key!r} 含路径字符（/ \\ ..），只允许当文件名用的普通字符")
    key = _UNSAFE_KEY_RE.sub("", key).strip(" .")
    if not key:
        raise ValueError("章键非法：不能为空或只有空白/点号")
    return key


def _clean(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^>\s?", "", text)
    text = re.sub(r"^[-*]\s+", "", text)
    return text.strip()


def _parse_fields(lines: list[str]) -> dict:
    fields: dict[str, list[str]] = {}
    current = None
    for line in lines:
        m = FIELD_RE.match(line.strip())
        if m:
            current = m.group(1).strip()
            fields.setdefault(current, [])
            continue
        if current is not None:
            fields[current].append(line)
    out: dict[str, str | list[str]] = {}
    for key, value in fields.items():
        cleaned = [_clean(x) for x in value if x.strip()]
        if key in ("要点", "禁忌"):
            out[key] = [x for x in cleaned if x]
        else:
            out[key] = "\n".join(x for x in cleaned if x)
    return out


def _parse_table(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells or all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        if cells[0] in ("设定", "问", "章", "拍"):
            continue
        rows.append(cells)
    return rows


def import_outline(project_dir: str | Path, source: str | Path, chapter_key: str | None = None, title: str | None = None) -> dict:
    project_dir = Path(project_dir)
    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(f"细纲不存在：{src}")
    text = src.read_text(encoding="utf-8-sig")
    lines = text.splitlines()

    sections: list[dict] = []
    current = None
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            if current:
                sections.append(current)
            current = {"level": len(m.group(1)), "title": m.group(2).strip(), "lines": []}
        elif current is not None:
            current["lines"].append(line)
    if current:
        sections.append(current)

    estimate = ESTIMATE_RE.search(text)
    est_lo = int(estimate.group(1).replace(",", "")) if estimate else 0
    est_hi = int(estimate.group(2).replace(",", "")) if estimate else 0
    scene = ""
    beats: list[dict] = []
    settings: list[str] = []
    forbidden: list[str] = []
    combat: list[list[str]] = []

    for section in sections:
        name = section["title"]
        if "场面" in name and not beats:
            scene = "\n".join(_clean(x) for x in section["lines"] if x.strip()).strip()
            continue
        if "设定" in name and ("这一章" in name or "放出" in name):
            for row in _parse_table(section["lines"]):
                if row:
                    settings.append(row[0])
            continue
        if "战斗四问" in name:
            combat = _parse_table(section["lines"])
            continue
        if "不要写" in name:
            for line in section["lines"]:
                m = BULLET_RE.match(line.strip())
                if not m:
                    continue
                raw = m.group(1).strip()
                raw = re.sub(r"^(不出现|不要出现|不写|不要写)[：:「“]?", "", raw).strip("」” ")
                raw = re.sub(r"这些词$", "", raw).strip()
                parts = [p.strip("「」“” ") for p in re.split(r"[、，,；;／/]+", raw) if p.strip("「」“” ")]
                forbidden.extend(parts)
            continue
        if ("拍" in name or "收束" in name or "幕" in name) and "不要写" not in name:
            fields = _parse_fields(section["lines"])
            beat_name = re.split(r"[｜|·]", name)[-1].strip() if re.search(r"[｜|]", name) else name
            beats.append({
                "id": f"B{len(beats) + 1}",
                "name": beat_name,
                "heading": name,
                "goal": fields.get("做什么", ""),
                "entry": fields.get("开句", ""),
                "exit": fields.get("收句", ""),
                "points": fields.get("要点", []),
                "taboo": fields.get("禁忌", []),
                "target_chars": 0,
            })

    if not beats:
        raise ValueError("没有解析到节拍（标题里应有「第一拍」「收束」之类）")
    target = DEFAULT_BEAT_CHARS
    if est_lo and est_hi:
        target = int(((est_lo + est_hi) / 2) / len(beats))
    for beat in beats:
        beat["target_chars"] = target

    key = safe_chapter_key(chapter_key or re.sub(r"[^\d]", "", src.stem) or src.stem)
    if key.isdigit():
        key = f"第{key}章"
    data = {
        "schema": 1,
        "chapter_key": key,
        "title": title or src.stem,
        "source": str(src),
        "imported_at": now_iso(),
        "scene": scene,
        "beats": beats,
        "settings_budget": settings,
        "forbidden": forbidden,
        "combat_questions": combat,
        "estimated_chars": [est_lo, est_hi],
        "target_chars_total": sum(beat["target_chars"] for beat in beats),
    }
    out = plot_root(project_dir) / f"{key}.json"
    write_json(out, data)
    return {"ok": True, "plot": str(out), "chapter_key": key, "beats": len(beats), "target_chars": data["target_chars_total"]}


def load_plot(project_dir: str | Path, chapter_key: str) -> dict:
    path = plot_root(project_dir) / f"{safe_chapter_key(chapter_key)}.json"
    if not path.exists():
        raise FileNotFoundError(f"没有这一章的节拍卡：{path}")
    return read_json(path)


def _beat_text(beat: dict, include_taboo: bool = False) -> str:
    """节拍正文（默认不含「禁忌」清单本身，避免把禁忌词自己判成违规）。"""
    parts = [
        str(beat.get("goal") or ""),
        str(beat.get("entry") or ""),
        str(beat.get("exit") or ""),
        "\n".join(beat.get("points") or []),
    ]
    if include_taboo:
        parts.append("\n".join(beat.get("taboo") or []))
    return "\n".join(parts)


def validate(project_dir: str | Path, chapter_key: str) -> dict:
    project_dir = Path(project_dir)
    cfg = load_project(project_dir)
    rules = load_rules(project_dir, cfg)
    data = load_plot(project_dir, chapter_key)
    beats = data.get("beats") or []
    findings: list[dict] = []

    def add(code: str, severity: str, message: str, beat: str | None = None):
        findings.append({"code": code, "severity": severity, "message": message, "beat": beat})

    if len(beats) < 3:
        add("beats.few", "warn", f"只有 {len(beats)} 拍，可能拆得过粗（建议 3–8 拍）。")
    if len(beats) > 8:
        add("beats.many", "warn", f"有 {len(beats)} 拍，可能拆得过碎（建议 3–8 拍）。")

    target_total = sum(int(b.get("target_chars") or 0) for b in beats)
    est_lo, est_hi = (data.get("estimated_chars") or [0, 0])[:2]
    if est_lo and est_hi and not (est_lo * 0.8 <= target_total <= est_hi * 1.2):
        add("length.budget", "warn", f"节拍字数预算 {target_total}，细纲预估 {est_lo}–{est_hi}，差距偏大。")

    banned = [b.get("term") for b in rules.banned if b.get("term")]
    forbidden = [t for t in (data.get("forbidden") or []) if len(t) >= 2]
    for beat in beats:
        text = _beat_text(beat)
        prose = "\n".join([str(beat.get("entry") or ""), str(beat.get("exit") or "")])
        if not beat.get("entry"):
            add("beat.entry_missing", "warn", "缺「开句」。", beat.get("name"))
        if not beat.get("exit"):
            add("beat.exit_missing", "warn", "缺「收句」。", beat.get("name"))
        for term in banned:
            if term and term in prose:
                add("beat.banned", "fail", f"节拍的开句/收句里出现禁用词「{term}」。", beat.get("name"))
        for term in forbidden:
            if term in prose:
                add("beat.forbidden", "warn", f"节拍的开句/收句里出现「不要写」清单里的「{term}」。", beat.get("name"))

    # 跨拍重复句
    sentences: dict[str, str] = {}
    for beat in beats:
        for sentence in split_sentences(_beat_text(beat)):
            norm = re.sub(r"[\s。！？!?…，、；：]", "", sentence)
            if len(norm) < 12:
                continue
            if norm in sentences and sentences[norm] != beat.get("name"):
                add("beat.dup", "warn", f"跨拍重复句：{sentence[:30]}…（{sentences[norm]} / {beat.get('name')}）")
            sentences[norm] = beat.get("name")

    # 章末钩子
    last_exit = beats[-1].get("exit") if beats else ""
    hook = hook_score(last_exit or "")
    if hook["score"] < 45:
        add("beat.hook", "warn", f"最后收句钩子偏弱（{hook['score']} 分）：{'；'.join(hook['reasons'])}")

    # 设定暴露预算
    settings = data.get("settings_budget") or []
    if len(settings) > 6:
        add("settings.budget", "warn", f"本章放出的设定 {len(settings)} 条，偏多（建议 ≤5）。")

    return {
        "ok": True,
        "chapter_key": chapter_key,
        "beats": len(beats),
        "target_chars_total": target_total,
        "estimated_chars": [est_lo, est_hi],
        "findings": findings,
        "pass": not any(f["severity"] == "fail" for f in findings),
        "hook": hook,
        "checked_at": now_iso(),
    }


BEAT_SCHEMA = {
    "type": "object",
    "properties": {
        "chapter_key": {"type": "string"},
        "title": {"type": "string"},
        "scene": {"type": "string"},
        "beats": {
            "type": "array",
            "minItems": 3,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "goal": {"type": "string"},
                    "entry": {"type": "string"},
                    "exit": {"type": "string"},
                    "points": {"type": "array", "items": {"type": "string"}},
                    "taboo": {"type": "array", "items": {"type": "string"}},
                    "target_chars": {"type": "integer"},
                },
                "required": ["name", "goal", "entry", "exit", "target_chars"],
            },
        },
        "settings_budget": {"type": "array", "items": {"type": "string"}},
        "forbidden": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["chapter_key", "beats"],
}

PROMPT = """你是小说结构编辑。请把下面这段剧情拆成 3–8 个"节拍"，只输出 JSON（不要解释）。

每个节拍必须包含：
- name：2–6 字
- goal：这一拍发生什么（≤120 字）
- entry：这一拍的开句（具体句子，不要"待写"）
- exit：这一拍的收句（具体句子）
- points：2–5 条要点（细节/动作/信息）
- taboo：这一拍不许出现的东西（0–3 条）
- target_chars：目标字数（全章预算均分，合计约 N 字）

硬要求：
- 按原文剧情，不增删事件；可以调序、拆合；
- 不写解释句、不升华、不替读者下结论；
- 设定名词按本书规则：不新增、不解释、能演就不说；
- 最后两拍之间要有钩子。

【剧情】
{{PLOT}}

【本书禁忌】
{{FORBIDDEN}}

【输出】只输出符合下面 Schema 的 JSON：
{{SCHEMA}}
"""


def template(project_dir: str | Path, chapter_key: str | None = None, total_chars: int = 2200) -> dict:
    project_dir = Path(project_dir)
    cfg = load_project(project_dir)
    rules = load_rules(project_dir, cfg)
    forbidden = [b.get("term") for b in rules.banned if b.get("term")]
    prompt = PROMPT.replace("{{PLOT}}", "（把剧情梗概贴到这里）") \
        .replace("{{FORBIDDEN}}", "、".join(forbidden)) \
        .replace("{{SCHEMA}}", json.dumps(BEAT_SCHEMA, ensure_ascii=False, indent=1)) \
        .replace("N 字", f"{total_chars} 字")
    return {
        "ok": True,
        "chapter_key": chapter_key or "新章",
        "schema": BEAT_SCHEMA,
        "prompt": prompt,
        "total_chars": total_chars,
        "default_beat_chars": int(total_chars / 5),
        "note": "让 AI 按 prompt 产出 JSON 后，用 plot submit 校验并落盘；本工具不调用模型。",
    }


def submit_beats(project_dir: str | Path, payload: dict) -> dict:
    project_dir = Path(project_dir)
    data = dict(payload or {})
    chapter_key = safe_chapter_key(data.get("chapter_key") or "新章")
    beats = data.get("beats")
    if not isinstance(beats, list) or not beats:
        raise ValueError("payload 里缺 beats 数组")
    normalized = []
    default_target = int((data.get("estimated_chars") or [0, 0])[1] or 0) or 0
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            raise ValueError(f"beats[{index}] 不是对象")
        for key in ("name", "goal", "entry", "exit"):
            if not str(beat.get(key) or "").strip():
                raise ValueError(f"beats[{index}] 缺 {key}")
        target = int(beat.get("target_chars") or (int(default_target / len(beats)) if default_target else DEFAULT_BEAT_CHARS))
        normalized.append({
            "id": f"B{index + 1}",
            "name": str(beat["name"]).strip(),
            "goal": str(beat["goal"]).strip(),
            "entry": str(beat["entry"]).strip(),
            "exit": str(beat["exit"]).strip(),
            "points": [str(x).strip() for x in (beat.get("points") or []) if str(x).strip()],
            "taboo": [str(x).strip() for x in (beat.get("taboo") or []) if str(x).strip()],
            "target_chars": target,
        })
    data["beats"] = normalized
    data.setdefault("title", chapter_key)
    data["source"] = "agent"
    data["submitted_at"] = now_iso()
    data["schema"] = 1
    data["target_chars_total"] = sum(b["target_chars"] for b in normalized)
    out = plot_root(project_dir) / f"{chapter_key}.json"
    write_json(out, data)
    validation = validate(project_dir, chapter_key)
    return {"ok": True, "plot": str(out), "chapter_key": chapter_key, "beats": len(normalized), "validation": validation}


def list_plots(project_dir: str | Path) -> dict:
    root = plot_root(project_dir)
    items = []
    if root.exists():
        for path in sorted(root.glob("*.json")):
            data = read_json(path, {}) or {}
            items.append({
                "chapter_key": data.get("chapter_key") or path.stem,
                "title": data.get("title"),
                "beats": len(data.get("beats") or []),
                "target_chars": data.get("target_chars_total"),
                "source": data.get("source"),
                "path": str(path),
                "needs_validation": True,
            })
    return {"ok": True, "plots": items}

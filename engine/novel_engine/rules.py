# -*- coding: utf-8 -*-
"""项目配置 + 规则包。

设计原则：引擎不写死任何一本书的内容。
- 通用规则（AI 腔、标点、节奏）来自 DEFAULT_*；
- 本书规则（禁用词、设定事实、白名单、文风基线）来自项目目录下的 config.json / rules/*.json。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CHAPTER_PATTERN = r"^第([0-9\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u96f6\u4e24]+)\u7ae0"
DEFAULT_THRESHOLDS = {
    "near_duplicate_ratio": 0.88,
    "near_duplicate_min_len": 16,
    "near_duplicate_window": 120,
    "repeated_opening_run": 3,
    "repeated_opening_chars": 2,
    "watch_term_chapter_min": 4,
    "hook_weak_below": 45,
    "chapter_outlier_z": 1.8,
    "max_findings_per_chapter": 40,
    "voice_tolerance_pct": 10.0,
}

DEFAULT_VOICE = {
    "image_per_10k": None,      # 比喻密度（像/万字）
    "sisi": None,
    "mengdi": None,
    "huran": None,
    "baseline_note": "",
}

# 通用 AI 腔模式：与具体书无关，中文叙述通用。
DEFAULT_AI = [
    {
        "id": "ai.conclusion",
        "name": "替读者下结论",
        "severity": "warn",
        "scope": "narration",
        "patterns": [r"这意味着", r"这说明", r"这证明", r"足以说明", r"(?<!肉眼)可见", r"所谓",
                      r"也就是说", r"换句话说", r"说白了", r"归根结底", r"本质上"],
        "exclude": [r"肉眼可见"],
        "why": "替读者把结论说出来了。人写东西会漏、会跳，让读者自己补。",
        "suggestion": "整句删掉；要留信息就挪进动作或对白。",
    },
    {
        "id": "ai.causal",
        "name": "补因果解释",
        "severity": "warn",
        "scope": "narration",
        "patterns": [r"之所以", r"是因为", r"是为了", r"因此"],
        "exclude": [],
        "why": "为了让前后逻辑通顺而补的一句说明，是最隐蔽的 AI 味。",
        "suggestion": "先删；删不掉就挪进动作，不加解释句。",
    },
    {
        "id": "ai.telly_emotion",
        "name": "直接贴情绪标签",
        "severity": "info",
        "scope": "narration",
        "patterns": [r"感到(?:一阵)?(?:恐惧|害怕|愤怒|悲伤|绝望|温暖|熟悉|不安)",
                      r"涌起(?:一股|一种)", r"心里(?:一沉|发毛|一紧)",
                      r"说不出的(?!(?:味道|气味|香味|声音))", r"难以言喻",
                      r"心里五味杂陈"],
        "exclude": [],
        "why": "直接告诉读者感受，而不是让读者从动作里看出来。",
        "suggestion": "删掉标签，换成生理反应或一个动作。",
    },
    {
        "id": "ai.summary_end",
        "name": "段末总结 / 升华",
        "severity": "warn",
        "scope": "narration_paragraph_end",
        "patterns": [r"仿佛(?:刚才|这一切)[^。]{0,20}(?:从来没有|从未|不曾)",
                      r"似乎(?:在|是)[^。]{0,12}(?:诉说|等待|见证|宣告)",
                      r"(?:这|那)就是[^。]{0,10}(?:意义|命运|答案|归宿)",
                      r"一切(?:都|仿佛)[^。]{0,10}(?:注定|值得|结束)"],
        "exclude": [],
        "why": "段落最后一句总想拔高一下，是典型的 AI 收尾。",
        "suggestion": "删掉升华句，落回具体动作或画面。",
    },
    {
        "id": "ai.common_sense",
        "name": "常识铺垫 + 转折 + 比喻",
        "severity": "warn",
        "scope": "narration",
        "patterns": [r"(?:太空|真空|宇宙|外太空)[^。]{0,12}(?:没有声音|什么声音都没有|没有重力)"
                      r"[^。]{0,20}(?:但|可|却)[^。]{0,40}(?:像|仿佛|好像)"],
        "exclude": [],
        "why": "「先交代物理常识 → 转折 → 打比喻」这个句式一眼像 AI。",
        "suggestion": "删掉常识前半句，直接从画面写起。",
    },
]

# 通用设定/文字事实检查：本书可按体裁补充。
DEFAULT_FACTS: list[dict[str, Any]] = []


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


@dataclass
class PatternRule:
    id: str
    name: str
    category: str
    severity: str
    scope: str
    patterns: list[re.Pattern]
    excludes: list[re.Pattern]
    why: str
    suggestion: str
    replacement: str = ""

    def matches(self, text: str) -> list[re.Match]:
        """命中判定。

        exclude 只看命中位置附近的小窗口（旧实现查整段，一处豁免会否掉全段）。
        """
        hits: list[re.Match] = []
        for pat in self.patterns:
            for m in pat.finditer(text):
                if self.excludes:
                    a = max(0, m.start() - 8)
                    b = min(len(text), m.end() + 8)
                    window = text[a:b]
                    if any(x.search(window) for x in self.excludes):
                        continue
                hits.append(m)
        return hits


@dataclass
class Rules:
    chapter_pattern: str = DEFAULT_CHAPTER_PATTERN
    banned: list[dict] = field(default_factory=list)
    ai: list[PatternRule] = field(default_factory=list)
    facts: list[PatternRule] = field(default_factory=list)
    allow_duplicates: list[str] = field(default_factory=list)
    allow_patterns: list[re.Pattern] = field(default_factory=list)
    watch_terms: list[str] = field(default_factory=list)
    voice: dict = field(default_factory=lambda: dict(DEFAULT_VOICE))
    thresholds: dict = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    ai_flavor: dict = field(default_factory=dict)
    do_not_touch: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    weak_hook_phrases: list[str] = field(default_factory=list)

    def allowed(self, text: str) -> bool:
        if text in self.allow_duplicates:
            return True
        return any(p.search(text) for p in self.allow_patterns)


def _compile(pattern: str) -> re.Pattern | None:
    try:
        return re.compile(pattern)
    except re.error:
        return None


def _build_pattern_rules(items: list[dict], category: str) -> list[PatternRule]:
    out: list[PatternRule] = []
    for item in items:
        pats = [p for p in (_compile(x) for x in item.get("patterns", [])) if p]
        if not pats:
            continue
        excludes = [p for p in (_compile(x) for x in item.get("exclude", [])) if p]
        out.append(PatternRule(
            id=item.get("id") or f"rule.{len(out)}",
            name=item.get("name") or item.get("id") or category,
            category=item.get("category") or category,
            severity=item.get("severity") or "warn",
            scope=item.get("scope") or "narration",
            patterns=pats,
            excludes=excludes,
            why=item.get("why") or "",
            suggestion=item.get("suggestion") or "",
            replacement=item.get("replacement") or "",
        ))
    return out


def load_project(project_dir: str | Path) -> dict:
    """读取项目配置，并解析 main_draft 绝对路径。"""
    p = Path(project_dir).resolve()
    cfg_path = p / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"项目缺少 config.json：{cfg_path}")
    cfg = read_json(cfg_path, {})
    cfg["_project_dir"] = str(p)
    main_rel = cfg.get("main_draft") or "input/主稿.docx"
    cfg["_main_draft_path"] = str((p / main_rel).resolve())
    if not Path(cfg["_main_draft_path"]).exists():
        raise FileNotFoundError(f"主稿不存在：{cfg['_main_draft_path']}")
    return cfg


def load_rules(project_dir: str | Path, cfg: dict) -> Rules:
    p = Path(project_dir).resolve()
    rule_rel = cfg.get("rules_file") or "rules/rules.json"
    raw = read_json(p / rule_rel, {}) or {}

    rules = Rules()
    rules.chapter_pattern = cfg.get("chapter_pattern") or raw.get("chapter_pattern") or DEFAULT_CHAPTER_PATTERN
    rules.voice = {**DEFAULT_VOICE, **(raw.get("voice") or {})}
    rules.thresholds = {**DEFAULT_THRESHOLDS, **(raw.get("thresholds") or {})}
    rules.banned = list(raw.get("banned_terms") or [])
    rules.allow_duplicates = list(raw.get("allow_duplicates") or [])
    rules.watch_terms = list(raw.get("watch_terms") or [])
    rules.do_not_touch = list(raw.get("do_not_touch") or [])
    rules.notes = list(raw.get("notes") or [])
    rules.weak_hook_phrases = list(raw.get("weak_hook_phrases") or [])
    rules.allow_patterns = [x for x in (_compile(p) for p in (raw.get("allow_patterns") or [])) if x]
    af_rel = raw.get("ai_flavor_file") or "rules/ai-flavor.json"
    rules.ai_flavor = read_json(p / af_rel, {}) or {}

    rules.ai = _build_pattern_rules(DEFAULT_AI + list(raw.get("ai_patterns") or []), "AI 腔")
    rules.facts = _build_pattern_rules(list(raw.get("facts") or []) + list(raw.get("extra_facts") or []), "设定")
    return rules

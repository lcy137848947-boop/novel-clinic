# -*- coding: utf-8 -*-
"""扫描器：把稿子拆成可定位、可解释、可审批的问题条目。

finding 约定（全引擎一致）：
{
  id, rule, category, severity(hard|warn|info), chapter, para(0-based 章内段序),
  para_display(1-based), quote(整段原文), why, suggestion,
  action(flag|delete|replace), replacement, auto_fixable, confidence, meta
}
"""
from __future__ import annotations

import hashlib
import re
import statistics
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from .model import Book, Chapter, Paragraph, cjk_count, dialogue_spans, is_dialogue_only, narration_segments, sha1, split_sentences
from .rules import Rules

PLACEHOLDER_RE = re.compile(r"\* \*|⑤|＊|●○")
# 兜底词表：项目可在 rules.json 用 weak_hook_phrases 覆盖（引擎不写死某一本书的句子）
WEAK_HOOK_PHRASES = [
    "闭上了眼睛", "从来没有发生过", "尽快到达", "只能加快",
    "红棕色一片", "星云包裹上来", "闭上了眼", "沉沉睡去",
]
HOOK_ACTION_WORDS = ["要", "去", "得", "必须", "准备", "看看", "跟着", "走向", "追", "出发", "回去", "进去", "拉下"]
HOOK_TWIST_WORDS = ["却", "但", "原来", "那是", "竟然", "忽然", "突然", "而是"]
CHANGE_MARKERS = ["停了", "断了", "响了", "灭了", "裂了", "倒了", "死了", "走了", "来了", "没了", "睁开", "亮起", "暗下", "转身", "回头"]
REVEAL_MARKERS = ["那是", "这是", "原来", "竟然", "露出", "正是"]
INTERJECTION_ONLY = {"操", "靠", "妈的", "嗯", "啊", "哦", "好", "行", "……", "…", "艹", "尼玛"}


def finding_id(rule: str, chapter: int, para: int, text: str) -> str:
    """内容指纹：只和规则 + 命中文本有关，段序漂移不会换 id。"""
    raw = f"{rule}|{sha1(text)}"
    return "F-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def make_finding(
    *,
    rule: str,
    category: str,
    severity: str,
    chapter: int,
    para: int,
    paragraph: str,
    why: str,
    suggestion: str,
    quote: str | None = None,
    action: str = "flag",
    replacement: str = "",
    auto_fixable: bool = False,
    confidence: str = "medium",
    meta: dict | None = None,
) -> dict:
    return {
        "id": finding_id(rule, chapter, para, quote if quote is not None else paragraph),
        "rule": rule,
        "category": category,
        "severity": severity,
        "chapter": chapter,
        "para": para,
        "para_display": para + 1,
        "quote": quote if quote is not None else paragraph,
        "why": why,
        "suggestion": suggestion,
        "action": action,
        "replacement": replacement,
        "auto_fixable": auto_fixable,
        "confidence": confidence,
        "meta": meta or {},
    }


def is_ascii_apostrophe(text: str, i: int) -> bool:
    """text[i] 是否是不该当引号处理的英文撇号（don't / it's 这种夹在两个字母之间）。"""
    if text[i] != "'":
        return False
    prev = text[i - 1] if i else ""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    return prev.isascii() and prev.isalpha() and nxt.isascii() and nxt.isalpha()


def straight_quote_count(text: str) -> int:
    """半角直引号计数（英文撇号不算），scan 与 verify 共用同一口径。"""
    n = text.count('"')
    for i, ch in enumerate(text):
        if ch == "'" and not is_ascii_apostrophe(text, i):
            n += 1
    return n


def has_straight_quote(text: str) -> bool:
    """是否含半角直引号：ASCII 双引号一律算，ASCII 单引号排除英文撇号。"""
    return straight_quote_count(text) > 0


def cn_quotes(text: str) -> str:
    """半角引号 → 中文引号（成对交替，按段内已有中文引号初始化配对状态）。"""
    out: list[str] = []
    c_open, c_close = text.count("“"), text.count("”")
    open_dq = c_open <= c_close
    open_sq = text.count("‘") <= text.count("’")
    # 本段没有任何中文双引号、且只有一个落在段尾的直引号：那是上一段对白的收尾，按右引号处理
    if c_open == 0 and c_close == 0 and text.count('"') == 1 and text.rstrip().endswith('"'):
        open_dq = False
    for i, ch in enumerate(text):
        if ch == '"':
            out.append("“" if open_dq else "”")
            open_dq = not open_dq
        elif ch == "'":
            if is_ascii_apostrophe(text, i):
                out.append(ch)          # don't / it's 这种英文撇号原样保留
                continue
            out.append("‘" if open_sq else "’")
            open_sq = not open_sq
        else:
            out.append(ch)
    return "".join(out)


def quote_balance(text: str) -> tuple[int, int, int, int]:
    return text.count("“"), text.count("”"), text.count("「"), text.count("」")


# ---------------------------------------------------------------- 硬伤
def scan_hard(book: Book, rules: Rules) -> list[dict]:
    findings: list[dict] = []
    banned = [(b.get("term"), b.get("replacement") or "", b.get("reason") or "") for b in rules.banned if b.get("term")]
    seen_chapters: dict[str, int] = {}

    for ch in book.chapters:
        if ch.index > 1 and not ch.paragraphs:
            findings.append(make_finding(
                rule="hard.empty_chapter", category="硬伤", severity="hard",
                chapter=ch.index, para=0, paragraph=ch.title,
                quote=ch.title, why="本章没有任何正文。", suggestion="检查是否误删或分章错误。",
                action="flag"))
        body_hash = sha1("".join(p.text for p in ch.paragraphs)) if ch.paragraphs else None
        if body_hash and body_hash in seen_chapters:
            findings.append(make_finding(
                rule="hard.duplicate_chapter", category="硬伤", severity="hard",
                chapter=ch.index, para=0, paragraph=ch.title,
                quote=ch.title,
                why=f"本章正文与第 {seen_chapters[body_hash]} 章完全相同，疑似重复粘贴。",
                suggestion="确认后删掉重复章。", action="flag"))
        elif body_hash:
            seen_chapters[body_hash] = ch.index

        for para in ch.paragraphs:
            text = para.text
            if _skip_do_not_touch(rules, text):
                continue
            hits = [(t, r, why) for (t, r, why) in banned if t and t in text]
            if hits:
                # 同一段多个禁用词合并成一条，避免每条都吐「整段替换」互相覆盖
                all_repl = all(r for _, r, _ in hits)
                if all_repl:
                    new_text = text
                    for term, repl, _ in hits:
                        new_text = new_text.replace(term, repl)
                    why = "；".join(f"「{t}」" + (f"（{w}）" if w else "") for t, _, w in hits)
                    findings.append(make_finding(
                        rule="hard.banned_term", category="硬伤", severity="hard",
                        chapter=ch.index, para=para.index_in_chapter, paragraph=text,
                        why=f"使用了禁用词：{why}。",
                        suggestion="按规则包替换：" + "；".join(f"「{t}」→「{r}」" for t, r, _ in hits) + "。",
                        action="replace", replacement=new_text, auto_fixable=True,
                        meta={"terms": [t for t, _, _ in hits]}))
                else:
                    why = "；".join(f"「{t}」" + (f"（{w}）" if w else "") for t, _, w in hits)
                    findings.append(make_finding(
                        rule="hard.banned_term", category="硬伤", severity="hard",
                        chapter=ch.index, para=para.index_in_chapter, paragraph=text,
                        why=f"使用了禁用词：{why}。",
                        suggestion="删除该词或按设定替代表达。",
                        action="flag", meta={"terms": [t for t, _, _ in hits]}))
            if PLACEHOLDER_RE.search(text):
                findings.append(make_finding(
                    rule="hard.placeholder", category="硬伤", severity="hard",
                    chapter=ch.index, para=para.index_in_chapter, paragraph=text,
                    why="残留占位符/特殊标记。", suggestion="删掉占位符或补上真实内容。",
                    action="flag"))
            if has_straight_quote(text):
                findings.append(make_finding(
                    rule="hard.straight_quote", category="硬伤", severity="hard",
                    chapter=ch.index, para=para.index_in_chapter, paragraph=text,
                    why="出现半角直引号，与全书中文引号不统一。",
                    suggestion="统一转换为中文引号。",
                    action="replace", replacement=cn_quotes(text),
                    auto_fixable=True))
        lq, rq, lj, rj = quote_balance(ch.text)
        tol = int(rules.thresholds.get("quote_imbalance_tolerance", 1))
        if abs(lq - rq) > tol or abs(lj - rj) > tol:
            first = ch.paragraphs[0] if ch.paragraphs else None
            findings.append(make_finding(
                rule="hard.quote_unbalanced", category="硬伤", severity="info",
                chapter=ch.index, para=0,
                paragraph=ch.title,
                quote=f"“×{lq} / ”×{rq}；「×{lj} / 」×{rj}",
                why=f"本章引号总数不成对（“×{lq} / ”×{rq}；「×{lj} / 」×{rj}），可能有漏引号。",
                suggestion="全章搜一遍引号配对；注意跨段对白。", action="flag",
                meta={"first_para": first.text if first else ""}))
    return findings


# ---------------------------------------------------------------- 重复
def _norm(text: str) -> str:
    return re.sub(r"[\s。！？!?…，、；：,.!?;:~～—\-“”‘’「」『』()（）]", "", text)


def scan_duplicates(book: Book, rules: Rules) -> list[dict]:
    findings: list[dict] = []
    paras = book.paragraphs
    exact: dict[str, list[Paragraph]] = defaultdict(list)
    for p in paras:
        if _skip_do_not_touch(rules, p.text):
            continue
        if len(p.text) >= 12:
            exact[p.text].append(p)
    for text, locs in exact.items():
        if len(locs) < 2 or rules.allowed(text):
            continue
        first = locs[0]
        second = locs[1]
        findings.append(make_finding(
            rule="dup.exact_paragraph", category="重复", severity="warn",
            chapter=second.chapter, para=second.index_in_chapter, paragraph=second.text,
            why=f"与第 {first.chapter} 章第 {first.index_in_chapter + 1} 段完全相同（共 {len(locs)} 处）。",
            suggestion="人工确认：若是呼应/复调可加进白名单；否则删掉重复段落。",
            action="flag"))

    # 近重复句：按章内比较，控制窗口
    ratio_th = float(rules.thresholds.get("near_duplicate_ratio", 0.88))
    min_len = int(rules.thresholds.get("near_duplicate_min_len", 16))
    window = int(rules.thresholds.get("near_duplicate_window", 120))
    for ch in book.chapters:
        sents: list[tuple[int, str, str]] = []
        for p in ch.paragraphs:
            if _skip_do_not_touch(rules, p.text):
                continue
            for s in split_sentences(p.text):
                n = _norm(s)
                if len(n) >= min_len:
                    sents.append((p.index_in_chapter, s, n))
        used: set[int] = set()
        for i in range(len(sents)):
            if i in used:
                continue
            for j in range(i + 1, min(i + window, len(sents))):
                if j in used or sents[i][0] == sents[j][0]:
                    continue
                a, b = sents[i][2], sents[j][2]
                if abs(len(a) - len(b)) > max(4, len(a) * 0.35):
                    continue
                r = SequenceMatcher(None, a, b).ratio()
                if r >= ratio_th:
                    used.add(i)
                    used.add(j)
                    findings.append(make_finding(
                        rule="dup.near_sentence", category="重复", severity="info",
                        chapter=ch.index, para=sents[j][0], paragraph=ch.paragraphs[sents[j][0]].text,
                        quote=sents[j][1], why=f"与同章前文一句相似度 {r:.0%}：{sents[i][1][:30]}…",
                        suggestion="确认是否重复表达；能删则删。", action="flag",
                        confidence="low", meta={"ratio": round(r, 2)}))
                    break

    # 连续同头（三段以上）
    run_chars = int(rules.thresholds.get("repeated_opening_chars", 2))
    run_min = int(rules.thresholds.get("repeated_opening_run", 3))
    for ch in book.chapters:
        ps = ch.paragraphs
        i = 0
        while i < len(ps):
            opening = re.sub(r"^[“”‘’「」『』\s]+", "", ps[i].text)[:run_chars]
            j = i
            while (
                j + 1 < len(ps)
                and len(opening) == run_chars
                and re.sub(r"^[“”‘’「」『』\s]+", "", ps[j + 1].text)[:run_chars] == opening
            ):
                j += 1
            if j - i + 1 >= run_min and len(opening) >= run_chars and all(len(p.text) >= 10 for p in ps[i : j + 1]):
                if not rules.allowed(ps[i].text):
                    findings.append(make_finding(
                        rule="dup.repeated_opening", category="重复", severity="info",
                        chapter=ch.index, para=ps[i].index_in_chapter, paragraph=ps[i].text,
                        why=f"连续 {j - i + 1} 段都以「{opening}」开头。",
                        suggestion="确认是否是作者节奏；若不是，换个开头。", action="flag",
                        confidence="low"))
            i = j + 1

    # 本章高频意象词（可配置 watch_terms；默认不启用）
    min_count = int(rules.thresholds.get("watch_term_chapter_min", 4))
    for term in rules.watch_terms:
        for ch in book.chapters:
            c = ch.text.count(term)
            if c >= min_count and not rules.allowed(ch.text):
                findings.append(make_finding(
                    rule="dup.watch_term", category="重复", severity="info",
                    chapter=ch.index, para=0, paragraph=ch.paragraphs[0].text if ch.paragraphs else ch.title,
                    quote=term, why=f"「{term}」在本章出现 {c} 次。",
                    suggestion="确认是否为有意复调；若否，替换其中几处。", action="flag",
                    confidence="low"))
    return findings


# ---------------------------------------------------------------- AI 腔
SENTINEL = "。"   # 用句号当分隔符：[^。] 类正则因此无法跨对白边界


def narration_with_map(text: str) -> tuple[str, list[tuple[int, int, int]]]:
    """拼接叙述片段（用句号分隔，[^。] 类正则因此不会跨对白边界），同时记录位置映射。

    返回 (narr, [(narr_start, orig_start, length), ...])。
    """
    spans = dialogue_spans(text)
    pieces: list[tuple[int, str]] = []
    cursor = 0
    for start, end in spans:
        if start > cursor:
            pieces.append((cursor, text[cursor:start]))
        cursor = max(cursor, end)
    if cursor < len(text):
        pieces.append((cursor, text[cursor:]))

    parts: list[str] = []
    mapping: list[tuple[int, int, int]] = []
    pos = 0
    for orig_start, piece in pieces:
        if not piece.strip():
            continue
        parts.append(piece)
        mapping.append((pos, orig_start, len(piece)))
        pos += len(piece) + 1          # +1 是哨兵
    return SENTINEL.join(parts), mapping


def narr_pos_to_orig(mapping: list[tuple[int, int, int]], pos: int) -> int | None:
    for nstart, ostart, length in mapping:
        if nstart <= pos <= nstart + length:
            return ostart + (pos - nstart)
    return None


def _skip_do_not_touch(rules: Rules, text: str) -> bool:
    return text in (rules.do_not_touch or [])


def _sentence_around(text: str, start: int, end: int, pad: int = 24) -> str:
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    return text[a:b].strip()


def scan_ai(book: Book, rules: Rules) -> list[dict]:
    findings: list[dict] = []
    per_chapter: Counter = Counter()
    cap = int(rules.thresholds.get("max_findings_per_chapter", 40))

    for ch in book.chapters:
        for para in ch.paragraphs:
            text = para.text
            if _skip_do_not_touch(rules, text):
                continue
            if rules.allowed(text):
                continue
            narr, narr_map = narration_with_map(text)
            if not narr.strip():
                continue
            sentences = split_sentences(text)
            last_sentence = sentences[-1] if sentences else text
            for rule in rules.ai:
                if per_chapter[ch.index] >= cap:
                    break
                hits: list = []
                if rule.scope == "any":
                    hits = rule.matches(text)
                elif rule.scope == "narration_paragraph_end":
                    if is_dialogue_only(last_sentence):
                        continue
                    hits = rule.matches(last_sentence)
                else:
                    hits = rule.matches(narr)
                if not hits:
                    continue
                m = hits[0]
                first = m.group(0)
                if rule.scope in ("any", "narration_paragraph_end"):
                    base_text, base_pos = text, m.start()
                else:
                    orig = narr_pos_to_orig(narr_map, m.start())
                    base_text, base_pos = (text, orig) if orig is not None else (narr, m.start())
                quote = _sentence_around(base_text, base_pos, base_pos + len(first))
                findings.append(make_finding(
                    rule=rule.id, category=rule.category, severity=rule.severity,
                    chapter=ch.index, para=para.index_in_chapter, paragraph=text,
                    quote=quote,
                    why=f"{rule.name}：命中「{first}」。" + (rule.why or ""),
                    suggestion=rule.suggestion or "先删；删不掉就挪进动作。",
                    action="flag", confidence="medium", meta={"hit": first}))
                per_chapter[ch.index] += 1

            # 连续同构句（同一段内 3 句以上同头；跳过档案/列表体）
            if per_chapter[ch.index] >= cap:
                continue
            if len(sentences) >= 3 and not text.lstrip().startswith(("—", "-", "·", "【", "（", "(")):
                run = 1
                for k in range(1, len(sentences)):
                    a = sentences[k - 1].strip()
                    b = sentences[k].strip()
                    if len(a) >= 8 and len(b) >= 8 and a[:2] == b[:2] and a[:2].strip():
                        run += 1
                    else:
                        run = 1
                    if run >= 3:
                        findings.append(make_finding(
                            rule="ai.repeat_structure", category="AI 腔", severity="info",
                            chapter=ch.index, para=para.index_in_chapter, paragraph=text,
                            quote=" / ".join(s.strip()[:18] for s in sentences[k - 2 : k + 1]),
                            why="连续三句同一个开头，句式重复。",
                            suggestion="打散其中一句的句式。", action="flag",
                            confidence="low", meta={"opening": b[:2]}))
                        per_chapter[ch.index] += 1
                        break
    return findings


# ---------------------------------------------------------------- 设定一致性
def scan_consistency(book: Book, rules: Rules) -> list[dict]:
    findings: list[dict] = []
    for ch in book.chapters:
        for para in ch.paragraphs:
            text = para.text
            if _skip_do_not_touch(rules, text):
                continue
            narr, _ = narration_with_map(text)
            for rule in rules.facts:
                if rule.scope == "narration":
                    target = narr
                else:
                    target = text
                hits = rule.matches(target)
                if not hits:
                    continue
                hit = hits[0]
                findings.append(make_finding(
                    rule=rule.id, category=rule.category or "设定", severity=rule.severity,
                    chapter=ch.index, para=para.index_in_chapter, paragraph=text,
                    quote=_sentence_around(text, 0, len(text), 10),
                    why=f"{rule.name}：命中「{hit.group(0)}」。" + (rule.why or ""),
                    suggestion=rule.suggestion or "按设定规则处理。",
                    action="flag", confidence="high" if rule.severity == "hard" else "medium",
                    meta={"hit": hit.group(0)}))
    return findings


# ---------------------------------------------------------------- 节奏 / 章末钩子
def hook_score(last_para: str, weak_phrases: list[str] | None = None) -> dict:
    text = last_para.strip()
    score = 50
    reasons: list[str] = []
    if not text:
        return {"score": 0, "level": "empty", "reasons": ["章末为空"]}
    core = re.sub(r"^[“”‘’「」『』\s]+|[“”‘’「」『』。！？!?…\s]+$", "", text)
    if core in INTERJECTION_ONLY:
        score -= 30
        reasons.append("章末只有语气词/极短句")
    if re.search(r"[？?]", text):
        score += 12
        reasons.append("以疑问收尾")
    if re.search(r"[”」]$", text):
        score += 8
        reasons.append("以对白收尾")
    if any(w in text for w in HOOK_ACTION_WORDS):
        score += 10
        reasons.append("含具体动作/决定")
    if any(w in text for w in HOOK_TWIST_WORDS):
        score += 6
        reasons.append("含转折/新信息")
    if any(w in text for w in CHANGE_MARKERS):
        score += 15
        reasons.append("有状态变化")
    if any(w in text for w in REVEAL_MARKERS):
        score += 18
        reasons.append("有揭示/反转")
    weak = [w for w in (weak_phrases or WEAK_HOOK_PHRASES) if w in text]
    weak = [w for w in weak if not any(w != other and w in other for other in weak)]
    if weak:
        score -= 18
        reasons.append("落在景物/闭眼/总结上：" + "、".join(weak))
    if 8 <= len(text) <= 60:
        score += 4
    score = max(5, min(95, score))
    level = "strong" if score >= 65 else "medium" if score >= 45 else "weak"
    return {"score": score, "level": level, "reasons": reasons or ["常规收尾"]}


def scan_pacing(book: Book, rules: Rules) -> tuple[list[dict], dict[int, dict], dict]:
    findings: list[dict] = []
    weak_below = int(rules.thresholds.get("hook_weak_below", 45))
    hook_by_chapter: dict[int, dict] = {}
    chapter_stats: list[dict] = []

    for ch in book.chapters:
        last = ch.paragraphs[-1].text if ch.paragraphs else ""
        hook = hook_score(last, rules.weak_hook_phrases or None)
        hook_by_chapter[ch.index] = hook
        dialogue_cjk = 0
        for p in ch.paragraphs:
            spans = dialogue_spans(p.text)
            dialogue_cjk += sum(cjk_count(p.text[s:e]) for s, e in spans)
        chapter_stats.append({
            "index": ch.index,
            "title": ch.title,
            "paras": len(ch.paragraphs),
            "cjk": ch.cjk,
            "dialogue_ratio": round(dialogue_cjk / ch.cjk, 3) if ch.cjk else 0,
            "hook": hook,
            "last": last,
        })
        if hook["score"] < weak_below and ch.paragraphs:
            findings.append(make_finding(
                rule="pace.weak_hook", category="节奏", severity="warn",
                chapter=ch.index, para=ch.paragraphs[-1].index_in_chapter,
                paragraph=last, quote=last,
                why=f"章末钩子偏弱（{hook['score']} 分）：" + "；".join(hook["reasons"]) + "。",
                suggestion="用一个具体动作、决定或新信息收尾；不要落在景物、闭眼、总结上。",
                action="flag", confidence="medium"))

    cjks = [c["cjk"] for c in chapter_stats if c["cjk"]]
    if len(cjks) >= 5:
        mean = statistics.mean(cjks)
        sd = statistics.pstdev(cjks)
        z_th = float(rules.thresholds.get("chapter_outlier_z", 1.8))
        if sd > 0:
            for c in chapter_stats:
                z = (c["cjk"] - mean) / sd
                if abs(z) >= z_th:
                    findings.append(make_finding(
                        rule="pace.chapter_outlier", category="节奏", severity="info",
                        chapter=c["index"], para=0,
                        paragraph=c["title"], quote=c["title"],
                        why=f"本章 {c['cjk']} 字，偏离全书均值 {mean:.0f} 字（z={z:.1f}）。",
                        suggestion="确认篇幅是否匹配本章信息量；过长可拆分/删冗余，过短可补动作。",
                        action="flag", confidence="low"))
    return findings, hook_by_chapter, {"chapters": chapter_stats, "mean_cjk": statistics.mean(cjks) if cjks else 0}


# ---------------------------------------------------------------- 文风
def style_metrics(book: Book, rules: Rules) -> dict:
    text = book.text
    cjk = book.cjk or 1
    counts = {
        "image": text.count("像"),
        "sisi": text.count("死死"),
        "mengdi": text.count("猛地"),
        "huran": text.count("忽然"),
        "straight_quotes": text.count('"') + text.count("'"),
    }
    per10k = {k: round(v / cjk * 10000, 1) for k, v in counts.items() if k != "straight_quotes"}
    baseline = rules.voice or {}
    labels = {"image": "像/万字", "sisi": "死死", "mengdi": "猛地", "huran": "忽然"}
    deviations: dict[str, dict] = {}
    for key, label in labels.items():
        base = baseline.get(key) if key != "image" else baseline.get("image_per_10k")
        if base is None:
            continue
        cur = per10k["image"] if key == "image" else counts[key]
        pct = (cur - float(base)) / float(base) * 100 if base else 0
        deviations[key] = {"label": label, "current": cur, "baseline": base, "pct": round(pct, 1)}
    return {"counts": counts, "per_10k": per10k, "baseline": baseline, "deviations": deviations}


# ---------------------------------------------------------------- 汇总
def scan_book(book: Book, rules: Rules) -> dict:
    findings: list[dict] = []
    findings += scan_hard(book, rules)
    findings += scan_duplicates(book, rules)
    findings += scan_ai(book, rules)
    findings += scan_consistency(book, rules)
    pacing_findings, hook_by_chapter, pacing_meta = scan_pacing(book, rules)
    findings += pacing_findings
    metrics = style_metrics(book, rules)

    # 稳定定位：apply 用 global_index + quote 双校验，避免改稿后段序漂移打错段
    para_index = {(p.chapter, p.index_in_chapter): p for p in book.paragraphs}
    for f in findings:
        p = para_index.get((f["chapter"], f["para"]))
        if p is not None:
            f["global_index"] = p.global_index
            f["text_sha1"] = sha1(p.text)
        else:
            f["global_index"] = None
            f["text_sha1"] = sha1(f.get("quote") or "")

    order = {"hard": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: (order.get(f["severity"], 3), f["chapter"], f["para"], f["rule"]))

    chapters = []
    by_ch: dict[int, list[dict]] = defaultdict(list)
    for f in findings:
        by_ch[f["chapter"]].append(f)
    stats_by_ch = {c["index"]: c for c in pacing_meta["chapters"]}
    for ch in book.chapters:
        st = stats_by_ch.get(ch.index, {})
        chapters.append({
            "index": ch.index,
            "title": ch.title,
            "paras": len(ch.paragraphs),
            "cjk": ch.cjk,
            "dialogue_ratio": st.get("dialogue_ratio", 0),
            "hook": hook_by_chapter.get(ch.index, hook_score("")),
            "last": st.get("last", ch.paragraphs[-1].text if ch.paragraphs else ""),
            "findings": len(by_ch.get(ch.index, [])),
            "severity_counts": {
                "hard": sum(1 for f in by_ch.get(ch.index, []) if f["severity"] == "hard"),
                "warn": sum(1 for f in by_ch.get(ch.index, []) if f["severity"] == "warn"),
                "info": sum(1 for f in by_ch.get(ch.index, []) if f["severity"] == "info"),
            },
        })

    return {
        "findings": findings,
        "chapters": chapters,
        "metrics": metrics,
        "stats": {
            "chapters": len(book.chapters),
            "paragraphs": len(book.paragraphs),
            "total_paragraphs": len(book.paragraphs) + len(book.chapters) + len(book.front_matter),
            "cjk": book.cjk,
            "cjk_with_headings": book.cjk
            + sum(cjk_count(c.title) for c in book.chapters)
            + sum(cjk_count(t) for t in book.front_matter),
            "findings": len(findings),
        },
    }

# -*- coding: utf-8 -*-
"""v4 AI 味审计（Phase A）

按《DSH优化交接文档-v4增补》A 部分实现 17 个指标里的 A/B/D 组，
但作为"编辑模式只报告"层接进现有引擎：

- 高精度信号 W2/W4 产出段级/章末 finding；
- S1–S8、W1–W3 只做章级统计，进 report["audit"]，不进评分、不硬卡；
- W5/H1 未启用（缺 aliases / 编辑模式无生成）；
- 阈值、词表全部来自 rules/ai-flavor.json，可替换；
- 每本书的基线存 rules/ai-flavor-baseline.json，首次扫描自动生成。

generate 模式（v4 硬卡、红段整章挂起、±5% 篇幅、双检）等拿到 v3 再接。
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from pathlib import Path

from .model import Book, cjk_count, dialogue_spans, file_sha256, split_sentences
from .rules import Rules
from .scanners import make_finding
from .store import now_iso, read_json, write_json

S3_RE = re.compile(r"他[^，。]{1,4}了一下")
S6_RE = re.compile(
    r"[^\s，。！？：“”「」『』]{2,6}[、，][^\s，。！？：“”「」『』]{2,6}[、，和与及][^\s，。！？：“”「」『』]{2,6}"
)
S7_RE = re.compile(r"不[只仅是][^。]{0,20}(?:而是|更是|而且)")
OPEN_PREFIX_RE = re.compile(r"^[“”‘’「」『』\s]+")

DEFAULT_WORDS = {
    "transition": ["然而", "于是", "不禁", "仿佛", "竟然", "此外", "值得注意的是", "显然", "不由得", "顿时"],
    "grandeur": ["标志着", "见证了", "体现了", "证明了", "至关重要", "关键转折点", "不可磨灭",
                  "深深植根于", "彰显了", "象征着", "反映了"],
    "promo": ["充满活力", "令人叹为观止", "开创性", "极致", "震撼", "史诗级"],
    "hollow_ending": ["未来可期", "一切才刚刚开始", "故事还在继续", "等待着他的", "无人知晓", "谁也不知道"],
    "user_blacklist": [],
    "user_whitelist": [],
}

DEFAULT_METRICS = {
    "S1": {"group": "A", "name": "短句密度", "unit": "ratio", "default": {"green_max": 0.35, "yellow_max": 0.50}},
    "S2": {"group": "A", "name": "句长方差", "unit": "std", "default": {"green_min": 6.0, "yellow_min": 4.0}},
    "S3": {"group": "A", "name": "「他X了一下」", "unit": "per_k", "default": {"green_max": 1.0, "yellow_max": 2.5}},
    "S4": {"group": "A", "name": "段首同头率", "unit": "ratio", "default": {"green_max": 0.20, "yellow_max": 0.35}},
    "S5": {"group": "A", "name": "破折号密度", "unit": "per_k", "default": {"green_max": 1.5, "yellow_max": 3.0}},
    "S6": {"group": "A", "name": "三段式堆砌", "unit": "per_chapter", "default": {"green_max": 3, "yellow_max": 6}},
    "S7": {"group": "A", "name": "否定式排比", "unit": "per_chapter", "default": {"green_max": 1, "yellow_max": 2}},
    "S8": {"group": "A", "name": "对白比偏离", "unit": "ratio", "default": {"green_max": 0.10, "yellow_max": 0.20}},
    "W1": {"group": "B", "name": "过渡词密度", "unit": "per_k", "default": {"green_max": 2.0, "yellow_max": 4.0}},
    "W2": {"group": "B", "name": "意义拔高词密度", "unit": "per_k", "default": {"green_max": 0.8, "yellow_max": 2.0}},
    "W3": {"group": "B", "name": "宣传式形容词密度", "unit": "per_k", "default": {"green_max": 1.0, "yellow_max": 2.5}},
    "W4": {"group": "B", "name": "空泛结尾", "unit": "count", "default": {"green_max": 0, "yellow_max": 1}},
}

DEFAULT_POLICY = {
    "edit_mode": "report_only",
    "hard_metrics": ["W2", "W4"],
    "summary": "编辑模式：v4 指标只报告，不作为升格硬门禁。",
}

ZONE_LABEL = {"green": "绿", "yellow": "黄", "red": "红"}


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(rules: Rules) -> dict:
    cfg = dict(rules.ai_flavor or {})
    cfg["words"] = _merge(DEFAULT_WORDS, cfg.get("words") or {})
    cfg["metrics"] = _merge(DEFAULT_METRICS, cfg.get("metrics") or {})
    cfg["policy"] = _merge(DEFAULT_POLICY, cfg.get("policy") or {})
    cfg.setdefault("mode", "edit")
    return cfg


def _zone(metric: dict, value) -> str | None:
    if value is None:
        return None
    default = metric.get("default") or {}
    if "green_max" in default:
        if value <= default["green_max"]:
            return "green"
        if value <= default.get("yellow_max", default["green_max"]):
            return "yellow"
        return "red"
    if "green_min" in default:
        if value >= default["green_min"]:
            return "green"
        if value >= default.get("yellow_min", default["green_min"]):
            return "yellow"
        return "red"
    return None


def _words(cfg: dict) -> dict[str, list[str]]:
    words = dict(cfg["words"])
    blacklist = [w for w in words.get("user_blacklist") or [] if w]
    whitelist = set(words.get("user_whitelist") or [])

    def combine(key: str) -> list[str]:
        items = [w for w in (words.get(key) or []) if w and w not in whitelist]
        for extra in blacklist:
            if extra not in items and extra not in whitelist:
                items.append(extra)
        return items

    return {
        "transition": combine("transition"),
        "grandeur": combine("grandeur"),
        "promo": combine("promo"),
        "hollow_ending": combine("hollow_ending"),
    }


def _chapter_stats(book: Book, cfg: dict) -> list[dict]:
    words = _words(cfg)
    rows: list[dict] = []
    for ch in book.chapters:
        sents: list[str] = []
        para_short_ratios: list[float] = []
        openings: list[str] = []
        for para in ch.paragraphs:
            parsed = split_sentences(para.text)
            if not parsed:
                continue
            sents.extend(parsed)
            para_short_ratios.append(sum(1 for s in parsed if cjk_count(s) <= 8) / len(parsed))
            openings.append(OPEN_PREFIX_RE.sub("", parsed[0])[:2])

        lens = [cjk_count(s) for s in sents]
        pairs = len(openings) - 1
        same_open = sum(1 for a, b in zip(openings, openings[1:]) if a and a == b)
        dialogue = sum(cjk_count(para.text[s:e]) for para in ch.paragraphs for s, e in dialogue_spans(para.text))
        last3 = "".join(para.text for para in ch.paragraphs[-3:])
        rows.append({
            "chapter": ch.index,
            "title": ch.title,
            "cjk": ch.cjk,
            "s1": statistics.mean(para_short_ratios) if para_short_ratios else 0.0,
            "s2": statistics.pstdev(lens) if len(lens) > 1 else 0.0,
            "s3_hits": len(S3_RE.findall(ch.text)),
            "s4": (same_open / pairs) if pairs > 0 else 0.0,
            "s5_hits": ch.text.count("——"),
            "s6": len(S6_RE.findall(ch.text)),
            "s7": len(S7_RE.findall(ch.text)),
            "dialogue_ratio": dialogue / (ch.cjk or 1),
            "w1_hits": sum(ch.text.count(w) for w in words["transition"]),
            "w2_hits": sum(ch.text.count(w) for w in words["grandeur"]),
            "w3_hits": sum(ch.text.count(w) for w in words["promo"]),
            "w4": sum(1 for w in words["hollow_ending"] if w in last3),
        })
    return rows


def _assemble(book: Book, cfg: dict, rows: list[dict]) -> dict:
    """把逐章原始计数组装成带单位、带区间的指标表。"""
    total_cjk = sum(r["cjk"] for r in rows) or 1

    def per_k(key: str) -> float:
        return sum(r[key] for r in rows) / total_cjk * 1000

    def weighted(key: str) -> float:
        return sum(r[key] * r["cjk"] for r in rows) / total_cjk

    def mean_count(key: str) -> float:
        return statistics.mean(r[key] for r in rows) if rows else 0.0

    # S8：与最近 10 章滚动均值的绝对偏差；不足 10 章用全书均值
    raw_ratios = [r["dialogue_ratio"] for r in rows]
    global_mean = statistics.mean(raw_ratios) if raw_ratios else 0.0
    for i, row in enumerate(rows):
        reference = global_mean if i < 10 else statistics.mean(raw_ratios[i - 10 : i])
        row["s8"] = abs(row["dialogue_ratio"] - reference)

    book_values = {
        "S1": weighted("s1"),
        "S2": weighted("s2"),
        "S3": per_k("s3_hits"),
        "S4": weighted("s4"),
        "S5": per_k("s5_hits"),
        "S6": mean_count("s6"),
        "S7": mean_count("s7"),
        "S8": statistics.mean(r["s8"] for r in rows) if rows else 0.0,
        "W1": per_k("w1_hits"),
        "W2": per_k("w2_hits"),
        "W3": per_k("w3_hits"),
        "W4": mean_count("w4"),
    }

    metrics = cfg["metrics"]
    chapter_rows: list[dict] = []
    zone_counts: dict[str, Counter] = {mid: Counter() for mid in metrics}
    for row in rows:
        values = {
            "S1": row["s1"], "S2": row["s2"], "S3": row["s3_hits"] / (row["cjk"] or 1) * 1000,
            "S4": row["s4"], "S5": row["s5_hits"] / (row["cjk"] or 1) * 1000,
            "S6": row["s6"], "S7": row["s7"], "S8": row["s8"],
            "W1": row["w1_hits"] / (row["cjk"] or 1) * 1000,
            "W2": row["w2_hits"] / (row["cjk"] or 1) * 1000,
            "W3": row["w3_hits"] / (row["cjk"] or 1) * 1000,
            "W4": row["w4"],
        }
        zones = {}
        for mid, metric in metrics.items():
            if mid in values:
                zone = _zone(metric, values[mid])
                zones[mid] = zone
                if zone:
                    zone_counts[mid][zone] += 1
        chapter_rows.append({
            "chapter": row["chapter"],
            "title": row["title"],
            "cjk": row["cjk"],
            "values": {mid: _round(values[mid], metrics[mid].get("unit")) for mid in values if mid in metrics},
            "zones": zones,
        })

    return {
        "book_values": {mid: _round(value, metrics[mid].get("unit")) for mid, value in book_values.items()},
        "raw_book_values": book_values,
        "chapters": chapter_rows,
        "zone_counts": {mid: dict(counter) for mid, counter in zone_counts.items()},
    }


def _round(value: float, unit: str | None) -> float:
    if unit == "ratio":
        return round(value, 3)
    if unit == "per_k":
        return round(value, 2)
    if unit == "std":
        return round(value, 1)
    return round(value, 2)


def _findings(book: Book, cfg: dict, audit_notes: list[str]) -> list[dict]:
    words = _words(cfg)
    metrics = cfg["metrics"]
    out: list[dict] = []

    for ch in book.chapters:
        for para in ch.paragraphs:
            text = para.text
            for metric_id, word_key, label, severity, suggestion in (
                ("W2", "grandeur", "意义拔高词", metrics["W2"].get("severity", "warn"),
                 "降低判断强度，保留原判断；不要拔高成宏大意义。"),
                ("W3", "promo", "宣传式形容词", metrics["W3"].get("severity", "info"),
                 "删掉宣传词，换成具体可见的细节。"),
            ):
                if metrics[metric_id].get("enabled", True) is False:
                    continue      # 用户关掉的指标不再产出 findings
                hits = [w for w in words[word_key] if w in text]
                if not hits:
                    continue
                out.append(make_finding(
                    rule=f"audit.{metric_id}", category="AI 味审计", severity=severity,
                    chapter=ch.index, para=para.index_in_chapter, paragraph=text,
                    quote=text,
                    why=f"{label}：{'、'.join(hits)}。这是 v4 审计里的高精度信号。",
                    suggestion=suggestion, action="flag", confidence="high",
                    meta={"audit": True, "metric": metric_id, "hits": hits},
                ))

            s3_hits = S3_RE.findall(text)
            if metrics["S3"].get("enabled", True) is not False and len(s3_hits) >= int(metrics["S3"].get("min_per_para", 2)):
                out.append(make_finding(
                    rule="audit.S3", category="AI 味审计",
                    severity=metrics["S3"].get("severity", "info"),
                    chapter=ch.index, para=para.index_in_chapter, paragraph=text, quote=text,
                    why=f"「他X了一下」在单段出现 {len(s3_hits)} 次，句式机械感偏高。",
                    suggestion="保留一处，其余换成具体动作或直接叙述。", action="flag",
                    confidence="medium", meta={"audit": True, "metric": "S3", "hits": s3_hits},
                ))

        # W4：章末 3 段
        last_paras = ch.paragraphs[-3:] if metrics["W4"].get("enabled", True) is not False else []
        for para in last_paras:
            hits = [w for w in words["hollow_ending"] if w in para.text]
            if hits:
                out.append(make_finding(
                    rule="audit.W4", category="AI 味审计",
                    severity=metrics["W4"].get("severity", "warn"),
                    chapter=ch.index, para=para.index_in_chapter, paragraph=para.text,
                    quote=para.text,
                    why=f"章末出现空泛结尾词：{'、'.join(hits)}。",
                    suggestion="换成一个具体动作、决定或新信息收尾。", action="flag",
                    confidence="high", meta={"audit": True, "metric": "W4", "hits": hits},
                ))
    return out


def _baseline(project_dir: Path, book: Book, assembled: dict, cfg: dict) -> tuple[dict, str, Path]:
    path = project_dir / "rules" / "ai-flavor-baseline.json"
    existing = read_json(path, None)
    draft_path = Path(book.path)
    try:
        digest = file_sha256(draft_path)
    except OSError:
        digest = ""
    if existing:
        return existing, "file", path
    baseline = {
        "version": 1,
        "generated_at": now_iso(),
        "draft_sha256": digest,
        "draft_path": str(draft_path),
        "book_values": assembled["book_values"],
        "chapters": [
            {
                "chapter": row["chapter"],
                "values": {
                    mid: row["values"].get(mid)
                    for mid in ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "W1", "W2", "W3", "W4")
                    if mid in row["values"]
                },
            }
            for row in assembled["chapters"]
        ],
        "words_digest": _digest(cfg["words"]),
        "note": "首次扫描自动生成：以当前主稿作为本书基线。新稿对比用。",
    }
    write_json(path, baseline)
    return baseline, "created", path


def _digest(value) -> str:
    import hashlib
    import json

    return hashlib.sha1(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def audit_summary(book: Book, rules: Rules) -> dict:
    """供 verify / 工具使用的轻量审计摘要（不写基线、不改 scan）。"""
    cfg = load_config(rules)
    rows = _chapter_stats(book, cfg)
    assembled = _assemble(book, cfg, rows)
    findings = _findings(book, cfg, [])
    by_metric: dict[str, int] = {}
    for finding in findings:
        metric = (finding.get("meta") or {}).get("metric")
        if metric:
            by_metric[metric] = by_metric.get(metric, 0) + 1
    return {
        "mode": cfg.get("mode", "edit"),
        "book_values": assembled["book_values"],
        "zone_counts": assembled["zone_counts"],
        "findings": findings,
        "by_metric": by_metric,
    }


def attach(project_dir: str | Path, book: Book, rules: Rules, scan: dict) -> dict:
    """计算 v4 审计，追加段级 findings，写入 scan["audit"]。返回 audit 包。"""
    project_dir = Path(project_dir)
    cfg = load_config(rules)
    rows = _chapter_stats(book, cfg)
    assembled = _assemble(book, cfg, rows)
    baseline, baseline_status, baseline_path = _baseline(project_dir, book, assembled, cfg)
    metrics = cfg["metrics"]

    audit_metrics: list[dict] = []
    for mid, metric in metrics.items():
        enabled = metric.get("enabled", True) is not False
        book_value = assembled["book_values"].get(mid)
        baseline_value = None
        deviation_pct = None
        if enabled and baseline and baseline.get("book_values"):
            baseline_value = baseline["book_values"].get(mid)
            if baseline_value not in (None, 0) and book_value is not None:
                deviation_pct = round((book_value - float(baseline_value)) / float(baseline_value) * 100, 1)
        zone_counts = assembled["zone_counts"].get(mid, {})
        audit_metrics.append({
            "id": mid,
            "group": metric.get("group", ""),
            "name": metric.get("name", mid),
            "unit": metric.get("unit"),
            "aggregate": metric.get("aggregate"),
            "enabled": enabled,
            "book_value": book_value,
            "baseline_value": baseline_value,
            "deviation_pct": deviation_pct,
            "default_zones": {
                "green": zone_counts.get("green", 0),
                "yellow": zone_counts.get("yellow", 0),
                "red": zone_counts.get("red", 0),
            },
            "policy": "warn" if mid in (cfg["policy"].get("hard_metrics") or []) else ("disabled" if not enabled else "report_only"),
            "note": metric.get("note", ""),
        })

    notes: list[str] = []
    s1_zones = assembled["zone_counts"].get("S1", {})
    if s1_zones.get("yellow", 0) + s1_zones.get("red", 0) > 8:
        notes.append(
            f"S1 短句密度：默认阈值下 {s1_zones.get('yellow', 0)} 黄 / {s1_zones.get('red', 0)} 红——本书短句是作者语感，默认线仅作 AI 生成参考。"
        )
    s5_zones = assembled["zone_counts"].get("S5", {})
    if s5_zones.get("yellow", 0) + s5_zones.get("red", 0) > 5:
        notes.append(
            f"S5 破折号：默认阈值下 {s5_zones.get('yellow', 0)} 黄 / {s5_zones.get('red', 0)} 红——本书作者常用「——」，不按此改。"
        )
    s6_zones = assembled["zone_counts"].get("S6", {})
    if s6_zones.get("red", 0) >= 20:
        notes.append(
            f"S6 三段式：默认正则命中 {s6_zones.get('red', 0)} 章红、{s6_zones.get('green', 0)} 章绿——它把普通排比/对白也算进去了，v4 原正则不建议直接作门禁。"
        )
    if metrics.get("W5", {}).get("enabled", True) is False:
        notes.append("W5 同义词循环未启用：需要角色 aliases；补齐后可开启。")
    if metrics.get("H1", {}).get("enabled", True) is False:
        notes.append("H1 human_edit_ratio 未启用：编辑模式没有 AI 生成字数；generate 模式再启用。")

    if baseline_status == "created":
        notes.append("第一次运行：已用当前主稿生成本书 AI 味基线（rules/ai-flavor-baseline.json）。")
    else:
        if baseline.get("draft_sha256") and baseline["draft_sha256"] != (file_sha256(Path(book.path)) if Path(book.path).exists() else ""):
            notes.append("主稿已变化：当前稿与基线 hash 不同；偏差列可用于观察改动影响。")

    findings = _findings(book, cfg, notes)

    audit = {
        "profile": cfg.get("mode", "edit"),
        "engine": "v4-a.1-phaseA",
        "policy": cfg["policy"],
        "baseline": {
            "status": baseline_status,
            "path": str(baseline_path),
            "draft_sha256": baseline.get("draft_sha256"),
            "generated_at": baseline.get("generated_at"),
            "words_digest": baseline.get("words_digest"),
        },
        "words_digest": _digest(cfg["words"]),
        "metrics": audit_metrics,
        "chapters": assembled["chapters"],
        "findings": [
            {"id": f["id"], "rule": f["rule"], "severity": f["severity"], "chapter": f["chapter"], "para": f["para"]}
            for f in findings
        ],
        "notes": notes,
    }

    # 并入扫描结果
    order = {"hard": 0, "warn": 1, "info": 2}
    scan["findings"].extend(findings)
    scan["findings"].sort(key=lambda f: (order.get(f["severity"], 3), f["chapter"], f["para"], f["rule"]))
    scan["audit"] = audit
    scan["stats"]["findings"] = len(scan["findings"])
    scan["stats"]["audit_findings"] = len(findings)
    scan["stats"]["candidates"] = sum(1 for f in scan["findings"] if not (f.get("meta") or {}).get("audit"))

    # 更新章级计数
    by_ch: dict[int, list[dict]] = {}
    for finding in scan["findings"]:
        by_ch.setdefault(finding["chapter"], []).append(finding)
    for card in scan.get("chapters", []):
        items = by_ch.get(card["index"], [])
        card["findings"] = len(items)
        card["severity_counts"] = {
            "hard": sum(1 for f in items if f["severity"] == "hard"),
            "warn": sum(1 for f in items if f["severity"] == "warn"),
            "info": sum(1 for f in items if f["severity"] == "info"),
        }
    return {"audit": audit, "findings": findings}

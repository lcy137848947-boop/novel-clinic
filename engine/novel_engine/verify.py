# -*- coding: utf-8 -*-
"""改后门禁：硬指标必须过；文风只报警告。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .model import cjk_count, load_book
from .rules import Rules
from .scanners import straight_quote_count
from . import aiflavor


def _dup_paragraphs(book, rules: Rules) -> list[str]:
    texts = [p.text for p in book.paragraphs if len(p.text) >= 12]
    dup = [t for t, n in Counter(texts).items() if n > 1 and not rules.allowed(t)]
    return dup


def verify_book(
    *,
    baseline_path: str | Path,
    draft_path: str | Path,
    cfg: dict,
    rules: Rules,
    expected_delta: int | None = None,
    applied_ops: list[dict] | None = None,
) -> dict:
    base = load_book(baseline_path, rules.chapter_pattern, cfg.get("title"), cfg.get("subtitle"))
    draft = load_book(draft_path, rules.chapter_pattern, cfg.get("title"), cfg.get("subtitle"))
    gates: list[dict] = []

    def gate(gid: str, name: str, status: str, detail: str):
        gates.append({"id": gid, "name": name, "status": status, "detail": detail})

    # 章结构
    if len(base.chapters) != len(draft.chapters):
        gate("chapters", "章数不变", "fail", f"{len(base.chapters)} → {len(draft.chapters)}")
    elif [c.title for c in base.chapters] != [c.title for c in draft.chapters]:
        gate("chapters", "章标题不变", "fail", "章标题序列发生变化")
    else:
        gate("chapters", "章数 / 章标题", "pass", f"{len(draft.chapters)} 章")

    # 空章
    empty = [c.index for c in draft.chapters if not c.paragraphs]
    gate("empty", "无空章", "fail" if empty else "pass", f"空章：{empty}" if empty else "无")

    # 禁用词
    banned_hits = []
    for ch in draft.chapters:
        for p in ch.paragraphs:
            for b in rules.banned:
                term = b.get("term")
                if term and term in p.text:
                    banned_hits.append({"chapter": ch.index, "para": p.index_in_chapter + 1, "term": term})
    gate("banned", "禁用词为 0", "fail" if banned_hits else "pass",
         f"命中 {len(banned_hits)} 处" if banned_hits else "0 处")

    # 直引号（与 scanners.has_straight_quote 同一口径：英文撇号不算）
    text = draft.text
    sq = straight_quote_count(text)
    gate("quotes", "直引号为 0", "fail" if sq else "pass", f"{sq} 处" if sq else "0 处")

    # 重复长段
    dup = _dup_paragraphs(draft, rules)
    gate("duplicates", "无未授权的重复长段", "fail" if dup else "pass",
         f"{len(dup)} 处" if dup else "0 处")

    # 字数变化与预期一致
    actual_delta = draft.cjk - base.cjk
    if expected_delta is None:
        gate("delta", "字数变化可解释", "pass", f"{actual_delta:+d} 字（未提供预期值）")
    elif actual_delta == expected_delta:
        gate("delta", "字数变化与改动一致", "pass", f"{actual_delta:+d} 字")
    else:
        gate("delta", "字数变化与改动一致", "fail", f"实际 {actual_delta:+d}，预期 {expected_delta:+d}")

    # 已批改动都在
    applied = applied_ops or []
    missing = []
    for op in applied:
        ch = draft.chapter(op["chapter"])
        if ch is None:
            missing.append({"id": op["id"], "reason": "章不存在"})
            continue
        if op["kind"] == "replace":
            if op["after"] not in [p.text for p in ch.paragraphs]:
                missing.append({"id": op["id"], "reason": "替换文本未出现在新稿"})
        else:
            if op["before"] in [p.text for p in ch.paragraphs]:
                missing.append({"id": op["id"], "reason": "待删段落仍在"})
    gate("applied", "已批改动全部生效", "fail" if missing else "pass",
         f"缺失 {len(missing)} 条" if missing else f"{len(applied)} 条全部生效")

    # 文风保真（仅警告）
    after_counts = {"image": text.count("像"), "sisi": text.count("死死"), "mengdi": text.count("猛地"),
                    "huran": text.count("忽然")}
    cjk = draft.cjk or 1
    image_per_10k = round(after_counts["image"] / cjk * 10000, 1)
    voice = rules.voice or {}
    tol = float(rules.thresholds.get("voice_tolerance_pct", 10.0))
    voice_warnings = []
    base_image = voice.get("image_per_10k")
    if base_image:
        pct = (image_per_10k - float(base_image)) / float(base_image) * 100
        if abs(pct) > tol:
            voice_warnings.append(f"像/万字 {image_per_10k}，基线 {base_image}（{pct:+.1f}%）")
    for key, label, base_key in (("sisi", "死死", "sisi"), ("mengdi", "猛地", "mengdi")):
        base_v = voice.get(base_key)
        if base_v:
            pct = (after_counts[key] - float(base_v)) / float(base_v) * 100
            if abs(pct) > tol:
                voice_warnings.append(f"{label} {after_counts[key]}，基线 {base_v}（{pct:+.1f}%）")
    gate("voice", "文风指纹未漂移", "warn" if voice_warnings else "pass",
         "；".join(voice_warnings) if voice_warnings else f"像/万字 {image_per_10k}，与基线一致")

    # v4 AI 味审计（编辑模式只提醒；generate 模式等 v3 再硬卡）
    audit_summary = None
    try:
        summary = aiflavor.audit_summary(draft, rules)
        mode = summary.get("mode", "edit")
        warn_count = len([f for f in summary["findings"] if (f.get("meta") or {}).get("metric") in ("W2", "W4")])
        if warn_count:
            gate("audit", "AI 味审计（W2/W4）", "warn" if mode == "edit" else "fail",
                 f"W2/W4 段级告警 {warn_count} 条（{'编辑模式只提醒' if mode == 'edit' else '生成模式硬卡'}）")
        else:
            gate("audit", "AI 味审计（W2/W4）", "pass", "W2/W4 段级告警 0 条")
        audit_summary = {
            "mode": mode,
            "book_values": summary["book_values"],
            "by_metric": summary["by_metric"],
            "findings": [
                {"rule": f.get("rule"), "chapter": f.get("chapter"), "para": f.get("para"),
                 "severity": f.get("severity"), "why": f.get("why")}
                for f in summary["findings"]
            ],
        }
    except Exception as error:  # noqa: BLE001
        gate("audit", "AI 味审计（W2/W4）", "warn", f"审计计算失败：{type(error).__name__}: {error}")

    hard_fail = [g for g in gates if g["status"] == "fail"]
    return {
        "pass": not hard_fail,
        "gates": gates,
        "failures": hard_fail,
        "warnings": [g for g in gates if g["status"] == "warn"],
        "stats_before": {"cjk": base.cjk, "chapters": len(base.chapters), "paragraphs": len(base.paragraphs)},
        "stats_after": {"cjk": draft.cjk, "chapters": len(draft.chapters), "paragraphs": len(draft.paragraphs)},
        "image_per_10k": image_per_10k,
        "audit": audit_summary,
    }

# -*- coding: utf-8 -*-
"""透明的编辑健康度评分。权重和阈值全部可解释，不追求"平台分"。"""
from __future__ import annotations

from .rules import Rules

WEIGHTS = {
    "hard": 0.25,
    "consistency": 0.15,
    "duplication": 0.15,
    "aiflavor": 0.20,
    "pacing": 0.15,
    "voice": 0.10,
}

DIMENSION_NAMES = {
    "hard": "硬门禁",
    "consistency": "设定一致性",
    "duplication": "重复冗余",
    "aiflavor": "AI 腔",
    "pacing": "节奏与钩子",
    "voice": "文风保真",
}


def _by_cat(findings: list[dict], cat: str) -> list[dict]:
    # 硬伤只在 hard 维度算一次，分类维度里不再重复扣
    return [f for f in findings if f.get("category") == cat and f.get("severity") != "hard"]


def _penalty(items: list[dict], warn: float, info: float, hard: float = 0) -> float:
    p = 0.0
    for f in items:
        sev = f.get("severity")
        p += hard if sev == "hard" else warn if sev == "warn" else info
    return p


def _grade(total: float) -> str:
    if total >= 90:
        return "A"
    if total >= 80:
        return "B+"
    if total >= 70:
        return "B"
    if total >= 60:
        return "C"
    return "D"


def compute_score(scan: dict, rules: Rules) -> dict:
    findings = scan["findings"]
    chapters = scan["chapters"]
    metrics = scan["metrics"]

    # 硬伤维度按 category 收全部（hard / warn / info）：
    # 否则 quote_unbalanced 这类「硬伤 + info」不进 hard、也不进 _by_cat，哪个维度都不扣分。
    hard_items = [f for f in findings if f["category"] == "硬伤"]
    hard_warn_items = [f for f in hard_items if f["severity"] == "warn"]
    hard_info_items = [f for f in hard_items if f["severity"] == "info"]
    consistency_items = _by_cat(findings, "设定")
    dup_items = _by_cat(findings, "重复")
    ai_items = _by_cat(findings, "AI 腔")
    pace_items = _by_cat(findings, "节奏")

    # #10 硬伤按“能不能一键修”分档：可自动修 2 分/条，不可修 20 分/条
    hard_penalty = sum(2.0 if f.get("auto_fixable") else 20.0
                       for f in hard_items if f["severity"] == "hard")
    hard_penalty += 2.0 * len(hard_warn_items)      # 硬伤类 warn：每条 2 分
    hard_penalty += 0.5 * len(hard_info_items)      # 硬伤类 info（引号不平衡等）：每条 0.5 分
    scores = {
        "hard": max(0.0, 100 - hard_penalty),
        "consistency": (max(0.0, 100 - _penalty(consistency_items, 12, 2, 20))
                        if (rules.facts or consistency_items) else None),   # #7 没配置 = 未测
        "duplication": max(0.0, 100 - _penalty(dup_items, 8, 1, 20)),
        "aiflavor": max(0.0, 100 - _penalty(ai_items, 6, 1, 20)),
    }

    hook_scores = [c["hook"]["score"] for c in chapters if c.get("hook")]
    avg_hook = sum(hook_scores) / len(hook_scores) if hook_scores else 100.0
    weak = sum(1 for s in hook_scores if s < 45)
    scores["pacing"] = max(0.0, min(100.0, avg_hook - weak * 2))

    baseline = (rules.voice or {})
    tol = float(rules.thresholds.get("voice_tolerance_pct", 10.0))
    voice_penalty = 0.0
    voice_details: list[str] = []
    for key, dev in (metrics.get("deviations") or {}).items():
        pct = abs(dev.get("pct") or 0)
        if pct > tol:
            voice_penalty += min(30.0, (pct - tol) * 1.2)
            voice_details.append(f"{dev['label']} 偏离基线 {dev['pct']:+.1f}%")
    if not any(baseline.get(k) is not None for k in ("image_per_10k", "sisi", "mengdi", "huran")):
        scores["voice"] = None          # #7 没基线 = 未测，不给 90 分白送
        voice_details.append("尚未设置文风基线（未测，不计入总分）")
    else:
        scores["voice"] = max(0.0, 100 - voice_penalty)

    # #7 未测维度从权重分母里剔除后重归一化，并在报告里标出覆盖率
    measured = {k: v for k, v in scores.items() if v is not None}
    wsum = sum(WEIGHTS[k] for k in measured) or 1.0
    total = sum(measured[k] * WEIGHTS[k] for k in measured) / wsum
    unmeasured = [DIMENSION_NAMES[k] for k in scores if scores[k] is None]
    coverage = {"measured": len(measured), "total": len(scores), "missing": unmeasured}

    dims = []
    for key, name in DIMENSION_NAMES.items():
        detail = {
            "hard": f"硬伤 {len(hard_items)} 条",
            "consistency": f"设定类问题 {len(consistency_items)} 条",
            "duplication": f"重复类 {len(dup_items)} 条",
            "aiflavor": f"AI 腔 {len(ai_items)} 条",
            "pacing": f"章末钩子平均 {avg_hook:.0f} 分，弱钩子 {weak} 章",
            "voice": "；".join(voice_details) if voice_details else "与基线一致",
        }[key]
        dims.append({
            "id": key,
            "name": name,
            "score": round(scores[key], 1) if scores[key] is not None else None,
            "weight": WEIGHTS[key],
            "measured": scores[key] is not None,
            "detail": detail if scores[key] is not None else "未配置，未计入总分",
        })

    weak_chapters = [
        {"index": c["index"], "title": c["title"], "score": c["hook"]["score"], "reasons": c["hook"]["reasons"]}
        for c in chapters if c["hook"]["score"] < 45
    ]

    candidates = [f for f in findings if not (f.get("meta") or {}).get("audit")]
    audit_count = len(findings) - len(candidates)
    return {
        "total": round(total, 1),
        "grade": _grade(total),
        "dimensions": dims,
        "weak_hooks": weak_chapters,
        "coverage": coverage,
        "summary": _summary(total, scores, len(hard_items), len(candidates), audit_count, coverage),
    }


def _summary(total: float, scores: dict, hard: int, findings: int, audit_count: int = 0,
             coverage: dict | None = None) -> str:
    parts = [f"编辑健康度 {total:.1f} 分。"]
    if coverage and coverage["missing"]:
        parts.append("已测 %d/%d 维（%s 未配置，未计入）。"
                     % (coverage["measured"], coverage["total"], "、".join(coverage["missing"])))
    if hard:
        parts.append(f"硬伤 {hard} 条必须先处理。")
    weak = [DIMENSION_NAMES[k] for k in ("pacing", "aiflavor", "duplication")
            if scores[k] is not None and scores[k] < 80]
    if weak:
        parts.append("低于 80 分的维度：" + "、".join(weak) + "。")
    parts.append(f"共生成 {findings} 条候选项，逐条勾选后再动稿。")
    if audit_count:
        parts.append(f"另有 {audit_count} 条 AI 味审计告警（编辑模式只报告）。")
    return "".join(parts)

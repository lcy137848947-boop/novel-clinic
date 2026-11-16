# -*- coding: utf-8 -*-
"""P2 文风调性（style register）引擎。

- learn：用作者认可的样本学一个"文风指纹"（样本互测一致性 + 特征均值/方差）
- check：任意文本/段落/章节对样本的"粘性"（0–100，可解释到每个特征）
- 只做检测与报告；改写仍走 A.6（diff/提案/审批）

设计原则：特征与内容无关（句长、标点、对白比、意象/感官/抽象词密度等），
不比对原文词句，避免"像 = 抄"；粘性只表示风格贴合，不代表内容正确。
"""
from __future__ import annotations

import hashlib
import math
import re
import shutil
import statistics
from pathlib import Path

from .model import cjk_count, dialogue_spans, load_book, split_sentences
from .rules import load_project, load_rules
from .store import now_iso, read_json, write_json

STYLE_DIR = "styles"
PROFILE_FILE = "profile.json"

COLOR_CHARS = "红橙黄绿青蓝紫黑白灰金银暗亮"
SENSE_CHARS = "冷热烫凉暖疼痛痒湿干香臭腥甜苦咸声听看闻"
NATURE_CHARS = "星云海风雷雨雪月日山塔光雾霜潮"
IMAGE_WORDS = ["像", "仿佛", "好像", "如同", "似的", "宛如"]
JUDGMENT_WORDS = ["意味着", "说明", "证明", "其实", "本来", "显然", "可见", "所谓", "也就是说", "换句话说"]
ABSTRACT_WORDS = ["命运", "宿命", "意义", "存在", "永恒", "孤独", "救赎", "真相", "答案", "注定", "终究", "世界", "一切", "自由"]
ADVERB_WORDS = ["很", "非常", "极", "太", "更", "最", "十分", "格外", "特别", "几乎", "简直"]
CLASSICAL_WORDS = ["之", "其", "亦", "矣", "焉", "兮", "乃", "若", "于", "而"]

FEATURES = [
    "sent_mean", "sent_std", "short_ratio", "para_mean", "dialogue_ratio",
    "image_per_k", "color_per_k", "sense_per_k", "nature_per_k",
    "abstract_per_k", "judgment_per_k", "adverb_per_k", "classical_per_k",
    "dash_per_k", "ellipsis_per_k", "question_ratio", "exclaim_ratio", "comma_per_sent",
]

FEATURE_LABELS = {
    "sent_mean": "平均句长",
    "sent_std": "句长波动",
    "short_ratio": "短句占比",
    "para_mean": "平均段长",
    "dialogue_ratio": "对白占比",
    "image_per_k": "比喻/像密度",
    "color_per_k": "颜色词密度",
    "sense_per_k": "感官词密度",
    "nature_per_k": "自然意象密度",
    "abstract_per_k": "抽象词密度",
    "judgment_per_k": "判断句密度",
    "adverb_per_k": "程度副词密度",
    "classical_per_k": "古风虚词密度",
    "dash_per_k": "破折号密度",
    "ellipsis_per_k": "省略号密度",
    "question_ratio": "疑问句占比",
    "exclaim_ratio": "感叹句占比",
    "comma_per_sent": "逗号/句",
}


def styles_root(project_dir: str | Path) -> Path:
    return Path(project_dir) / STYLE_DIR


def profile_dir(project_dir: str | Path, name: str) -> Path:
    return styles_root(project_dir) / name


def profile_path(project_dir: str | Path, name: str) -> Path:
    return profile_dir(project_dir, name) / PROFILE_FILE


def _count_chars(text: str, chars: str) -> int:
    return sum(text.count(ch) for ch in chars)


def _count_words(text: str, words: list[str]) -> int:
    return sum(text.count(word) for word in words)


def _paragraphs(text: str) -> list[str]:
    out = []
    for block in re.split(r"\n\s*\n", text):
        cleaned = []
        for line in block.splitlines():
            s = line.strip()
            if not s or s == "---" or s.startswith("#") or s.startswith("|") or s.startswith(">"):
                continue
            cleaned.append(s)
        merged = "".join(cleaned).strip()
        if cjk_count(merged) >= 8:
            out.append(merged)
    return out


def _features(text: str) -> dict:
    sents = [s for s in split_sentences(text) if cjk_count(s) > 0]
    paras = _paragraphs(text) or [text]
    cjk = cjk_count(text) or 1
    lens = [cjk_count(s) for s in sents] or [0]
    para_lens = [cjk_count(p) for p in paras] or [0]
    dialogue = sum(cjk_count(text[s:e]) for s, e in dialogue_spans(text))

    def per_k(value: int | float) -> float:
        return round(float(value) / cjk * 1000, 3)

    return {
        "sent_mean": round(statistics.mean(lens), 2),
        "sent_std": round(statistics.pstdev(lens) if len(lens) > 1 else 0.0, 2),
        "short_ratio": round(sum(1 for value in lens if value <= 8) / len(lens), 3),
        "para_mean": round(statistics.mean(para_lens), 1),
        "dialogue_ratio": round(dialogue / cjk, 3),
        "image_per_k": per_k(_count_words(text, IMAGE_WORDS)),
        "color_per_k": per_k(_count_chars(text, COLOR_CHARS)),
        "sense_per_k": per_k(_count_chars(text, SENSE_CHARS)),
        "nature_per_k": per_k(_count_chars(text, NATURE_CHARS)),
        "abstract_per_k": per_k(_count_words(text, ABSTRACT_WORDS)),
        "judgment_per_k": per_k(_count_words(text, JUDGMENT_WORDS)),
        "adverb_per_k": per_k(_count_words(text, ADVERB_WORDS)),
        "classical_per_k": per_k(_count_chars(text, CLASSICAL_WORDS)),
        "dash_per_k": per_k(text.count("——")),
        "ellipsis_per_k": per_k(text.count("……")),
        "question_ratio": round(text.count("？") / max(1, len(sents)), 3),
        "exclaim_ratio": round(text.count("！") / max(1, len(sents)), 3),
        "comma_per_sent": round(text.count("，") / max(1, len(sents)), 2),
    }


def _z(value: float, mean: float, std: float) -> float:
    scale = max(abs(std), abs(mean) * 0.25, 0.4)
    return (value - mean) / scale


def _similarity(z: float) -> float:
    return 100.0 * math.exp(-0.5 * z * z)


def _pair_similarity(a: dict, b: dict, profile: dict) -> float:
    scores = []
    for key in FEATURES:
        mean = profile["features"][key]["mean"]
        std = profile["features"][key]["std"]
        za = _z(a[key], mean, std)
        zb = _z(b[key], mean, std)
        scores.append(_similarity(abs(za - zb)))
    return round(statistics.mean(scores), 1)


def _read_sample(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        import docx

        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs if p.text.strip())
    return path.read_text(encoding="utf-8-sig")


def learn(project_dir: str | Path, name: str, sample_paths: list[str]) -> dict:
    project_dir = Path(project_dir)
    if not sample_paths:
        raise ValueError("至少给一个样本文件")
    root = profile_dir(project_dir, name)
    samples_dir = root / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    sample_records = []
    paragraph_features: list[dict] = []
    for raw in sample_paths:
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(f"样本不存在：{path}")
        text = _read_sample(path)
        paras = _paragraphs(text) or ([text] if text.strip() else [])
        if not paras:
            raise ValueError(f"样本为空：{path}")
        for paragraph in paras:
            paragraph_features.append(_features(paragraph))
        target = samples_dir / path.name
        if path.resolve() != target.resolve():
            shutil.copyfile(path, target)
        sample_records.append({
            "file": str(target),
            "name": path.name,
            "chars": cjk_count(text),
            "paragraphs": len(paras),
            "sha1": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12],
        })
    if len(paragraph_features) < 2:
        raise ValueError("样本段落太少（至少 2 段，建议 3–5 段 × 300–800 字）")
    profile_features = {}
    for key in FEATURES:
        values = [item[key] for item in paragraph_features]
        profile_features[key] = {
            "mean": round(statistics.mean(values), 4),
            "std": round(statistics.pstdev(values) if len(values) > 1 else 0.0, 4),
        }
    profile = {
        "schema": 1,
        "name": name,
        "created_at": now_iso(),
        "samples": sample_records,
        "features": profile_features,
        "features_order": FEATURES,
        "labels": FEATURE_LABELS,
        "paragraphs_learned": len(paragraph_features),
    }
    # 样本互测一致性
    sample_vectors = []
    for record in sample_records:
        text = _read_sample(Path(record["file"]))
        paras = _paragraphs(text) or [text]
        vector = {key: statistics.mean([_features(p)[key] for p in paras]) for key in FEATURES}
        sample_vectors.append(vector)
    pair_scores = []
    for i in range(len(sample_vectors)):
        for j in range(i + 1, len(sample_vectors)):
            pair_scores.append(_pair_similarity(sample_vectors[i], sample_vectors[j], profile))
    consistency = round(statistics.mean(pair_scores), 1) if pair_scores else None
    profile["sample_consistency"] = consistency
    profile["notes"] = []
    if consistency is not None and consistency < 65:
        profile["notes"].append(f"样本互测粘性只有 {consistency}，这组样本可能不是一个风格，建议补充/筛选。")
    if len(sample_records) < 3:
        profile["notes"].append("样本少于 3 个；建议按 3–5 段 × 300–800 字补充，粘性更可靠。")
    max_sample = max((record["chars"] for record in sample_records), default=0)
    if max_sample < 300:
        profile["notes"].append(f"样本偏短（最长 {max_sample} 字）；当前可做演示，正式使用建议每段 300–800 字。")
    write_json(root / PROFILE_FILE, profile)
    return {
        "ok": True,
        "profile": str(root / PROFILE_FILE),
        "name": name,
        "samples": sample_records,
        "paragraphs_learned": len(paragraph_features),
        "sample_consistency": consistency,
        "notes": profile["notes"],
        "features": {key: profile_features[key] for key in ("sent_mean", "short_ratio", "image_per_k", "sense_per_k", "dialogue_ratio")},
    }


def load_profile(project_dir: str | Path, name: str) -> dict:
    path = profile_path(project_dir, name)
    if not path.exists():
        raise FileNotFoundError(f"没有这个风格档案：{path}（先 style learn）")
    return read_json(path)


def check_text(profile: dict, text: str, source: str = "") -> dict:
    features = _features(text)
    scores = []
    details = []
    for key in FEATURES:
        mean = profile["features"][key]["mean"]
        std = profile["features"][key]["std"]
        z = _z(features[key], mean, std)
        score = _similarity(z)
        scores.append(score)
        details.append({
            "key": key,
            "label": FEATURE_LABELS.get(key, key),
            "value": features[key],
            "mean": mean,
            "z": round(z, 2),
            "score": round(score, 1),
        })
    adhesion = round(statistics.mean(scores), 1)
    verdict = "贴合" if adhesion >= 80 else "接近" if adhesion >= 65 else "混合" if adhesion >= 45 else "不像"
    weakest = sorted(details, key=lambda item: item["score"])[:5]
    return {
        "ok": True,
        "style": profile.get("name"),
        "source": source,
        "chars": cjk_count(text),
        "adhesion": adhesion,
        "verdict": verdict,
        "weakest": weakest,
        "features": details,
        "sample_consistency": profile.get("sample_consistency"),
        "note": "粘性只表示与样本的风格贴合，不代表内容正确；样本互测一致性是该档案的可信度上限。",
        "checked_at": now_iso(),
    }


def check(
    project_dir: str | Path,
    name: str,
    *,
    text: str | None = None,
    text_file: str | None = None,
    chapter: int | None = None,
    para: int | None = None,
) -> dict:
    project_dir = Path(project_dir)
    profile = load_profile(project_dir, name)
    source = ""
    if text_file:
        target = Path(text_file)
        content = target.read_text(encoding="utf-8-sig")
        source = str(target)
    elif text is not None:
        content = text
        source = "inline"
    elif chapter is not None:
        cfg = load_project(project_dir)
        rules = load_rules(project_dir, cfg)
        book = load_book(cfg["_main_draft_path"], rules.chapter_pattern, cfg.get("title"), cfg.get("subtitle"))
        ch = book.chapter(chapter)
        if not ch:
            raise ValueError(f"没有第 {chapter} 章")
        if para is not None:
            if para < 0 or para >= len(ch.paragraphs):
                raise ValueError(f"第 {chapter} 章没有第 {para + 1} 段")
            content = ch.paragraphs[para].text
            source = f"第{chapter}章·第{para + 1}段"
        else:
            content = ch.text
            source = f"第{chapter}章"
    else:
        raise ValueError("check 需要 text / text_file / chapter 之一")
    primary = check_text(profile, content, source)
    alternatives = []
    for item in list_styles(project_dir).get("styles", []):
        if item["name"] == name:
            continue
        try:
            other = check_text(load_profile(project_dir, item["name"]), content, source)
        except FileNotFoundError:
            continue
        alternatives.append({
            "style": item["name"],
            "adhesion": other["adhesion"],
            "verdict": other["verdict"],
        })
    alternatives.sort(key=lambda entry: entry["adhesion"], reverse=True)
    primary["alternatives"] = alternatives
    if alternatives:
        best_other = alternatives[0]
        margin = round(primary["adhesion"] - best_other["adhesion"], 1)
        primary["margin"] = margin
        if margin >= 5 and primary["adhesion"] >= 65:
            primary["verdict"] = f"更接近「{name}」"
        elif margin <= -5:
            primary["verdict"] = f"更接近「{best_other['style']}」"
        else:
            primary["verdict"] = "风格不明确 / 混合"
        primary["note"] = (
            f"粘性只表示与样本的风格贴合，不代表内容正确；第一名领先第二名 {margin} 分。"
            "样本互测一致性是绝对粘性的上限。"
        )
    return primary


def list_styles(project_dir: str | Path) -> dict:
    root = styles_root(project_dir)
    items = []
    if root.exists():
        for path in sorted(root.iterdir()):
            if not path.is_dir():
                continue
            profile = read_json(path / PROFILE_FILE, None)
            if not profile:
                continue
            items.append({
                "name": profile.get("name") or path.name,
                "samples": len(profile.get("samples") or []),
                "paragraphs": profile.get("paragraphs_learned"),
                "sample_consistency": profile.get("sample_consistency"),
                "created_at": profile.get("created_at"),
                "path": str(path / PROFILE_FILE),
            })
    return {"ok": True, "styles": items}

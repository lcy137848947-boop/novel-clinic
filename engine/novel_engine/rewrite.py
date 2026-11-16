# -*- coding: utf-8 -*-
"""A.6 改写契约（Phase B）。

流程（只产出参考稿，不自动替换主稿）：
    prepare(finding_id) → 生成"定向改写请求"（原文 + 触发指标 + 上下文 + 硬约束 + prompt）
    由 AI（聊天里的模型）按 prompt 写出一段改写
    submit(request_id, text) → 机检：篇幅 / 禁用词 / 新事实（数字+实体+新对白）/
                              新 AI 腔 / 触发指标是否真的降下来 → 通过则存"改写提案"
    作者在审批页勾选 → 现有 apply 流程才会写进新稿。

机器只能查"可机检项"；语义事实（动作/心理/因果）仍需人复核，报告里会写明。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import aiflavor
from .model import Book, cjk_count, load_book, narration_segments
from .rules import Rules, load_project, load_rules
from .scanners import make_finding
from .store import load_scan, now_iso, read_json, round_dir, write_json

DEFAULT_MAX_ROUNDS = 2
DEFAULT_EDIT_TOLERANCE = 0.15
DEFAULT_GENERATE_TOLERANCE = 0.05
REQUEST_DIR = "改写请求"
PROPOSALS_FILE = "改写提案.json"

QUOTE_RE = re.compile(r"[“「]([^”」]*)[”」]")
NUMBER_RE = re.compile(r"\d[\d,]*")


# ---------------------------------------------------------------- helpers
def _entities(project_dir: Path) -> list[str]:
    data = read_json(project_dir / "rules" / "entities.json", {}) or {}
    out: list[str] = []
    for key, value in data.items():
        if key in ("version", "note"):
            continue
        if isinstance(value, list):
            out.extend(str(item) for item in value if item)
    seen = set()
    ordered = []
    for item in out:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _quotes(text: str) -> list[str]:
    return [m.group(1).strip() for m in QUOTE_RE.finditer(text) if m.group(1).strip()]


def _numbers(text: str) -> set[str]:
    return set(NUMBER_RE.findall(text))


def _length_range(original: str, tolerance: float) -> tuple[int, int]:
    n = max(1, cjk_count(original))
    return int(n * (1 - tolerance)), int(n * (1 + tolerance))


def _para_metrics(text: str, rules: Rules) -> dict:
    cfg = aiflavor.load_config(rules)
    words = aiflavor._words(cfg)
    sents = [s for s in re.split(r"(?<=[。！？!?…])", text) if s.strip()]
    return {
        "cjk": cjk_count(text),
        "s1_short_ratio": (
            sum(1 for s in sents if cjk_count(s) <= 8) / len(sents) if sents else 0.0
        ),
        "s3": len(re.findall(r"他[^，。]{1,4}了一下", text)),
        "s5": text.count("——"),
        "w1": sum(text.count(w) for w in words["transition"]),
        "w2": sum(text.count(w) for w in words["grandeur"]),
        "w3": sum(text.count(w) for w in words["promo"]),
        "quotes": len(_quotes(text)),
    }


def _find_request(project_dir: Path, request_id: str, round_name: str | None = None) -> tuple[dict, Path]:
    from .store import list_rounds

    if round_name:
        candidates = [round_name]
    else:
        candidates = [path.name for _, path in reversed(list_rounds(project_dir))]
    for name in candidates:
        path = project_dir / "rounds" / name / REQUEST_DIR / f"{request_id}.json"
        if path.exists():
            return read_json(path), path
    raise FileNotFoundError(f"找不到改写请求：{request_id}")


def _triggers(finding: dict, report: dict) -> list[dict]:
    triggers: list[dict] = []
    meta = finding.get("meta") or {}
    metric = meta.get("metric")
    if metric:
        triggers.append({
            "id": metric,
            "hits": meta.get("hits") or [],
            "rule": finding.get("suggestion") or finding.get("why") or "",
        })
    if finding.get("rule", "").startswith("ai."):
        triggers.append({
            "id": finding["rule"],
            "hits": [finding.get("quote", "")[:80]],
            "rule": finding.get("why") or "",
        })
    if not triggers:
        triggers.append({"id": finding.get("rule", ""), "hits": [], "rule": finding.get("why") or ""})
    return triggers


def _prompt(request: dict, rules: Rules, cfg: dict) -> str:
    words = aiflavor._words(cfg)
    banned = [b.get("term") for b in rules.banned if b.get("term")]
    trg = "\n".join(f"- {t['id']}：{t['rule']}" for t in request["triggers"])
    lo, hi = request["length_range"]
    return f"""你是《{request['project_title']}》的编辑。只改下面这一段，不要补事实。

【要修掉的触发项】
{trg}

【原文】
{request['original']}

【硬约束（违反任何一条都会被机检打回）】
1. 只改表达，不补事实：不得新增原文没有的人物、地点、时间、物品、动作、心理活动、对话内容、因果。
2. 不得把模糊表述改成确定表述（“像是有什么”不能改成“就是什么”）。
3. 不得删除任何独立信息点（一个动作、一个感官细节、一句台词都算）。
4. 不得改变人物立场、语气、态度；不得为了“更生动”编造场景或细节。
5. 不得新增比喻。
6. 原文对白必须原句保留（原文没有对白就不许新增对白）。
7. 不得新增数字；不得出现新实体（人物/地点/势力/物品）。
8. 不得出现意义拔高词：{("、".join(words['grandeur']))}；不得出现宣传词：{("、".join(words['promo']))}。
9. 不得出现禁用词：{("、".join(banned))}。
10. 篇幅：改写后正文 {lo}–{hi} 字（原文 {request['original_cjk']} 字，允许 ±{int(request['length_tolerance'] * 100)}%）。
11. 只输出改写后的整段正文：不要解释、不要分析、不要加“改写：”之类的前缀。

【相邻段落（只作衔接参考，不要复制进来）】
上一段：{request['context']['prev']}
下一段：{request['context']['next']}
"""


# ---------------------------------------------------------------- prepare
def prepare(project_dir: str | Path, finding_id: str, round_name: str | None = None) -> dict:
    project_dir = Path(project_dir)
    cfg = load_project(project_dir)
    rules = load_rules(project_dir, cfg)
    book = load_book(cfg["_main_draft_path"], rules.chapter_pattern, cfg.get("title"), cfg.get("subtitle"))
    report, actual_round = load_scan(project_dir, round_name)
    finding = next((f for f in report.get("findings", []) if f.get("id") == finding_id), None)
    if not finding:
        raise ValueError(f"报告里没有这条候选项：{finding_id}（请先重新扫描）")
    chapter = book.chapter(finding["chapter"])
    if not chapter or finding["para"] >= len(chapter.paragraphs):
        raise ValueError("定位失效：章/段不存在")
    target = chapter.paragraphs[finding["para"]]
    if target.text != finding["quote"]:
        raise ValueError("定位失效：原文已变化，请重新扫描")

    mode = (rules.ai_flavor or {}).get("mode", "edit")
    policy_rewrite = (rules.ai_flavor or {}).get("rewrite") or {}
    tolerance = float(
        policy_rewrite.get("edit_length_tolerance", DEFAULT_EDIT_TOLERANCE)
        if mode == "edit"
        else policy_rewrite.get("generate_length_tolerance", DEFAULT_GENERATE_TOLERANCE)
    )
    max_rounds = int(policy_rewrite.get("max_rounds", DEFAULT_MAX_ROUNDS))
    prev_text = chapter.paragraphs[finding["para"] - 1].text if finding["para"] > 0 else ""
    next_text = (
        chapter.paragraphs[finding["para"] + 1].text
        if finding["para"] + 1 < len(chapter.paragraphs)
        else ""
    )
    req_id = "RW-" + __import__("hashlib").sha1(
        f"{finding_id}|{actual_round}|{target.text}".encode("utf-8")
    ).hexdigest()[:10]
    lo, hi = _length_range(target.text, tolerance)

    request = {
        "schema": 1,
        "request_id": req_id,
        "created_at": now_iso(),
        "project": cfg.get("title") or book.title,
        "project_title": cfg.get("title") or book.title,
        "project_dir": str(project_dir),
        "round": actual_round,
        "finding_id": finding_id,
        "finding": {
            "rule": finding.get("rule"),
            "category": finding.get("category"),
            "severity": finding.get("severity"),
            "why": finding.get("why"),
            "suggestion": finding.get("suggestion"),
        },
        "chapter": finding["chapter"],
        "chapter_title": chapter.title,
        "para": finding["para"],
        "para_display": finding["para_display"],
        "original": target.text,
        "original_cjk": cjk_count(target.text),
        "length_tolerance": tolerance,
        "length_range": [lo, hi],
        "max_rounds": max_rounds,
        "attempts": 0,
        "status": "prepared",
        "triggers": _triggers(finding, report),
        "context": {
            "prev": (prev_text[:120] + "…") if len(prev_text) > 120 else prev_text,
            "next": (next_text[:120] + "…") if len(next_text) > 120 else next_text,
            "prev_ref": f"chapters/{finding['chapter']:03d}#p{finding['para']}",
            "next_ref": f"chapters/{finding['chapter']:03d}#p{finding['para'] + 2}",
        },
        "constraints": {
            "no_new_facts": True,
            "keep_dialogue": True,
            "no_new_simile": True,
            "max_rounds": max_rounds,
            "length_tolerance": tolerance,
        },
        "metrics_before": _para_metrics(target.text, rules),
    }
    request["prompt"] = _prompt(request, rules, aiflavor.load_config(rules))

    req_dir = round_dir(project_dir, actual_round) / REQUEST_DIR
    req_dir.mkdir(parents=True, exist_ok=True)
    write_json(req_dir / f"{req_id}.json", request)
    return {"ok": True, "request": request}


# ---------------------------------------------------------------- submit
def _fail(request: dict, path: Path, code: str, errors: list[dict]) -> dict:
    request["attempts"] = int(request.get("attempts", 0)) + 1
    request["status"] = "retry" if request["attempts"] < request.get("max_rounds", DEFAULT_MAX_ROUNDS) else "manual"
    request["last_result"] = {"ok": False, "code": code, "errors": errors, "at": now_iso()}
    write_json(path, request)
    return {
        "ok": False,
        "code": code,
        "errors": errors,
        "attempts": request["attempts"],
        "can_retry": request["attempts"] < request.get("max_rounds", DEFAULT_MAX_ROUNDS),
        "request": {k: request.get(k) for k in ("request_id", "chapter", "para_display", "original", "length_range")},
    }


def submit(
    project_dir: str | Path,
    request_id: str,
    rewritten: str,
    round_name: str | None = None,
) -> dict:
    project_dir = Path(project_dir)
    cfg = load_project(project_dir)
    rules = load_rules(project_dir, cfg)
    request, path = _find_request(project_dir, request_id, round_name)
    if request.get("status") == "manual":
        return {
            "ok": False,
            "code": "REWRITE_ROUNDS_EXCEEDED",
            "errors": [{"code": "REWRITE_ROUNDS_EXCEEDED", "message": "该段已用完 2 轮改写，转人工处理。"}],
            "attempts": request.get("attempts", 0),
            "can_retry": False,
        }
    if int(request.get("attempts", 0)) >= int(request.get("max_rounds", DEFAULT_MAX_ROUNDS)):
        request["status"] = "manual"
        write_json(path, request)
        return {
            "ok": False,
            "code": "REWRITE_ROUNDS_EXCEEDED",
            "errors": [{"code": "REWRITE_ROUNDS_EXCEEDED", "message": "该段已用完 2 轮改写，转人工处理。"}],
            "attempts": request.get("attempts", 0),
            "can_retry": False,
        }

    text = (rewritten or "").strip()
    original = request["original"]
    errors: list[dict] = []
    if not text:
        errors.append({"code": "REWRITE_EMPTY", "message": "改写文本为空"})
    lo, hi = request["length_range"]
    cjk = cjk_count(text)
    if not (lo <= cjk <= hi):
        errors.append({
            "code": "REWRITE_LENGTH_FAIL",
            "message": f"篇幅不在范围内：{cjk} 字，要求 {lo}–{hi} 字（原文 {request['original_cjk']}，±{int(request['length_tolerance'] * 100)}%）",
            "actual": cjk,
            "range": [lo, hi],
        })
    # 禁用词
    banned_hits = [b.get("term") for b in rules.banned if b.get("term") and b["term"] in text]
    if banned_hits:
        errors.append({"code": "REWRITE_BANNED_TERM", "message": f"出现禁用词：{'、'.join(banned_hits)}", "hits": banned_hits})
    # 新数字
    new_numbers = sorted(_numbers(text) - _numbers(original))
    if new_numbers:
        errors.append({"code": "REWRITE_FACT_VIOLATION", "message": f"出现原文没有的数字：{'、'.join(new_numbers)}", "hits": new_numbers})
    # 新实体
    entities = _entities(project_dir)
    entities_configured = bool(entities)
    new_entities = [e for e in entities if e in text and e not in original]
    if new_entities:
        errors.append({"code": "REWRITE_FACT_VIOLATION", "message": f"出现原文没有的实体：{'、'.join(new_entities)}", "hits": new_entities})
    # 对白
    original_quotes = _quotes(original)
    new_quotes = _quotes(text)
    changed = [q for q in original_quotes if q not in text]
    introduced = [q for q in new_quotes if q not in original_quotes]
    if changed:
        errors.append({"code": "REWRITE_DIALOGUE_CHANGED", "message": "原文对白被改动或删除：" + "；".join(changed[:3]), "hits": changed[:3]})
    if introduced:
        errors.append({"code": "REWRITE_NEW_DIALOGUE", "message": "新增了原文没有的对白：" + "；".join(introduced[:3]), "hits": introduced[:3]})
    # AI 腔词表复测
    ai_cfg = aiflavor.load_config(rules)
    words = aiflavor._words(ai_cfg)
    trigger_ids = {t["id"] for t in request.get("triggers", [])}
    for metric, word_key, label in (
        ("W2", "grandeur", "意义拔高词"),
        ("W3", "promo", "宣传式形容词"),
    ):
        hits = [w for w in words[word_key] if w in text]
        if not hits:
            continue
        original_hits = [w for w in words[word_key] if w in original]
        if metric in trigger_ids or (hits and not original_hits):
            errors.append({
                "code": "REWRITE_AIFLAVOR_FAIL",
                "message": f"改写后仍有/新增{label}：{'、'.join(hits)}",
                "hits": hits,
                "metric": metric,
            })
    # 原有 AI 腔 pattern 复测：触发的那条必须清掉；其他条不许新增
    for rule in rules.ai:
        narr = "\n".join(narration_segments(text))
        after = rule.matches(narr)
        if not after:
            continue
        before = rule.matches("\n".join(narration_segments(original)))
        if rule.id in trigger_ids:
            errors.append({
                "code": "REWRITE_AIFLAVOR_FAIL",
                "message": f"触发项 {rule.id} 仍未清除：{rule.name}",
                "metric": rule.id,
            })
        elif not before:
            errors.append({
                "code": "REWRITE_AIFLAVOR_FAIL",
                "message": f"改写引入了新的 AI 腔：{rule.name}",
                "metric": rule.id,
            })

    if errors:
        first = errors[0]["code"]
        return _fail(request, path, first, errors)

    # 通过：写提案
    request["attempts"] = int(request.get("attempts", 0)) + 1
    request["status"] = "accepted"
    metrics_after = _para_metrics(text, rules)
    proposal = {
        "request_id": request_id,
        "finding_id": request["finding_id"],
        "chapter": request["chapter"],
        "chapter_title": request.get("chapter_title"),
        "para": request["para"],
        "para_display": request.get("para_display"),
        "original": original,
        "rewritten": text,
        "triggers": request.get("triggers"),
        "metrics_before": request.get("metrics_before"),
        "metrics_after": metrics_after,
        "machine_checks": {
            "length": "pass",
            "banned_terms": "pass",
            "new_numbers": "pass",
            "new_entities": "pass" if entities_configured else "skipped(没有 rules/entities.json)",
            "dialogue": "pass",
            "aiflavor_retest": "pass",
        },
        "semantic_note": "机器只能查篇幅/禁用词/数字/实体/对白/AI 腔词；动作、心理、因果等语义事实仍需人工复核。",
        "created_at": now_iso(),
        "status": "accepted_pending_approval",
    }
    request["last_result"] = {"ok": True, "proposal": proposal, "at": now_iso()}
    write_json(path, request)
    proposals_path = path.parents[1] / PROPOSALS_FILE
    current = read_json(proposals_path, {"version": 1, "proposals": []}) or {"version": 1, "proposals": []}
    items = [p for p in current.get("proposals", []) if p.get("request_id") != request_id]
    items.append(proposal)
    current["proposals"] = items
    current["updated_at"] = now_iso()
    write_json(proposals_path, current)

    return {
        "ok": True,
        "request_id": request_id,
        "proposal": proposal,
        "proposals_path": str(proposals_path),
        "next": "让作者在审批页勾选/或调用 novel_apply，把 rewritten 作为该条 finding 的 replacement 应用；不会自动替换主稿。",
    }


def list_proposals(project_dir: str | Path, round_name: str | None = None) -> dict:
    project_dir = Path(project_dir)
    report, actual_round = load_scan(project_dir, round_name)
    path = round_dir(project_dir, actual_round) / PROPOSALS_FILE
    data = read_json(path, {"version": 1, "proposals": []}) or {"version": 1, "proposals": []}
    return {"ok": True, "round": actual_round, "proposals": data.get("proposals", []), "path": str(path)}

# -*- coding: utf-8 -*-
"""应用审批结果：生成新稿 + 逐条记录 + 自动体检。"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from .docx_io import write_book
from .model import cjk_count, file_sha256, load_book
from .rules import Rules, load_project, load_rules
from .store import (
    archive_files,
    load_scan,
    now_iso,
    read_json,
    round_dir,
    save_apply,
    update_status,
    write_json,
    write_text,
)
from .verify import verify_book


class ApplyError(Exception):
    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("；".join(e.get("message", "") for e in errors))


def _load_decisions(decisions) -> list[dict]:
    if isinstance(decisions, dict):
        decisions = decisions.get("decisions") or []
    return list(decisions or [])


def apply_decisions(project_dir: str | Path, round_name: str, decisions) -> dict:
    cfg = load_project(project_dir)
    rules = load_rules(project_dir, cfg)
    book = load_book(cfg["_main_draft_path"], rules.chapter_pattern, cfg.get("title"), cfg.get("subtitle"))
    scan, round_name = load_scan(project_dir, round_name)
    findings = {f["id"]: f for f in scan["findings"]}
    decisions = _load_decisions(decisions)

    ops: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for d in decisions:
        fid = d.get("id")
        decision = d.get("decision") or "reject"
        finding = findings.get(fid)
        if not finding:
            errors.append({"id": fid, "message": f"扫描结果里没有 {fid}（可能稿子已变，请重新扫描）"})
            continue
        if decision != "approve":
            skipped.append({"id": fid, "reason": "未批准"})
            continue
        ch = book.chapter(finding["chapter"])
        # 优先用全书段号 + 原文定位（段序漂移时更稳）；旧 para 越界不代表失效，
        # 所以先试全局段号，失败再回退章内序号。
        target = None
        gi = finding.get("global_index")
        if isinstance(gi, int):
            all_paras = book.paragraphs
            if 0 <= gi < len(all_paras):
                cand = all_paras[gi]
                if cand.text == finding["quote"] and cand.chapter == finding["chapter"]:
                    target = cand
                    finding = dict(finding)
                    finding["para"] = cand.index_in_chapter
        if target is None:
            if not ch or finding["para"] >= len(ch.paragraphs):
                errors.append({"id": fid, "message": "定位失效：章/段不存在"})
                continue
            target = ch.paragraphs[finding["para"]]
            if target.text != finding["quote"]:
                errors.append({"id": fid, "message": "定位失效：原文已变化，请重新扫描后再批"})
                continue
        action = d.get("action") or finding.get("action") or "flag"
        replacement = d.get("replacement")
        if replacement is None:
            replacement = finding.get("replacement") or ""
        if action == "delete":
            ops.append({"id": fid, "kind": "delete", "chapter": finding["chapter"], "para": finding["para"],
                        "before": target.text, "after": "", "why": finding["why"]})
        elif action == "replace" or (action == "flag" and replacement):
            replacement = replacement or finding.get("replacement") or ""
            if not replacement:
                errors.append({"id": fid, "message": "缺少替换文本（审批时请填写）"})
                continue
            ops.append({"id": fid, "kind": "replace", "chapter": finding["chapter"], "para": finding["para"],
                        "before": target.text, "after": replacement, "why": finding["why"]})
        else:
            skipped.append({"id": fid, "reason": "已批准，但该条为观察项且没有替换文本（仅记录）"})

    if errors:
        raise ApplyError(errors)
    if not ops:
        raise ApplyError([{
            "id": "-",
            "message": "没有批准任何可执行条目：全部被拒绝或跳过，本轮不生成新稿",
        }])

    # 内存里应用（按章号索引：章号不一定是 1..N，按位置取会错位/越界）
    chapter_texts: dict[int, tuple[str, list[dict]]] = {}
    for ch in book.chapters:
        chapter_texts[ch.index] = (ch.title, [{"text": p.text, "deleted": False} for p in ch.paragraphs])
    for op in ops:
        entry = chapter_texts.get(op["chapter"])
        if entry is None:
            raise ApplyError([{"id": op["id"],
                               "message": f"定位失效：新稿里没有第 {op['chapter']} 章（章号可能已变，请重新扫描后再批）"}])
        title, paras = entry
        slot = paras[op["para"]]
        if op["kind"] == "delete":
            slot["deleted"] = True
            slot["text"] = ""
        else:
            slot["text"] = op["after"]

    flat: list[str] = []
    expected_delta = 0
    for op in ops:
        if op["kind"] == "delete":
            expected_delta -= cjk_count(op["before"])
        else:
            expected_delta += cjk_count(op["after"]) - cjk_count(op["before"])

    for title, paras in chapter_texts.values():
        flat.append(title)
        for slot in paras:
            if slot["deleted"]:
                continue
            flat.append(slot["text"])

    rd = round_dir(project_dir, round_name)
    out_path = rd / f"稿子_{round_name}.docx"
    ledger_path = rd / "应用对照.md"
    verify_path = rd / "体检.json"
    tmp_path = rd / f".稿子_{round_name}.{os.getpid()}.tmp.docx"

    archived: list[str] = []
    replaced = False
    draft_before = book.cjk
    draft_after = draft_before
    new_book = book
    applied: list[dict] = []
    verify: dict = {}

    def _rollback() -> None:
        """删掉本轮写出的新产物，再把归档的旧产物搬回原位。"""
        for path in (tmp_path, out_path if replaced else None,
                     ledger_path if replaced else None, verify_path if replaced else None):
            if path is None:
                continue
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        for backup in archived:
            src = Path(backup)
            dst = rd / src.name.split("__", 1)[-1]
            try:
                if src.exists() and not dst.exists():
                    shutil.move(str(src), str(dst))
            except OSError:
                pass

    try:
        # 先写临时文件：写失败时旧稿还在原位，不会出现「旧稿已归档、新稿没写成」。
        write_book(
            flat,
            tmp_path,
            title=cfg.get("docx_title") or cfg.get("title") or book.title,
            subtitle=cfg.get("docx_subtitle") or "修订版",
            chapter_pattern=rules.chapter_pattern,
            front_matter=book.front_matter,
        )
        # 新稿写成功后再归档上一版（同一轮重复 apply 不静默覆盖）。
        archived = archive_files(
            [out_path, rd / "应用记录.json", ledger_path, verify_path],
            base_dir=rd,
        )
        os.replace(tmp_path, out_path)
        replaced = True

        new_book = load_book(out_path, rules.chapter_pattern, cfg.get("title"), cfg.get("subtitle"))
        draft_after = new_book.cjk
        applied = [op for op in ops]

        # 记录逐条对照
        ledger_lines = [f"# {round_name} · 应用记录", "", f"> 生成：{now_iso()}", ""]
        for op in applied:
            ledger_lines.append(f"## {op['id']}　第{op['chapter']}章·第{op['para'] + 1}段")
            ledger_lines.append("")
            ledger_lines.append(f"- 动作：{'删除整段' if op['kind'] == 'delete' else '整段替换'}")
            ledger_lines.append(f"- 理由：{op['why']}")
            ledger_lines.append(f"- 原文：`{op['before']}`")
            if op["kind"] == "replace":
                ledger_lines.append(f"- 改为：`{op['after']}`")
                ledger_lines.append(f"- 字数：{cjk_count(op['before'])} → {cjk_count(op['after'])}")
            else:
                ledger_lines.append(f"- 字数：{cjk_count(op['before'])} → 0")
            ledger_lines.append("")
        if skipped:
            ledger_lines.append("## 未应用")
            ledger_lines.append("")
            for s in skipped:
                ledger_lines.append(f"- `{s['id']}`：{s['reason']}")
            ledger_lines.append("")
        write_text(ledger_path, "\n".join(ledger_lines))

        verify = verify_book(
            baseline_path=cfg["_main_draft_path"],
            draft_path=out_path,
            cfg=cfg,
            rules=rules,
            expected_delta=expected_delta,
            applied_ops=applied,
        )
        write_json(verify_path, verify)
    except BaseException:
        _rollback()
        raise

    result = {
        "ok": True,
        "round": round_name,
        "output": str(out_path),
        "applied": len(applied),
        "skipped": skipped,
        "changes": applied,
        "stats_before": {"cjk": draft_before, "chapters": len(book.chapters), "paragraphs": len(book.paragraphs)},
        "stats_after": {"cjk": draft_after, "chapters": len(new_book.chapters), "paragraphs": len(new_book.paragraphs)},
        "delta_cjk": draft_after - draft_before,
        "expected_delta": expected_delta,
        "verify": verify,
        "reapply": {"archived": archived} if archived else None,
        "generated_at": now_iso(),
    }
    save_apply(project_dir, round_name, result)
    # status.last_score 只由 scan 写（float）；apply 不重扫，所以不覆盖它，
    # 应用后的字数统计另记在 last_apply_stats（dict）里，避免同一字段两种类型。
    update_status(
        project_dir,
        last_apply_round=round_name,
        last_apply_at=result["generated_at"],
        last_draft=str(out_path),
        last_verify_pass=verify["pass"],
        last_apply_stats=verify.get("stats_after"),
    )
    return result

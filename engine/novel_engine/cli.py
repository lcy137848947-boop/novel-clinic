# -*- coding: utf-8 -*-
"""命令行入口。每个子命令只向 stdout 输出一个 JSON 对象。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

from . import __version__, aiflavor, kb
from . import plot as plot_engine
from . import rewrite as rewrite_engine
from . import style as style_engine
from .apply import ApplyError, apply_decisions
from .model import cjk_count, file_sha256, load_book
from .report import build_report, render_markdown
from .rules import load_project, load_rules
from .scanners import scan_book
from .store import (
    StoreError,
    latest_round,
    list_rounds,
    load_apply,
    load_scan,
    load_status,
    next_round_number,
    now_iso,
    read_json,
    round_name,
    save_scan,
    update_status,
    write_json,
)
from .verify import verify_book


def emit(data) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=1))
    return 0


def fail(message: str, detail: str | None = None, code: int = 1) -> int:
    print(json.dumps({"ok": False, "error": message, "detail": detail}, ensure_ascii=False, indent=1))
    return code


def rules_digest(project_dir: Path, cfg: dict) -> str:
    rel = cfg.get("rules_file") or "rules/rules.json"
    p = project_dir / rel
    h = hashlib.sha1()
    h.update(super_engine_digest().encode("utf-8"))
    if p.exists():
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def super_engine_digest() -> str:
    try:
        from .rules import DEFAULT_AI, DEFAULT_THRESHOLDS

        return hashlib.sha1(
            (json.dumps(DEFAULT_AI, ensure_ascii=False, sort_keys=True) + json.dumps(DEFAULT_THRESHOLDS, sort_keys=True)).encode("utf-8")
        ).hexdigest()
    except Exception:
        return "engine"


# ------------------------------------------------------------------ scan
def _pending_round(project_dir: Path, cfg: dict) -> str:
    """没有显式指定轮次时：若最新一轮只扫描过、还没应用，就复用该轮；否则开新轮。"""
    rounds = list_rounds(project_dir)
    if rounds:
        n, path = rounds[-1]
        name = round_name(n)
        if (path / "扫描.json").exists() and not (path / "应用记录.json").exists():
            return name
        return round_name(n + 1)
    return round_name(next_round_number(project_dir, cfg))


def cmd_scan(args) -> int:
    project_dir = Path(args.project).resolve()
    cfg = load_project(project_dir)
    rules = load_rules(project_dir, cfg)
    book = load_book(cfg["_main_draft_path"], rules.chapter_pattern, cfg.get("title"), cfg.get("subtitle"))
    scan = scan_book(book, rules)
    aiflavor.attach(project_dir, book, rules, scan)
    rname = args.round or _pending_round(project_dir, cfg)
    digest = rules_digest(project_dir, cfg)
    report = build_report(
        cfg=cfg,
        rules=rules,
        book=book,
        scan=scan,
        round_name=rname,
        draft_sha256=file_sha256(Path(cfg["_main_draft_path"])),
        rules_digest=digest,
    )
    markdown = render_markdown(report, rules)
    paths = save_scan(project_dir, rname, report, markdown)
    update_status(
        project_dir,
        last_scan_round=rname,
        last_scan_at=report["generated_at"],
        latest_report=paths["scan"],
        latest_markdown=paths["markdown"],
        last_score=report["score"]["total"],
        last_grade=report["score"]["grade"],
        main_draft=cfg.get("main_draft"),
        title=cfg.get("title"),
    )
    report["artifacts"] = paths
    return emit(report)


# ------------------------------------------------------------------ report
def cmd_report(args) -> int:
    report, rname = load_scan(args.project, args.round)
    if args.summary:
        out = {
            "ok": True,
            "round": rname,
            "stats": report["stats"],
            "score": report["score"],
            "chapters": report["chapters"],
            "finding_count": len(report["findings"]),
            "findings": report["findings"][: int(args.limit or 30)],
        }
    else:
        out = report
    return emit(out)


# ------------------------------------------------------------------ apply
def cmd_apply(args) -> int:
    project_dir = Path(args.project).resolve()
    if args.decisions == "-":
        payload = json.load(sys.stdin)
    else:
        payload = read_json(args.decisions)
    try:
        result = apply_decisions(project_dir, args.round, payload)
    except ApplyError as e:
        return fail("审批无法应用，已全部回滚（未生成新稿）", json.dumps(e.errors, ensure_ascii=False))
    return emit(result)


# ------------------------------------------------------------------ verify
def cmd_verify(args) -> int:
    project_dir = Path(args.project).resolve()
    cfg = load_project(project_dir)
    rules = load_rules(project_dir, cfg)
    if args.draft:
        draft = Path(args.draft)
        expected = args.expected_delta
        ops = []
    else:
        record, rname = load_apply(project_dir, args.round)
        draft = Path(record["output"])
        expected = record.get("expected_delta")
        ops = record.get("changes") or []
    if not draft.exists():
        return fail(f"稿子不存在：{draft}")
    result = verify_book(
        baseline_path=cfg["_main_draft_path"],
        draft_path=draft,
        cfg=cfg,
        rules=rules,
        expected_delta=expected,
        applied_ops=ops,
    )
    rd = draft.parent
    write_json(rd / "体检.json", result)
    result["draft"] = str(draft)
    return emit(result)


# ------------------------------------------------------------------ status
def cmd_status(args) -> int:
    project_dir = Path(args.project).resolve()
    cfg = load_project(project_dir)
    rules = load_rules(project_dir, cfg)
    book = load_book(cfg["_main_draft_path"], rules.chapter_pattern, cfg.get("title"), cfg.get("subtitle"))
    rounds = []
    for n, path in list_rounds(project_dir):
        scan_path = path / "扫描.json"
        entry = {"round": round_name(n), "path": str(path)}
        if scan_path.exists():
            data = read_json(scan_path, {}) or {}
            entry["score"] = (data.get("score") or {}).get("total")
            entry["findings"] = len(data.get("findings") or [])
            entry["generated_at"] = data.get("generated_at")
        draft_path = path / f"稿子_{round_name(n)}.docx"
        if draft_path.exists():
            entry["draft"] = str(draft_path)
        rounds.append(entry)
    latest, _ = latest_round(project_dir)
    return emit({
        "ok": True,
        "project": {
            "title": cfg.get("title"),
            "dir": str(project_dir),
            "main_draft": cfg.get("main_draft"),
            "main_draft_path": cfg["_main_draft_path"],
            "chapters": len(book.chapters),
            "paragraphs": len(book.paragraphs),
            "cjk": book.cjk,
            "cjk_with_headings": book.cjk
            + sum(cjk_count(c.title) for c in book.chapters)
            + sum(cjk_count(t) for t in book.front_matter),
        },
        "engine": {"version": __version__},
        "status": load_status(project_dir),
        "rounds": rounds,
        "latest_round": latest,
        "pending": _pending_summary(project_dir, latest),
        "generated_at": now_iso(),
    })


def _pending_summary(project_dir: Path, latest: str | None) -> dict | None:
    if not latest:
        return None
    try:
        report, _ = load_scan(project_dir, latest)
    except FileNotFoundError:
        return None
    findings = report.get("findings") or []
    return {
        "round": latest,
        "findings": len(findings),
        "hard": sum(1 for f in findings if f["severity"] == "hard"),
        "warn": sum(1 for f in findings if f["severity"] == "warn"),
        "info": sum(1 for f in findings if f["severity"] == "info"),
        "auto_fixable": sum(1 for f in findings if f.get("auto_fixable")),
        "score": (report.get("score") or {}).get("total"),
    }


# ------------------------------------------------------------------ dump
def cmd_dump(args) -> int:
    project_dir = Path(args.project).resolve()
    if args.chapter is not None and args.chapter < 1:
        return fail(f"--chapter 必须 >= 1（收到 {args.chapter}）")
    cfg = load_project(project_dir)
    rules = load_rules(project_dir, cfg)
    book = load_book(cfg["_main_draft_path"], rules.chapter_pattern, cfg.get("title"), cfg.get("subtitle"))
    data = []
    for ch in book.chapters:
        if args.chapter is not None and ch.index != args.chapter:
            continue
        data.append({
            "index": ch.index,
            "title": ch.title,
            "paragraphs": [{"i": p.index_in_chapter + 1, "text": p.text} for p in ch.paragraphs],
        })
    return emit({"ok": True, "chapters": data})


# ------------------------------------------------------------------ rewrite
def cmd_rewrite(args) -> int:
    project_dir = Path(args.project).resolve()
    if args.action == "prepare":
        if not args.finding:
            return fail("prepare 需要 --finding <候选项 id>")
        return emit(rewrite_engine.prepare(project_dir, args.finding, args.round))
    if args.action == "submit":
        if not args.request:
            return fail("submit 需要 --request <request_id>")
        if args.text == "-":
            text = sys.stdin.read()
        elif args.text_file:
            text = Path(args.text_file).read_text(encoding="utf-8-sig")
        elif args.text:
            text = args.text
        else:
            return fail("submit 需要 --text / --text-file / --text - 之一")
        return emit(rewrite_engine.submit(project_dir, args.request, text, args.round))
    if args.action == "list":
        return emit(rewrite_engine.list_proposals(project_dir, args.round))
    return fail(f"未知 rewrite action：{args.action}")


# ------------------------------------------------------------------ kb
def cmd_kb(args) -> int:
    project_dir = Path(args.project).resolve()
    if args.action == "sync":
        return emit(kb.sync(project_dir))
    if args.action == "list":
        return emit(kb.list_cards(project_dir, include_spoilers=args.include_spoilers))
    if args.action == "search":
        if not args.query:
            return fail("search 需要 --query")
        return emit(kb.search(project_dir, args.query, limit=args.limit, include_spoilers=args.include_spoilers))
    if args.action == "context":
        if not args.chapter:
            return fail("context 需要 --chapter")
        return emit(kb.context(project_dir, args.chapter, max_chars=args.max_chars, include_spoilers=args.include_spoilers))
    return fail(f"未知 kb action：{args.action}")


# ------------------------------------------------------------------ plot
def cmd_plot(args) -> int:
    project_dir = Path(args.project).resolve()
    if args.action == "import":
        if not args.source:
            return fail("plot import 需要 --source <细纲路径>")
        return emit(plot_engine.import_outline(project_dir, args.source, chapter_key=args.chapter_key, title=args.title))
    if args.action == "validate":
        if not args.chapter_key:
            return fail("plot validate 需要 --chapter-key")
        return emit(plot_engine.validate(project_dir, args.chapter_key))
    if args.action == "list":
        return emit(plot_engine.list_plots(project_dir))
    if args.action == "template":
        return emit(plot_engine.template(project_dir, args.chapter_key, args.total_chars))
    if args.action == "submit":
        if not args.payload:
            return fail("plot submit 需要 --payload <json 路径或 - >")
        payload = json.load(sys.stdin) if args.payload == "-" else read_json(args.payload)
        return emit(plot_engine.submit_beats(project_dir, payload))
    return fail(f"未知 plot action：{args.action}")


# ------------------------------------------------------------------ style
def cmd_style(args) -> int:
    project_dir = Path(args.project).resolve()
    if args.action == "list":
        return emit(style_engine.list_styles(project_dir))
    if args.action == "learn":
        if not args.name:
            return fail("style learn 需要 --name")
        if not args.samples:
            return fail("style learn 需要 --samples <样本文件...>")
        return emit(style_engine.learn(project_dir, args.name, args.samples))
    if args.action == "check":
        if not args.name:
            return fail("style check 需要 --name")
        text = args.text
        if text == "-":
            text = sys.stdin.read()
        return emit(style_engine.check(
            project_dir, args.name,
            text=text, text_file=args.text_file, chapter=args.chapter, para=args.para,
        ))
    return fail(f"未知 style action：{args.action}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="novel-forge-engine", description="小说工坊引擎")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="扫描主稿，生成改动清单")
    p.add_argument("--project", required=True)
    p.add_argument("--round", default=None)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("report", help="读取扫描报告")
    p.add_argument("--project", required=True)
    p.add_argument("--round", default=None)
    p.add_argument("--summary", action="store_true")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("apply", help="应用审批结果并体检")
    p.add_argument("--project", required=True)
    p.add_argument("--round", default=None)
    p.add_argument("--decisions", required=True, help="审批 JSON 路径，或 - 从 stdin 读取")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("verify", help="门禁体检")
    p.add_argument("--project", required=True)
    p.add_argument("--round", default=None)
    p.add_argument("--draft", default=None)
    p.add_argument("--expected-delta", type=int, default=None)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("status", help="项目状态")
    p.add_argument("--project", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("dump", help="导出指定章")
    p.add_argument("--project", required=True)
    p.add_argument("--chapter", type=int, default=None)
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("rewrite", help="A.6 改写契约（prepare / submit / list）")
    p.add_argument("--project", required=True)
    p.add_argument("--action", choices=["prepare", "submit", "list"], required=True)
    p.add_argument("--round", default=None)
    p.add_argument("--finding", default=None)
    p.add_argument("--request", default=None)
    p.add_argument("--text", default=None)
    p.add_argument("--text-file", dest="text_file", default=None)
    p.set_defaults(func=cmd_rewrite)

    p = sub.add_parser("kb", help="知识库设定集（sync / list / search / context）")
    p.add_argument("--project", required=True)
    p.add_argument("--action", choices=["sync", "list", "search", "context"], required=True)
    p.add_argument("--query", default=None)
    p.add_argument("--chapter", type=int, default=None)
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--max-chars", dest="max_chars", type=int, default=4000)
    p.add_argument("--include-spoilers", dest="include_spoilers", action="store_true")
    p.set_defaults(func=cmd_kb)

    p = sub.add_parser("plot", help="情节拼接（import / validate / list / template / submit）")
    p.add_argument("--project", required=True)
    p.add_argument("--action", choices=["import", "validate", "list", "template", "submit"], required=True)
    p.add_argument("--source", default=None)
    p.add_argument("--chapter-key", dest="chapter_key", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--payload", default=None)
    p.add_argument("--total-chars", dest="total_chars", type=int, default=2200)
    p.set_defaults(func=cmd_plot)

    p = sub.add_parser("style", help="文风调性（list / learn / check）")
    p.add_argument("--project", required=True)
    p.add_argument("--action", choices=["list", "learn", "check"], required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--samples", nargs="+", default=None)
    p.add_argument("--text", default=None)
    p.add_argument("--text-file", dest="text_file", default=None)
    p.add_argument("--chapter", type=int, default=None)
    p.add_argument("--para", type=int, default=None)
    p.set_defaults(func=cmd_style)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        return fail(str(e))
    except StoreError as e:
        return fail(str(e))
    except Exception as e:  # noqa: BLE001
        if getattr(args, "debug", False):
            traceback.print_exc(file=sys.stderr)
        else:
            traceback.print_exc(file=sys.stderr)
        return fail(f"引擎异常：{type(e).__name__}: {e}")


if __name__ == "__main__":
    raise SystemExit(main())

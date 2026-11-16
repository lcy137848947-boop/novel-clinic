# -*- coding: utf-8 -*-
"""报告：机器读的 JSON + 作者读的 Markdown 改动清单。"""
from __future__ import annotations

from . import ENGINE_NAME, __version__
from .store import now_iso
from .score import compute_score
from .rules import Rules

SEVERITY_LABEL = {"hard": "硬伤（必须处理）", "warn": "建议修改", "info": "观察项"}
CATEGORY_ORDER = ["硬伤", "设定", "AI 腔", "重复", "节奏", "文风"]
RISK = {"hard": "高", "warn": "中", "info": "低"}


def _chapter_name(title: str) -> str:
    import re

    return re.sub(r"^第\d+章\s*", "", title or "").strip() or (title or "")


def short(text: str, n: int = 150) -> str:
    t = (text or "").replace("\n", " ")
    if len(t) <= n:
        return t
    return t[: int(n * 0.65)] + "……" + t[-int(n * 0.25) :]


def build_report(
    *,
    cfg: dict,
    rules: Rules,
    book,
    scan: dict,
    round_name: str,
    draft_sha256: str,
    rules_digest: str,
) -> dict:
    score = compute_score(scan, rules)
    project_dir = cfg["_project_dir"]
    draft_path = cfg["_main_draft_path"]
    try:
        draft_rel = str(__import__("pathlib").Path(draft_path).relative_to(project_dir))
    except ValueError:
        draft_rel = str(draft_path)
    return {
        "schema": 1,
        "generated_at": now_iso(),
        "round": round_name,
        "tool": {"name": ENGINE_NAME, "version": __version__},
        "rule_version": rules_digest,
        "project": {
            "title": cfg.get("title") or book.title,
            "project_dir": project_dir,
            "draft_path": draft_path,
            "draft_rel": draft_rel,
            "draft_sha256": draft_sha256,
            "chapter_pattern": rules.chapter_pattern,
        },
        "stats": scan["stats"],
        "score": score,
        "chapters": scan["chapters"],
        "findings": scan["findings"],
        "metrics": scan["metrics"],
        "audit": scan.get("audit"),
        "notes": rules.notes,
    }


def render_markdown(report: dict, rules: Rules) -> str:
    p = report["project"]
    s = report["stats"]
    score = report["score"]
    findings = report["findings"]
    audit = report.get("audit") or {}
    audit_findings = [f for f in findings if (f.get("meta") or {}).get("audit")]
    candidates = [f for f in findings if not (f.get("meta") or {}).get("audit")]
    lines: list[str] = []
    add = lines.append

    add(f"# {report['round']} · 改动清单")
    add("")
    add(f"> 项目：《{p['title']}》")
    add(f"> 主稿：`{p['draft_rel']}`（{s['chapters']} 章 / {s['total_paragraphs']} 段 / {s['cjk_with_headings']:,} 字）")
    add(f"> 生成：{report['generated_at']}　引擎：{report['tool']['name']} {report['tool']['version']}")
    add(
        f"> 编辑健康度：**{score['total']}（{score['grade']}）**　候选项：{len(candidates)} 条"
        + (f"　AI 味审计告警：{len(audit_findings)} 条" if audit_findings else "")
    )
    add("")
    add("---")
    add("")

    add("## 一、体检总表")
    add("")
    add("| 维度 | 得分 | 权重 | 说明 |")
    add("|---|---|---|---|")
    for d in score["dimensions"]:
        add(f"| {d['name']} | {d['score']} | {d['weight'] * 100:.0f}% | {d['detail']} |")
    add("")
    if score["weak_hooks"]:
        add("### 章末钩子最弱的几章")
        add("")
        add("| 章 | 末段 | 分数 | 原因 |")
        add("|---|---|---|---|")
        for w in score["weak_hooks"]:
            ch = next((c for c in report["chapters"] if c["index"] == w["index"]), None)
            last = short(ch["last"], 60) if ch else ""
            add(f"| 第{w['index']}章 {_chapter_name(w['title'])[:12]} | {last} | {w['score']} | {'；'.join(w['reasons'])} |")
        add("")

    if audit:
        add("## 二、AI 味审计（v4 指标 · 编辑模式：只报告）")
        add("")
        policy = audit.get("policy") or {}
        add(f"> {policy.get('summary') or '编辑模式：只报告，不硬卡。'}")
        add(f"> 基线：{audit.get('baseline', {}).get('status')}　词表版本：{audit.get('words_digest')}　审计引擎：{audit.get('engine')}")
        add("")
        add("| 指标 | 组 | 单位 | 全书值 | 默认区（绿/黄/红 章数） | 本书基线 | 偏差 | 处理 |")
        add("|---|---|---|---|---|---|---|---|")
        unit_labels = {"ratio": "比例", "per_k": "/千字", "std": "标准差", "per_chapter": "/章", "count": "次"}
        for m in audit.get("metrics") or []:
            if m.get("enabled") is False:
                add(f"| {m['id']} {m['name']} | {m.get('group')} | {unit_labels.get(m.get('unit'), m.get('unit') or '')} | — | — | — | — | 未启用 |")
                continue
            zones = m.get("default_zones") or {}
            value = m.get("book_value")
            base = m.get("baseline_value")
            dev = m.get("deviation_pct")
            add(
                f"| {m['id']} {m['name']} | {m.get('group')} | {unit_labels.get(m.get('unit'), m.get('unit') or '')} "
                f"| {value if value is not None else '—'} "
                f"| {zones.get('green', 0)} / {zones.get('yellow', 0)} / {zones.get('red', 0)} "
                f"| {base if base is not None else '—'} "
                f"| {(f'{dev:+.1f}%' if dev is not None else '—')} "
                f"| {'告警' if m.get('policy') == 'warn' else '只报告'} |"
            )
        add("")
        if audit_findings:
            add(f"### 段级审计告警（共 {len(audit_findings)} 条）")
            add("")
            for f in audit_findings:
                add(f"- **第{f['chapter']}章·第{f['para_display']}段** · `{f['id']}` · {SEVERITY_LABEL.get(f['severity'], f['severity'])}")
                add(f"  - 原文：`{short(f['quote'], 120)}`")
                add(f"  - 为什么：{f['why']}")
                add(f"  - 建议：{f['suggestion']}")
            add("")
        notes = audit.get("notes") or []
        if notes:
            add("### 误伤与未启用说明")
            add("")
            for note in notes:
                add(f"- {note}")
            add("")

    add("## 三、候选项（需要你拍板）")
    add("")
    add("> 用法：在 `- [ ]` 里打 `x` 表示同意；改法可留空（仅记录）或填整段替换文本。")
    add("> 全部处理完，回到「小说工坊」审批页点「应用已批准」，或运行 `apply`。")
    add("")
    by_cat: dict[str, list[dict]] = {}
    for f in candidates:
        by_cat.setdefault(f["category"], []).append(f)
    any_item = False
    for cat in CATEGORY_ORDER:
        items = by_cat.get(cat)
        if not items:
            continue
        any_item = True
        add(f"### {cat}（{len(items)} 条）")
        add("")
        for f in items:
            add(f"- [ ] **第{f['chapter']}章·第{f['para_display']}段** · `{f['id']}` · {SEVERITY_LABEL.get(f['severity'], f['severity'])}")
            add(f"  - 原文：`{short(f['quote'], 160)}`")
            add(f"  - 为什么：{f['why']}")
            add(f"  - 建议：{f['suggestion']}")
            add(f"  - 风险：{RISK.get(f['severity'], '低')}")
            if f.get("action") != "flag":
                add(f"  - 可执行：{f['action']}" + (f"（替换文本已备好）" if f.get("replacement") else ""))
        add("")
    if not any_item:
        add("（本轮没有候选项。）")
        add("")

    autos = [f for f in candidates if f.get("auto_fixable")]
    add("## 四、零风险机械修复")
    add("")
    if autos:
        for f in autos:
            add(f"- [ ] `{f['id']}` 第{f['chapter']}章·第{f['para_display']}段：{f['why']}")
    else:
        add("本轮没有可机械修复的项（禁用词 / 直引号 / 占位符均为 0）。")
    add("")

    add("## 五、白名单与不动的项")
    add("")
    add(f"- 故意重复/呼应白名单：{len(rules.allow_duplicates)} 条；命中即不报错。")
    if rules.do_not_touch:
        for item in rules.do_not_touch:
            add(f"- 不动：{item}")
    else:
        add("- 未配置不动清单。")
    add("")
    if rules.notes:
        add("## 六、本书规则备注")
        add("")
        for note in rules.notes:
            add(f"- {note}")
        add("")

    add("## 七、下一步")
    add("")
    add("1. 通读候选项，勾选你认可的；")
    add("2. 有明确改法的，把替换文本填在审批页（或直接改 `审批.json`）；")
    add("3. 应用后引擎会自动生成新稿并跑门禁体检；")
    add("4. 门禁通过后，再决定是否升为主稿。")
    add("")
    return "\n".join(lines)

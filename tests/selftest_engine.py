# -*- coding: utf-8 -*-
"""小说工坊引擎自测（fixture 版）。

流程：把 tests/fixture 复制到 tests/_run → 扫描 → 改写契约 → 知识库 → 情节 → 文风
      → 审批应用 → 门禁 → 归档/状态/dump/store 回归 → 清理。
不碰任何真实书稿；fixture 是虚构短文，可自由修改（改了记得同步 EXPECTED）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = PLUGIN_DIR / "engine"
FIXTURE_DIR = PLUGIN_DIR / "tests" / "fixture"
RUN_DIR = PLUGIN_DIR / "tests" / "_run"

# fixture 的稳定口径（改动 fixture 后按失败提示更新）
EXPECTED = {
    "chapters": 4,
    "total_paragraphs": 52,
    "cjk": 988,
    "candidates": 5,
    "audit_metrics_min": 12,
    "kb_cards": 10,
    "kb_sources": 3,
    "plot_beats": 5,
    "style_profiles": {"散文", "干句"},
}

sys.path.insert(0, str(ENGINE_DIR))
from novel_engine import store  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def call(args: list[str], stdin_data: str | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ENGINE_DIR / "run.py"), *args],
        cwd=str(ENGINE_DIR),
        input=stdin_data.encode("utf-8") if stdin_data is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=240,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace")[-3000:])
    if not proc.stdout.strip():
        raise RuntimeError("引擎无输出")
    return json.loads(proc.stdout.decode("utf-8"))


def prepare() -> None:
    """复制 fixture 到 _run，跳过生成物与缓存（跨平台，不依赖 PowerShell）。"""
    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)
    shutil.copytree(
        FIXTURE_DIR,
        RUN_DIR,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "rounds", "status.json", "index.json"),
    )
    (RUN_DIR / "rounds").mkdir(exist_ok=True)


def cleanup() -> None:
    try:
        if RUN_DIR.exists():
            shutil.rmtree(RUN_DIR)
    except Exception as error:  # noqa: BLE001
        print(f"[warn] 清理测试目录失败：{error}")


def main() -> int:
    if not (FIXTURE_DIR / "config.json").exists():
        print(f"找不到 fixture：{FIXTURE_DIR}")
        return 2
    prepare()
    try:
        scan = call(["scan", "--project", str(RUN_DIR)])
        assert scan.get("ok") is not False, scan
        stats = scan["stats"]
        assert stats["chapters"] == EXPECTED["chapters"], stats
        assert stats["total_paragraphs"] == EXPECTED["total_paragraphs"], stats
        assert stats["cjk"] == EXPECTED["cjk"], stats
        candidates = [f for f in scan["findings"] if not (f.get("meta") or {}).get("audit")]
        assert len(candidates) == EXPECTED["candidates"], f"{len(candidates)} != {EXPECTED['candidates']}"
        assert scan.get("audit") and len(scan["audit"]["metrics"]) >= EXPECTED["audit_metrics_min"], "audit 未落盘"
        print(
            f"[1] scan ok: round={scan['round']} chapters={stats['chapters']} "
            f"candidates={len(candidates)} audit_metrics={len(scan['audit']['metrics'])} "
            f"score={scan['score']['total']}"
        )

        # --- P1 回归：同一轮重复扫描，上一版产物移进 历史/，不再静默覆盖 ---
        rescan = call(["scan", "--project", str(RUN_DIR)])
        rescan_archived = ((rescan.get("artifacts") or {}).get("archived")) or []
        assert rescan_archived, rescan.get("artifacts")
        assert all(Path(item).exists() for item in rescan_archived), rescan_archived
        assert (RUN_DIR / "rounds" / scan["round"] / "历史").is_dir()
        print(f"[1b] 重复扫描备份 ok: {len(rescan_archived)} 个文件 → 历史/")

        by_rule: dict[str, list] = {}
        for finding in scan["findings"]:
            by_rule.setdefault(finding["rule"], []).append(finding)

        # 注意：rewrite prepare 要求 finding.quote 与整段文本完全相等，
        # 所以这里挑「命中句就是整段」的 finding（fixture 里这两条已按此设计）。
        ai_target = next(f for f in by_rule.get("ai.explain_rule", []))
        delete_target = next(f for f in by_rule.get("hard.banned_term", []))
        assert ai_target["chapter"] == 3 and delete_target["chapter"] == 4, (ai_target, delete_target)

        # --- A.6 改写契约：有效改写通过、新增实体被拒 ---
        prepared = call(["rewrite", "--project", str(RUN_DIR), "--action", "prepare", "--finding", ai_target["id"]])
        assert prepared.get("ok") is True, prepared
        request = prepared["request"]
        rewrite_text = "他把碗放下，站起来，往门外走。"
        submitted = call(
            ["rewrite", "--project", str(RUN_DIR), "--action", "submit", "--request", request["request_id"], "--text", "-"],
            rewrite_text,
        )
        assert submitted.get("ok") is True, submitted
        assert submitted["proposal"]["machine_checks"]["length"] == "pass", submitted
        print(f"[rewrite] valid accepted: {request['request_id']} ({request['original_cjk']}→{submitted['proposal']['metrics_after']['cjk']} 字)")

        bad_text = "老周把瓶子扔回船上，闭上了眼睛。"
        rejected = call(
            ["rewrite", "--project", str(RUN_DIR), "--action", "submit", "--request", request["request_id"], "--text", "-"],
            bad_text,
        )
        assert rejected.get("ok") is False, rejected
        assert rejected.get("code") == "REWRITE_FACT_VIOLATION", rejected
        print(f"[rewrite] new-entity rejected: {rejected['code']} / can_retry={rejected['can_retry']}")

        # --- P1 知识库：同步 / 检索 / 上下文包 ---
        kb_synced = call(["kb", "--project", str(RUN_DIR), "--action", "sync"])
        assert kb_synced.get("ok") is True, kb_synced
        assert kb_synced["cards"] == EXPECTED["kb_cards"], kb_synced
        assert len(kb_synced["sources"]) == EXPECTED["kb_sources"], kb_synced["sources"]
        assert kb_synced["spoiler_cards"] >= 1, kb_synced
        searched = call(["kb", "--project", str(RUN_DIR), "--action", "search", "--query", "引路灯"])
        assert searched.get("results"), searched
        ctx = call(["kb", "--project", str(RUN_DIR), "--action", "context", "--chapter", "2"])
        assert ctx.get("cards"), ctx
        assert all(not card["spoiler"] for card in ctx["cards"]), "上下文包混入番外剧透卡"
        print(
            f"[kb] sync={kb_synced['cards']} cards / {len(kb_synced['sources'])} sources / "
            f"search={len(searched['results'])} / context={len(ctx['cards'])} cards"
        )

        # --- P2 情节：import 第5章细纲 → validate ---
        outline = RUN_DIR / "plot" / "sources" / "第5章_细纲.md"
        imported = call(["plot", "--project", str(RUN_DIR), "--action", "import", "--source", str(outline)])
        assert imported.get("beats") == EXPECTED["plot_beats"], imported
        validation = call(["plot", "--project", str(RUN_DIR), "--action", "validate", "--chapter-key", "第5章"])
        assert validation.get("pass") is True, validation
        assert validation["beats"] == EXPECTED["plot_beats"], validation
        print(f"[plot] import+validate ok: {validation['beats']} beats / target={validation['target_chars_total']} / hook={validation['hook']['score']}")

        # --- P2 文风：样本 → 粘性 ---
        styles = call(["style", "--project", str(RUN_DIR), "--action", "list"])
        assert {item["name"] for item in styles["styles"]} >= EXPECTED["style_profiles"], styles
        sample = str(RUN_DIR / "styles" / "samples" / "散文_1.md")
        checked = call(["style", "--project", str(RUN_DIR), "--action", "check", "--name", "散文", "--text-file", sample])
        assert checked.get("adhesion", 0) >= 80, checked
        assert checked.get("verdict", "").startswith("更接近"), checked
        print(f"[style] profiles={len(styles['styles'])} / sample→散文 adhesion={checked['adhesion']} ({checked['verdict']})")

        decisions = {
            "decisions": [
                {"id": ai_target["id"], "decision": "approve", "replacement": rewrite_text},
                {"id": delete_target["id"], "decision": "approve", "action": "delete"},
            ]
        }
        applied = call(
            ["apply", "--project", str(RUN_DIR), "--round", scan["round"], "--decisions", "-"],
            json.dumps(decisions, ensure_ascii=False),
        )
        assert applied.get("ok") is not False, applied
        assert applied["applied"] == 2, applied
        assert applied["verify"]["pass"] is True, applied["verify"]
        assert applied["delta_cjk"] == applied["expected_delta"], applied
        out = Path(applied["output"])
        assert out.exists() and out.stat().st_size > 2000, out
        print(f"[2] apply ok: {applied['applied']} 条, delta={applied['delta_cjk']}, verify=pass")
        for gate in applied["verify"]["gates"]:
            print(f"      [{gate['status']}] {gate['name']}: {gate['detail']}")

        # --- P1 回归：同一轮重复 apply，上一版稿子/记录/体检移进 历史/ ---
        reapplied = call(
            ["apply", "--project", str(RUN_DIR), "--round", scan["round"], "--decisions", "-"],
            json.dumps(decisions, ensure_ascii=False),
        )
        assert reapplied.get("ok") is not False, reapplied
        reapply_archived = ((reapplied.get("reapply") or {}).get("archived")) or []
        assert reapply_archived, reapplied.get("reapply")
        assert all(Path(item).exists() for item in reapply_archived), reapply_archived
        assert reapplied["verify"]["pass"] is True, reapplied["verify"]
        print(f"[2b] 同轮重复应用归档 ok: {len(reapply_archived)} 个文件 → 历史/")

        report = call(["report", "--project", str(RUN_DIR), "--summary"])
        assert report["ok"] is True
        print(f"[3] report ok: {report['finding_count']} findings")

        # --- P0 回归：status 不再崩 / dump 章节边界 ---
        status = call(["status", "--project", str(RUN_DIR)])
        assert status.get("ok") is True, status
        assert status["project"]["chapters"] == EXPECTED["chapters"], status["project"]
        assert len(status["rounds"]) >= 1, status["rounds"]
        assert isinstance(status["status"].get("last_score"), float), status["status"].get("last_score")
        applied_round = next((item for item in status["rounds"] if item["round"] == scan["round"]), None)
        assert applied_round and applied_round.get("draft", "").endswith(f"稿子_{scan['round']}.docx"), status["rounds"]
        print(f"[4] status ok: rounds={len(status['rounds'])} last_score={status['status'].get('last_score')} draft={os.path.basename(applied_round['draft'])}")

        bad_dump = call(["dump", "--project", str(RUN_DIR), "--chapter", "0"])
        assert bad_dump.get("ok") is False, bad_dump
        one = call(["dump", "--project", str(RUN_DIR), "--chapter", "1"])
        assert one.get("ok") is True and len(one["chapters"]) == 1, one
        assert one["chapters"][0]["index"] == 1, one
        print("[5] dump 边界 ok: chapter=0 报错 / chapter=1 只返回 1 章")

        # --- P0 回归：store 原子写 + 损坏 JSON 容错 ---
        probe = RUN_DIR / "rounds" / "_store_probe"
        json_path = probe / "探针.json"
        store.write_json(json_path, {"ok": True, "中文": "值"})
        assert store.read_json(json_path) == {"ok": True, "中文": "值"}
        leftovers = sorted(p.name for p in probe.iterdir() if p.name.endswith(".tmp"))
        assert not leftovers, leftovers
        json_path.write_text('{"half": ', encoding="utf-8")
        assert store.read_json(json_path, {"fallback": True}) == {"fallback": True}
        backups = sorted(p.name for p in probe.iterdir() if ".corrupt-" in p.name)
        assert backups, "损坏 JSON 未备份"
        try:
            store.read_json(json_path)
            raise AssertionError("损坏且无默认值时应抛 StoreError")
        except store.StoreError:
            pass
        print(f"[6] store ok: 原子写无 .tmp 残留 / 损坏 JSON 返回默认值并备份（{backups[0]}）")

        # --- 2026-10-27 回归：本轮 6 条修复 ---
        from novel_engine import docx_io as _docx
        from novel_engine import model as _model
        from novel_engine import plot as _plot
        from novel_engine import rules as _rules
        from novel_engine import scanners as _sc

        # [7a] 英文撇号不算直引号；半角单/双引号仍然算
        assert not _sc.has_straight_quote("他没说 don't 就走了。"), "撇号被误判成直引号"
        assert _sc.straight_quote_count('他说"走"') == 2, "半角双引号漏算"
        assert _sc.straight_quote_count("他说'走'") == 2, "半角单引号漏算"

        # [7b] cn_quotes：落单直引号要配成右引号，且幂等
        assert _sc.cn_quotes('他走了。"') == '他走了。”', _sc.cn_quotes('他走了."')
        assert _sc.cn_quotes('“他走了。"') == '“他走了。”'
        _fixed = _sc.cn_quotes('他说："走吧。"')
        assert _fixed == '他说：“走吧。”', _fixed
        assert _sc.cn_quotes(_fixed) == _fixed, "cn_quotes 不幂等"

        # [7c] 引号不配对容差可配（默认 1）：tol=0 报、tol=1 不报
        _md = RUN_DIR / "rounds" / "_quote_probe" / "引号探针.md"
        _md.parent.mkdir(parents=True, exist_ok=True)
        _md.write_text("第1章 起\n\n他说“走。\n", encoding="utf-8")
        _base_rules = _rules.Rules()
        _book_q = _model.load_book(_md, _base_rules.chapter_pattern)
        _base_rules.thresholds["quote_imbalance_tolerance"] = 0
        _q0 = [f for f in _sc.scan_hard(_book_q, _base_rules) if f["rule"] == "hard.quote_unbalanced"]
        _base_rules.thresholds["quote_imbalance_tolerance"] = 1
        _q1 = [f for f in _sc.scan_hard(_book_q, _base_rules) if f["rule"] == "hard.quote_unbalanced"]
        assert len(_q0) == 1 and len(_q1) == 0, (len(_q0), len(_q1))

        # [7d] docx 前置页不随轮次累加（书名/副标题只出现一次）
        _out = RUN_DIR / "rounds" / "_fm_probe" / "稿子.docx"
        _out.parent.mkdir(parents=True, exist_ok=True)
        _paras = ["探针书", "修订版", "第1章 起", "正文一。", "第2章 承", "正文二。"]
        _docx.write_book(_paras, _out, title="探针书", subtitle="修订版",
                         chapter_pattern=_base_rules.chapter_pattern,
                         front_matter=["探针书", "修订版"])
        _b1 = _model.load_book(_out, _base_rules.chapter_pattern)
        assert _b1.front_matter == ["探针书", "修订版"], _b1.front_matter
        _docx.write_book(_paras, _out, title="探针书", subtitle="修订版",
                         chapter_pattern=_base_rules.chapter_pattern,
                         front_matter=list(_b1.front_matter))
        _b2 = _model.load_book(_out, _base_rules.chapter_pattern)
        assert _b2.front_matter == ["探针书", "修订版"], _b2.front_matter

        # [7e] plot 章键不允许路径穿越
        for _bad in ("../../x", "a/b", "..\\y", ""):
            try:
                _plot.safe_chapter_key(_bad)
                raise AssertionError(f"章键 {_bad!r} 应被拒绝")
            except ValueError:
                pass
        assert _plot.safe_chapter_key(" 第30章 ") == "第30章"
        print("[7] 2026-10-27 回归 ok: 撇号/引号配对/容差可配/前置页不累加/章键防穿越")

        print("SELFTEST PASSED")
        return 0
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""本地冒烟：调用引擎 scan，打印人类可读摘要（含 v4 审计）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = PLUGIN_DIR / "engine"
DEFAULT_PROJECT = PLUGIN_DIR / "tests" / "fixture"

sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PROJECT
    proc = subprocess.run(
        [sys.executable, str(ENGINE_DIR / "run.py"), "scan", "--project", str(project)],
        cwd=str(ENGINE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=240,
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace")[-4000:])
    data = json.loads(proc.stdout.decode("utf-8"))
    if data.get("ok") is False:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 1
    print(f"round={data['round']}  stats={data['stats']}")
    print(f"score={data['score']['total']} ({data['score']['grade']})  summary={data['score']['summary']}")
    findings = data["findings"]
    candidates = [f for f in findings if not (f.get("meta") or {}).get("audit")]
    audit_fs = [f for f in findings if (f.get("meta") or {}).get("audit")]
    print(f"candidates={len(candidates)}  audit_findings={len(audit_fs)}")
    for f in findings[:8]:
        print(f"  [{f['severity']}][{f['category']}] {f['rule']} ch{f['chapter']}p{f['para_display']} :: {f['quote'][:60]!r}")

    audit = data.get("audit") or {}
    if audit:
        print(f"\n-- AI audit ({audit.get('engine')}, baseline={audit.get('baseline', {}).get('status')}) --")
        for m in audit.get("metrics", []):
            if m.get("enabled") is False:
                print(f"  {m['id']:<3} {m['name']:<8} 未启用：{m.get('note','')[:60]}")
                continue
            z = m.get("default_zones") or {}
            print(
                f"  {m['id']:<3} {m['name']:<8} value={m.get('book_value')!s:<8} "
                f"baseline={m.get('baseline_value')!s:<8} dev={m.get('deviation_pct')} "
                f"zones={z.get('green')}/{z.get('yellow')}/{z.get('red')} policy={m.get('policy')}"
            )
        for note in audit.get("notes") or []:
            print(f"  note: {note}")
    print("\nartifacts:", data.get("artifacts"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

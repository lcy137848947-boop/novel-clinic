# -*- coding: utf-8 -*-
"""情节拼接冒烟：import 28 章细纲 → validate → list/template。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = PLUGIN_DIR / "engine"
PROJECT = Path(sys.argv[1]) if len(sys.argv) > 1 else PLUGIN_DIR / "tests" / "fixture"
SOURCE = PROJECT / "plot" / "sources" / "第5章_细纲.md"
sys.stdout.reconfigure(encoding="utf-8")


def call(args: list[str], stdin_data: str | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ENGINE_DIR / "run.py"), *args],
        cwd=str(ENGINE_DIR),
        input=stdin_data.encode("utf-8") if stdin_data is not None else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace")[-3000:])
    return json.loads(proc.stdout.decode("utf-8"))


def main() -> int:
    project = str(PROJECT)
    imported = call(["plot", "--project", project, "--action", "import", "--source", str(SOURCE)])
    if imported.get("ok") is False:
        print(json.dumps(imported, ensure_ascii=False, indent=1))
        return 1
    print(f"import: {imported['chapter_key']} beats={imported['beats']} target={imported['target_chars']}")

    validation = call(["plot", "--project", project, "--action", "validate", "--chapter-key", imported["chapter_key"]])
    print(f"validate: pass={validation['pass']} hook={validation['hook']['score']} findings={len(validation['findings'])}")
    for finding in validation["findings"]:
        print(f"  [{finding['severity']}] {finding['code']} {finding.get('beat') or ''} :: {finding['message']}")

    plot = call(["plot", "--project", project, "--action", "list"])
    print(f"list: {len(plot['plots'])} plot(s)")

    templ = call(["plot", "--project", project, "--action", "template", "--chapter-key", "第29章"])
    print(f"template: schema_keys={list(templ['schema']['properties'].keys())} prompt_chars={len(templ['prompt'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

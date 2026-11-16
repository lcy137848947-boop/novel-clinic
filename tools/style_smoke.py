# -*- coding: utf-8 -*-
"""文风粘性冒烟：样本 vs 目标风格、交叉验证。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = PLUGIN_DIR / "engine"
PROJECT = Path(sys.argv[1]) if len(sys.argv) > 1 else PLUGIN_DIR / "tests" / "fixture"
SAMPLES = PROJECT / "styles" / "samples"
sys.stdout.reconfigure(encoding="utf-8")


def call(args: list[str]) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ENGINE_DIR / "run.py"), *args],
        cwd=str(ENGINE_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace")[-3000:])
    return json.loads(proc.stdout.decode("utf-8"))


def show(title: str, result: dict) -> None:
    print(f"{title}: adhesion={result['adhesion']} ({result['verdict']}) / consistency={result['sample_consistency']}")
    for item in result["weakest"][:3]:
        print(f"   弱项 {item['label']}: 目标 {item['value']} vs 样本均值 {item['mean']} (z={item['z']})")


def main() -> int:
    project = str(PROJECT)
    styles = call(["style", "--project", project, "--action", "list"])
    print("profiles:", [(s["name"], s["samples"], s["sample_consistency"]) for s in styles["styles"]])

    prose = str(SAMPLES / "散文_1.md")
    dry = str(SAMPLES / "干句_1.md")
    show("散文样本 → 散文", call(["style", "--project", project, "--action", "check", "--name", "散文", "--text-file", prose]))
    show("干句样本 → 干句", call(["style", "--project", project, "--action", "check", "--name", "干句", "--text-file", dry]))
    show("干句样本 → 散文（应低）", call(["style", "--project", project, "--action", "check", "--name", "散文", "--text-file", dry]))
    show("散文样本 → 干句（应低）", call(["style", "--project", project, "--action", "check", "--name", "干句", "--text-file", prose]))
    show("第2章·第1段 → 干句", call(["style", "--project", project, "--action", "check", "--name", "干句", "--chapter", "2", "--para", "0"]))
    show("第2章·第1段 → 散文", call(["style", "--project", project, "--action", "check", "--name", "散文", "--chapter", "2", "--para", "0"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

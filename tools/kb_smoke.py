# -*- coding: utf-8 -*-
"""知识库冒烟：sync → search → context。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = PLUGIN_DIR / "engine"
PROJECT = Path(sys.argv[1]) if len(sys.argv) > 1 else PLUGIN_DIR / "tests" / "fixture"
sys.stdout.reconfigure(encoding="utf-8")


def call(args: list[str]) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ENGINE_DIR / "run.py"), *args],
        cwd=str(ENGINE_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace")[-3000:])
    return json.loads(proc.stdout.decode("utf-8"))


def main() -> int:
    project = str(PROJECT)
    synced = call(["kb", "--project", project, "--action", "sync"])
    if synced.get("ok") is False:
        print(json.dumps(synced, ensure_ascii=False, indent=1))
        return 1
    print(f"sync: cards={synced['cards']} spoiler={synced['spoiler_cards']}")
    for source in synced["sources"]:
        print(f"  {source['file']}: {source['cards']} cards / {source['authority']} / spoiler={source['spoiler']}")

    searched = call(["kb", "--project", project, "--action", "search", "--query", "引路灯", "--limit", "5"])
    print(f"\nsearch 引路灯: {len(searched['results'])} results")
    for result in searched["results"]:
        print(f"  [{result['authority']}] {result['title']} :: {result['snippet'][:80]}")

    ctx = call(["kb", "--project", project, "--action", "context", "--chapter", "2", "--max-chars", "3000"])
    print(f"\ncontext ch2: keywords={ctx['keywords'][:8]} cards={len(ctx['cards'])} chars={ctx['chars']}")
    for card in ctx["cards"][:6]:
        print(f"  [{card['authority']}] {card['title']} :: matched={card['matched_keywords'][:4]}")

    listed = call(["kb", "--project", project, "--action", "list"])
    print(f"\nlist: cards={listed['count']} sources={len(listed['sources'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

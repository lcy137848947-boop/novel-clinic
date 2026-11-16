# -*- coding: utf-8 -*-
"""KB 源文件结构探针：只看标题/行数，不打印全文。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
if len(sys.argv) < 2:
    raise SystemExit("用法：python tools/kb_probe.py <项目目录>/kb/sources")
SRC = Path(sys.argv[1])
if not SRC.is_dir():
    raise SystemExit(f"目录不存在：{SRC}")

for path in sorted(SRC.glob("*.txt")):
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    print(f"\n=== {path.name} | chars={len(text)} lines={len(lines)} ===")
    print("first lines:")
    for i, line in enumerate([x for x in lines if x.strip()][:12]):
        print(f"  {i:>3}: {line[:60]!r}")
    patterns = {
        "md": re.compile(r"^\s*#{1,6}\s+\S"),
        "chapter": re.compile(r"^\s*第[一二三四五六七八九十百零〇0-9]+章"),
        "cn_num": re.compile(r"^\s*[一二三四五六七八九十百]+、"),
        "section": re.compile(r"^\s*[0-9]+[、.]"),
    }
    for name, rx in patterns.items():
        hits = [(i + 1, line.strip()[:50]) for i, line in enumerate(lines) if rx.match(line)]
        print(f"headings[{name}]={len(hits)}")
        for ln, title in hits[:8]:
            print(f"   L{ln}: {title}")

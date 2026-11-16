# -*- coding: utf-8 -*-
"""小说工坊 · Python 引擎入口

插件（Host 半）通过子进程调用本文件，全部结果以 UTF-8 JSON 输出到 stdout；
日志一律写 stderr，避免污染 JSON 通道。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from novel_engine.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

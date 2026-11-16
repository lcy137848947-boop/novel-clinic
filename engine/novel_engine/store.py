# -*- coding: utf-8 -*-
"""项目 / 轮次 / 报告的落盘。

写入全部走原子写（同目录临时文件 → fsync → os.replace），进程中途被杀不会留下半截 JSON/Markdown；
读取遇到损坏文件会先备份为 `<name>.corrupt-<时间戳>`，再按调用方给不给 default 决定「返回默认值」还是抛
StoreError，避免把损坏数据当成正常数据往下算。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROUND_RE = re.compile(r"^第(\d+)轮$")

_MISSING = object()


class StoreError(RuntimeError):
    """数据文件损坏，且调用方没有提供默认值。"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _quarantine(path: Path) -> Path | None:
    """把损坏的文件另存一份（保留原文件，方便事后排查）。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        shutil.copy2(path, dst)
    except OSError:
        return None
    return dst


def read_json(path: str | Path, default: Any = _MISSING) -> Any:
    """读 JSON。

    - 文件不存在：返回 default；没给 default 时返回 None（与旧行为一致）。
    - 文件损坏（半截 JSON / 非 UTF-8）：先备份，再返回 default；
      调用方没给 default 时抛 StoreError，避免静默当成空数据。
    """
    p = Path(path)
    if not p.exists():
        return None if default is _MISSING else default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        backup = _quarantine(p)
        hint = f"，已备份为 {backup.name}" if backup else "，备份失败"
        if default is _MISSING:
            raise StoreError(f"JSON 损坏：{p}{hint}：{error}") from error
        sys.stderr.write(f"[store] 警告：JSON 损坏，已返回默认值：{p}{hint}：{error}\n")
        return default


def _atomic_write_text(path: Path, text: str) -> Path:
    """原子写：同目录临时文件 + flush/fsync + os.replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def archive_files(files: list[str | Path], base_dir: str | Path | None = None) -> list[str]:
    """把即将被覆盖的产物移进 `<base_dir>/历史/<时间戳>__<原名>`，返回备份路径列表。

    用于「重复扫描同一未应用轮次」「同一轮重复 apply」时保留上一版，避免静默覆盖。
    """
    existing = [p for p in (Path(f) for f in files) if p.exists()]
    if not existing:
        return []
    base = Path(base_dir) if base_dir is not None else existing[0].parent
    hist = base / "历史"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups: list[str] = []
    for src in existing:
        hist.mkdir(parents=True, exist_ok=True)
        dst = hist / f"{stamp}__{src.name}"
        try:
            shutil.move(str(src), str(dst))
        except OSError:
            shutil.copy2(src, dst)
            try:
                src.unlink()
            except OSError:
                pass
        backups.append(str(dst))
    return backups


def write_json(path: str | Path, data: Any) -> Path:
    return _atomic_write_text(Path(path), json.dumps(data, ensure_ascii=False, indent=2))


def write_text(path: str | Path, text: str) -> Path:
    return _atomic_write_text(Path(path), text)


def rounds_dir(project_dir: str | Path) -> Path:
    return Path(project_dir) / "rounds"


def round_name(n: int) -> str:
    return f"第{n}轮"


def list_rounds(project_dir: str | Path) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    rd = rounds_dir(project_dir)
    if not rd.exists():
        return out
    for child in rd.iterdir():
        if child.is_dir():
            m = ROUND_RE.match(child.name)
            if m:
                out.append((int(m.group(1)), child))
    return sorted(out)


def next_round_number(project_dir: str | Path, cfg: dict) -> int:
    base = int(cfg.get("current_round") or 0)
    for n, _ in list_rounds(project_dir):
        base = max(base, n)
    return base + 1


def latest_round(project_dir: str | Path) -> tuple[str, Path] | tuple[None, None]:
    rounds = list_rounds(project_dir)
    if not rounds:
        return None, None
    n, path = rounds[-1]
    return round_name(n), path


def round_dir(project_dir: str | Path, name: str) -> Path:
    p = rounds_dir(project_dir) / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_scan(project_dir: str | Path, name: str, report: dict, markdown: str) -> dict:
    rd = round_dir(project_dir, name)
    # 同一轮重复扫描（引擎按设计复用「已扫未应用」的轮次）前，把上一版产物移进 历史/，不再静默覆盖。
    archived = archive_files([rd / "扫描.json", rd / "改动清单.md", rd / "扫描元信息.json"], base_dir=rd)
    scan_path = rd / "扫描.json"
    md_path = rd / "改动清单.md"
    draft_path = Path(report["project"]["draft_path"])
    write_json(scan_path, report)
    write_text(md_path, markdown)
    write_json(rd / "扫描元信息.json", {
        "round": name,
        "generated_at": report["generated_at"],
        "draft_path": str(draft_path),
        "draft_sha256": report["project"]["draft_sha256"],
        "engine": report["tool"],
        "rule_version": report.get("rule_version"),
    })
    return {"scan": str(scan_path), "markdown": str(md_path), "archived": archived}


def load_scan(project_dir: str | Path, name: str | None = None) -> tuple[dict, str]:
    if name is None:
        name, _ = latest_round(project_dir)
        if name is None:
            raise FileNotFoundError("还没有任何扫描轮次，请先运行 scan")
    p = rounds_dir(project_dir) / name / "扫描.json"
    if not p.exists():
        raise FileNotFoundError(f"{name} 没有扫描结果：{p}")
    return read_json(p), name


def save_apply(project_dir: str | Path, name: str, data: dict) -> dict:
    rd = round_dir(project_dir, name)
    path = write_json(rd / "应用记录.json", data)
    return {"record": str(path)}


def load_apply(project_dir: str | Path, name: str | None = None) -> tuple[dict, str]:
    if name is None:
        rounds = list_rounds(project_dir)
        for n, _ in reversed(rounds):
            p = rounds_dir(project_dir) / round_name(n) / "应用记录.json"
            if p.exists():
                return read_json(p), round_name(n)
        raise FileNotFoundError("还没有应用记录")
    p = rounds_dir(project_dir) / name / "应用记录.json"
    if not p.exists():
        raise FileNotFoundError(f"{name} 没有应用记录")
    return read_json(p), name


def update_status(project_dir: str | Path, **fields) -> dict:
    p = Path(project_dir) / "status.json"
    data = read_json(p, {}) or {}
    data.update(fields)
    data["updated_at"] = now_iso()
    write_json(p, data)
    return data


def load_status(project_dir: str | Path) -> dict:
    return read_json(Path(project_dir) / "status.json", {}) or {}

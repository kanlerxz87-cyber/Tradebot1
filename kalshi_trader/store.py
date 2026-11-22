"""Small JSON persistence helpers (atomic writes, bounded collections)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, payload: Any, *, indent: int | None = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=indent, sort_keys=False, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, path)
        os.chmod(path, 0o644)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return path


def append_bounded(items: list[dict[str, Any]], new_items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Append, de-duplicating on ``id`` and keeping the newest ``limit`` entries."""
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in new_items + list(reversed(items)):
        key = str(item.get("id") or item.get("ts") or "")
        if key and key in seen:
            continue
        seen.add(key)
        merged.append(item)
    merged = list(reversed(merged))
    return merged[-limit:]


def trim_history(
    history: dict[str, list[list[float]]],
    keep_markets: set[str],
    max_points: int,
) -> dict[str, list[list[float]]]:
    """Keep only tracked markets and at most ``max_points`` per series."""
    out: dict[str, list[list[float]]] = {}
    for ticker, points in history.items():
        if ticker not in keep_markets or not points:
            continue
        points = sorted(points, key=lambda p: p[0])
        if len(points) > max_points:
            stride = max(1, len(points) // max_points)
            thinned = points[::stride]
            if thinned[-1] != points[-1]:
                thinned.append(points[-1])
            points = thinned[-max_points:]
        out[ticker] = points
    return out


def human_bytes(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} GB"

"""Small JSON read/write helpers shared by the collector modules."""
import json
import os
import tempfile
from datetime import datetime, timezone


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path, data):
    """Atomic-ish write: write to a temp file then rename, so a crash mid-write
    never leaves the committed JSON file truncated/corrupt."""
    ensure_dir(os.path.dirname(path))
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=False)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

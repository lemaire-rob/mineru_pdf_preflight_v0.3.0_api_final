from __future__ import annotations

from pathlib import Path
import json
import os
import re
import shutil
import tempfile
from typing import Any

INVALID_FILENAME_CHARS = r'<>:"/\\|?*'
CONTROL_CHARS = ''.join(map(chr, range(0, 32)))
FILENAME_TRANSLATION = str.maketrans({c: "_" for c in INVALID_FILENAME_CHARS + CONTROL_CHARS})


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def file_size(path: str | Path) -> int:
    return Path(path).stat().st_size


def mb(size_bytes: int) -> float:
    return round(size_bytes / (1024 * 1024), 3)


def sanitize_filename_part(text: str) -> str:
    text = text.translate(FILENAME_TRANSLATION).strip()
    text = re.sub(r"\s+", " ", text)
    text = text.rstrip(". ")
    return text or "unnamed"


def unique_path(path: str | Path) -> Path:
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 10000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot create unique path for {path}")


def atomic_write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent), suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, path)


def atomic_write_text(path: str | Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent), suffix=".tmp") as f:
        f.write(text)
        tmp = f.name
    os.replace(tmp, path)


def open_in_file_manager(path: str | Path) -> None:
    import subprocess
    p = Path(path)
    if os.name == "nt":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(p)])
    elif shutil.which("open"):
        subprocess.Popen(["open", str(p)])

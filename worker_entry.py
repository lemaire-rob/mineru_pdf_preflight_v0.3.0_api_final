from __future__ import annotations

import json
from pathlib import Path
from .config import RuleConfig
from .pdf_processor import process_pdf
from .utils import atomic_write_json


def main(task_path: str | None, result_path: str | None) -> int:
    if not task_path or not result_path:
        print("worker requires --task and --result")
        return 2
    task = json.loads(Path(task_path).read_text(encoding="utf-8"))
    rule = RuleConfig(**task["rule"]).normalized()
    result = process_pdf(task["src_path"], task["output_root"], rule, progress=lambda m: print(m, flush=True))
    atomic_write_json(result_path, result)
    return 0 if not result.get("error") else 1

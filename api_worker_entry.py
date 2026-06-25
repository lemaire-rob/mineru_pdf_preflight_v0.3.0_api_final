from __future__ import annotations

import json
from pathlib import Path
from .config import ApiConfig
from .api_client import MinerUApiClient
from .utils import atomic_write_json


def main(task_path: str | None, result_path: str | None) -> int:
    if not task_path or not result_path:
        print("api worker requires --task and --result")
        return 2
    task = json.loads(Path(task_path).read_text(encoding="utf-8"))
    config = ApiConfig(**task["api"]).normalized()
    client = MinerUApiClient(config)
    action = task.get("action", "bind_check")
    if action == "bind_check":
        result = client.bind_check()
    elif action == "extract_files":
        result = {"ok": True, "results": client.extract_files(task.get("files", []), task["out_dir"], progress=lambda m: print(m, flush=True))}
    else:
        result = {"ok": False, "message": f"unknown action: {action}"}
    atomic_write_json(result_path, result)
    return 0 if result.get("ok") else 1

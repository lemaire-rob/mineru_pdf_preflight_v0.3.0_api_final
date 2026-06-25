from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterable
import json
import os
import traceback

from .config import ApiConfig, DEFAULT_BASE_URL
from .utils import ensure_dir, sanitize_filename_part

ApiProgressFn = Callable[[str], None]


def _import_mineru_sdk():
    try:
        from mineru import MinerU  # type: ignore
        return MinerU
    except Exception as exc:
        raise RuntimeError(
            "未安装 mineru-open-sdk，无法调用 MinerU API。请使用项目内 GitHub Actions 正式构建版，或在源码环境安装 requirements.txt。"
        ) from exc


def save_result(result: Any, out_dir: str | Path, base_name: str, progress: ApiProgressFn | None = None) -> dict[str, Any]:
    out_dir = ensure_dir(out_dir)
    base = sanitize_filename_part(base_name)
    saved: dict[str, Any] = {}

    def log(msg: str) -> None:
        if progress:
            progress(msg)

    # SDK helpers if available.
    if hasattr(result, "save_all"):
        all_dir = ensure_dir(out_dir / f"{base}_mineru_result")
        try:
            result.save_all(str(all_dir))
            saved["all_dir"] = str(all_dir)
            log(f"已保存完整结果：{all_dir}")
        except Exception as exc:
            saved["save_all_error"] = str(exc)

    if getattr(result, "markdown", None):
        md_path = out_dir / f"{base}.md"
        md_path.write_text(str(result.markdown), encoding="utf-8")
        saved["markdown"] = str(md_path)

    # Optional format helpers.
    for fmt, helper, suffix in [
        ("docx", "save_docx", ".docx"),
        ("html", "save_html", ".html"),
        ("latex", "save_latex", ".tex"),
    ]:
        if hasattr(result, helper):
            p = out_dir / f"{base}{suffix}"
            try:
                getattr(result, helper)(str(p))
                saved[fmt] = str(p)
            except Exception:
                pass

    # Save a compact metadata snapshot.
    meta = {}
    for key in ["state", "progress", "task_id", "content_list", "images"]:
        try:
            val = getattr(result, key)
            if key == "images":
                val = [getattr(img, "name", str(img)) for img in val]
            meta[key] = val
        except Exception:
            pass
    (out_dir / f"{base}.metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    saved["metadata"] = str(out_dir / f"{base}.metadata.json")
    return saved


class MinerUApiClient:
    def __init__(self, config: ApiConfig):
        self.config = config.normalized()
        self._client = None

    def _make_client(self):
        MinerU = _import_mineru_sdk()
        token = self.config.token or os.getenv("MINERU_TOKEN", "")
        if self.config.mode == "flash":
            return MinerU(base_url=self.config.base_url or DEFAULT_BASE_URL)
        return MinerU(token or None, base_url=self.config.base_url or DEFAULT_BASE_URL)

    def bind_check(self) -> dict[str, Any]:
        # This is intentionally a local SDK construction check. It does not upload a file.
        token = self.config.token or os.getenv("MINERU_TOKEN", "")
        if self.config.mode == "precision" and not token:
            return {"ok": False, "message": "精准解析模式需要 API Token。"}
        try:
            client = self._make_client()
            close = getattr(client, "close", None)
            if callable(close):
                close()
            return {"ok": True, "message": "SDK 初始化成功；Token 已绑定到本机当前配置。未上传任何文件。"}
        except Exception as exc:
            return {"ok": False, "message": str(exc), "traceback": traceback.format_exc()}

    def extract_file(self, file_path: str | Path, out_dir: str | Path, progress: ApiProgressFn | None = None) -> dict[str, Any]:
        file_path = Path(file_path)
        out_dir = ensure_dir(out_dir)
        if progress:
            progress(f"开始调用 MinerU API：{file_path.name}")
        client = self._make_client()
        try:
            if self.config.mode == "flash":
                result = client.flash_extract(str(file_path), timeout=self.config.timeout_seconds)
            else:
                kwargs: dict[str, Any] = {
                    "timeout": self.config.timeout_seconds,
                }
                if self.config.model != "auto":
                    kwargs["model"] = self.config.model
                kwargs["ocr"] = self.config.ocr
                kwargs["formula"] = self.config.formula
                kwargs["table"] = self.config.table
                if self.config.language:
                    kwargs["language"] = self.config.language
                if self.config.extra_formats:
                    kwargs["extra_formats"] = self.config.extra_formats
                result = client.extract(str(file_path), **kwargs)
            saved = save_result(result, out_dir, file_path.stem, progress)
            state = getattr(result, "state", "unknown")
            task_id = getattr(result, "task_id", "")
            return {"ok": True, "file": str(file_path), "state": state, "task_id": task_id, "saved": saved, "error": ""}
        except Exception as exc:
            return {"ok": False, "file": str(file_path), "error": str(exc), "traceback": traceback.format_exc()}
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def extract_files(self, files: Iterable[str | Path], out_dir: str | Path, progress: ApiProgressFn | None = None) -> list[dict[str, Any]]:
        results = []
        for f in files:
            results.append(self.extract_file(f, out_dir, progress=progress))
        return results

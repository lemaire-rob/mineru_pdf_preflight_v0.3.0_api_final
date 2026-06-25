from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
import json
import os
from typing import Any, Dict

APP_NAME = "MinerU_PDF_Preflight"
DEFAULT_BASE_URL = "https://mineru.net/api/v4"
DEFAULT_FILENAME_TEMPLATE = "{name}__part{part:03d}_p{start:03d}-{end:03d}.pdf"


def user_config_dir() -> Path:
    base = os.getenv("APPDATA") or os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class RuleConfig:
    max_pages: int = 200
    max_size_mb: int = 200
    strategy: str = "page_first"  # page_first / size_first / both
    compression_level: str = "medium"  # none / light / medium / strong
    min_dpi: int = 150
    keep_bookmarks: bool = True
    keep_ocr_text: bool = True
    filename_template: str = DEFAULT_FILENAME_TEMPLATE

    def normalized(self) -> "RuleConfig":
        self.max_pages = max(1, int(self.max_pages))
        self.max_size_mb = max(1, int(self.max_size_mb))
        self.min_dpi = max(36, int(self.min_dpi))
        if self.strategy not in {"page_first", "size_first", "both"}:
            self.strategy = "page_first"
        if self.compression_level not in {"none", "light", "medium", "strong"}:
            self.compression_level = "medium"
        if not self.filename_template:
            self.filename_template = DEFAULT_FILENAME_TEMPLATE
        return self

    @property
    def max_size_bytes(self) -> int:
        return int(self.max_size_mb) * 1024 * 1024


@dataclass
class ApiConfig:
    enabled: bool = False
    base_url: str = DEFAULT_BASE_URL
    token: str = ""
    save_token: bool = False
    mode: str = "precision"  # precision / flash
    model: str = "vlm"  # vlm / pipeline / html / auto
    ocr: bool = False
    formula: bool = True
    table: bool = True
    language: str = "ch"
    extra_formats: list[str] = field(default_factory=lambda: ["docx", "html", "latex"])
    timeout_seconds: int = 1800
    upload_after_process: bool = False
    save_api_results: bool = True

    def normalized(self) -> "ApiConfig":
        self.base_url = (self.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if self.mode not in {"precision", "flash"}:
            self.mode = "precision"
        if self.model not in {"auto", "vlm", "pipeline", "html"}:
            self.model = "vlm"
        self.language = (self.language or "ch").strip()
        self.timeout_seconds = max(60, int(self.timeout_seconds))
        if not isinstance(self.extra_formats, list):
            self.extra_formats = []
        return self

    def masked_token(self) -> str:
        if not self.token:
            return ""
        if len(self.token) <= 8:
            return "****"
        return self.token[:4] + "****" + self.token[-4:]


@dataclass
class AppConfig:
    rule: RuleConfig = field(default_factory=RuleConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    last_output_dir: str = ""
    memory_safe_mode: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        rule = RuleConfig(**data.get("rule", {})).normalized()
        api_data = data.get("api", {})
        api = ApiConfig(**api_data).normalized()
        return cls(
            rule=rule,
            api=api,
            last_output_dir=data.get("last_output_dir", ""),
            memory_safe_mode=bool(data.get("memory_safe_mode", True)),
        )

    def to_dict(self, include_token: bool = False) -> Dict[str, Any]:
        data = asdict(self)
        if not include_token:
            data["api"]["token"] = ""
            data["api"]["save_token"] = False
        return data


def default_config_path() -> Path:
    return user_config_dir() / "app_config.json"


def load_config(path: str | Path | None = None) -> AppConfig:
    p = Path(path) if path else default_config_path()
    if not p.exists():
        return AppConfig()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return AppConfig.from_dict(data)
    except Exception:
        return AppConfig()


def save_config(config: AppConfig, path: str | Path | None = None) -> Path:
    p = Path(path) if path else default_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    include_token = bool(config.api.save_token)
    p.write_text(json.dumps(config.to_dict(include_token=include_token), ensure_ascii=False, indent=2), encoding="utf-8")
    return p

from __future__ import annotations

import copy
import fnmatch
import tomllib
from pathlib import Path
from typing import Any

from .paths import config_path, lbh_dir

DEFAULT_CONFIG_TEXT = """
schema = "lbh.config.v1"

[index]
include = ["**/*"]
exclude = [
  ".git/**",
  ".lbh/**",
  "node_modules/**",
  "vendor/**",
  "dist/**",
  "build/**",
  "coverage/**",
  ".next/**",
  ".turbo/**",
  "*.lock",
  "package-lock.json",
  "pnpm-lock.yaml",
  "yarn.lock",
  ".env",
  ".env.*",
  "*.pem",
  "*.key",
  "*.p12",
  "*.crt",
  "id_rsa",
  "id_ed25519",
  "secrets.*",
  "credentials.*"
]
max_file_bytes = 300000
content_preview_chars = 3000

[ranking]
path_weight = 0.25
symbol_weight = 0.25
import_weight = 0.15
content_weight = 0.25
graph_weight = 0.10

[context]
initial_file_limit = 12
snippet_lines = 80
max_prompt_chars = 60000
max_lazy_read_lines = 500
max_tool_requests_per_round = 12

[security]
redact_secrets = true
require_read_before_modify = true
allow_new_files_without_read = true
""".strip() + "\n"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


DEFAULT_CONFIG: dict[str, Any] = tomllib.loads(DEFAULT_CONFIG_TEXT)


class Config:
    def __init__(self, data: dict[str, Any]):
        self.data = _deep_merge(DEFAULT_CONFIG, data)

    @classmethod
    def load(cls, repo_root: Path) -> "Config":
        path = config_path(repo_root)
        if not path.exists():
            return cls(DEFAULT_CONFIG)
        with path.open("rb") as f:
            data = tomllib.load(f)
        return cls(data)

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.data.get(section, {}).get(key, default)

    @property
    def include(self) -> list[str]:
        return list(self.get("index", "include", ["**/*"]))

    @property
    def exclude(self) -> list[str]:
        return list(self.get("index", "exclude", []))

    @property
    def max_file_bytes(self) -> int:
        return int(self.get("index", "max_file_bytes", 300000))

    @property
    def content_preview_chars(self) -> int:
        return int(self.get("index", "content_preview_chars", 3000))

    @property
    def initial_file_limit(self) -> int:
        return int(self.get("context", "initial_file_limit", 12))

    @property
    def snippet_lines(self) -> int:
        return int(self.get("context", "snippet_lines", 80))

    @property
    def max_prompt_chars(self) -> int:
        return int(self.get("context", "max_prompt_chars", 60000))

    @property
    def max_lazy_read_lines(self) -> int:
        return int(self.get("context", "max_lazy_read_lines", 500))

    @property
    def max_tool_requests_per_round(self) -> int:
        return int(self.get("context", "max_tool_requests_per_round", 12))

    @property
    def redact_secrets(self) -> bool:
        return bool(self.get("security", "redact_secrets", True))

    @property
    def require_read_before_modify(self) -> bool:
        return bool(self.get("security", "require_read_before_modify", True))

    @property
    def allow_new_files_without_read(self) -> bool:
        return bool(self.get("security", "allow_new_files_without_read", True))

    def is_excluded(self, rel_path: str) -> bool:
        rel = rel_path.replace("\\", "/")
        name = Path(rel).name
        for pat in self.exclude:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat):
                return True
            if pat.endswith("/**") and rel.startswith(pat[:-3].rstrip("/") + "/"):
                return True
        return False

    def is_included(self, rel_path: str) -> bool:
        rel = rel_path.replace("\\", "/")
        if not self.include:
            return True
        return any(fnmatch.fnmatch(rel, pat) or pat == "**/*" for pat in self.include)


def init_config(repo_root: Path, force: bool = False) -> Path:
    lbh_dir(repo_root).mkdir(parents=True, exist_ok=True)
    path = config_path(repo_root)
    if path.exists() and not force:
        return path
    path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return path

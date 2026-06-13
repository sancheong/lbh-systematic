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

[request_classification]
component_limit = 1
broad_terms = [
  "all files",
  "architecture",
  "codebase-wide",
  "design and implement",
  "end-to-end",
  "entire",
  "full implementation",
  "large refactor",
  "migrate",
  "multi-component",
  "overhaul",
  "redesign",
  "rewrite"
]
component_separators = [",", ";", "\\n-", "\\n*", " and "]

[experimental]
enable_broad_request_planning = false

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


def _normalize_rel_path(rel_path: str) -> str:
    return rel_path.replace("\\", "/")


def _matches_exclude_pattern(rel_path: str, pattern: str) -> bool:
    name = Path(rel_path).name
    if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(name, pattern):
        return True
    if pattern.endswith("/**") and rel_path.startswith(pattern[:-3].rstrip("/") + "/"):
        return True
    return False


def _matches_include_pattern(rel_path: str, pattern: str) -> bool:
    return pattern == "**/*" or fnmatch.fnmatch(rel_path, pattern)


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
        return self._section(section).get(key, default)

    def _section(self, name: str) -> dict[str, Any]:
        section = self.data.get(name, {})
        if isinstance(section, dict):
            return section
        return {}

    def _list(self, section: str, key: str, default: list[str]) -> list[str]:
        return list(self.get(section, key, default))

    def _int(self, section: str, key: str, default: int) -> int:
        return int(self.get(section, key, default))

    def _bool(self, section: str, key: str, default: bool) -> bool:
        return bool(self.get(section, key, default))

    @property
    def include(self) -> list[str]:
        return self._list("index", "include", ["**/*"])

    @property
    def exclude(self) -> list[str]:
        return self._list("index", "exclude", [])

    @property
    def max_file_bytes(self) -> int:
        return self._int("index", "max_file_bytes", 300000)

    @property
    def content_preview_chars(self) -> int:
        return self._int("index", "content_preview_chars", 3000)

    @property
    def initial_file_limit(self) -> int:
        return self._int("context", "initial_file_limit", 12)

    @property
    def snippet_lines(self) -> int:
        return self._int("context", "snippet_lines", 80)

    @property
    def max_prompt_chars(self) -> int:
        return self._int("context", "max_prompt_chars", 60000)

    @property
    def max_lazy_read_lines(self) -> int:
        return self._int("context", "max_lazy_read_lines", 500)

    @property
    def max_tool_requests_per_round(self) -> int:
        return self._int("context", "max_tool_requests_per_round", 12)

    @property
    def request_classification_component_limit(self) -> int:
        return self._int("request_classification", "component_limit", 1)

    @property
    def request_classification_broad_terms(self) -> list[str]:
        return self._list("request_classification", "broad_terms", [])

    @property
    def request_classification_component_separators(self) -> list[str]:
        return self._list("request_classification", "component_separators", [])

    @property
    def enable_broad_request_planning(self) -> bool:
        return self._bool("experimental", "enable_broad_request_planning", False)

    @property
    def redact_secrets(self) -> bool:
        return self._bool("security", "redact_secrets", True)

    @property
    def require_read_before_modify(self) -> bool:
        return self._bool("security", "require_read_before_modify", True)

    @property
    def allow_new_files_without_read(self) -> bool:
        return self._bool("security", "allow_new_files_without_read", True)

    def is_excluded(self, rel_path: str) -> bool:
        rel = _normalize_rel_path(rel_path)
        for pattern in self.exclude:
            if _matches_exclude_pattern(rel, pattern):
                return True
        return False

    def is_included(self, rel_path: str) -> bool:
        rel = _normalize_rel_path(rel_path)
        include_patterns = self.include
        if not include_patterns:
            return True
        for pattern in include_patterns:
            if _matches_include_pattern(rel, pattern):
                return True
        return False


def init_config(repo_root: Path, force: bool = False) -> Path:
    lbh_dir(repo_root).mkdir(parents=True, exist_ok=True)
    path = config_path(repo_root)
    if path.exists() and not force:
        return path
    path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return path

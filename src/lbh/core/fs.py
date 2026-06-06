from __future__ import annotations

import hashlib
import re
from pathlib import Path

SECRET_PATTERNS = [
    re.compile(r"(?i)(OPENAI_API_KEY|ANTHROPIC_API_KEY|AWS_SECRET_ACCESS_KEY|DATABASE_URL|JWT_SECRET|PRIVATE_KEY)\s*=\s*[^\s]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
]

LANG_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".sh": "shell",
}

TEXT_SUFFIXES = set(LANG_BY_SUFFIX) | {
    ".txt", ".css", ".scss", ".html", ".xml", ".vue", ".svelte", ".dockerfile"
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def looks_binary(path: Path, sample_size: int = 4096) -> bool:
    try:
        data = path.read_bytes()[:sample_size]
    except OSError:
        return True
    if b"\0" in data:
        return True
    suffix = path.suffix.lower()
    if suffix and suffix not in TEXT_SUFFIXES and len(data) > 0:
        # Unknown files are allowed if they decode cleanly.
        pass
    try:
        data.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def detect_lang(path: str | Path) -> str:
    p = Path(path)
    suffix = p.suffix.lower()
    if p.name.lower() == "dockerfile":
        return "dockerfile"
    return LANG_BY_SUFFIX.get(suffix, "text")


def read_text(path: Path, max_chars: int | None = None) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if max_chars is not None:
        return text[:max_chars]
    return text


def redact_secrets(text: str) -> str:
    out = text
    for pat in SECRET_PATTERNS:
        out = pat.sub("[LBH_REDACTED_SECRET]", out)
    return out


def line_slice(text: str, start: int, end: int) -> list[tuple[int, str]]:
    lines = text.splitlines()
    start = max(1, start)
    end = min(max(start, end), len(lines))
    return [(i, lines[i - 1]) for i in range(start, end + 1)]


def format_numbered_lines(text: str, start: int = 1, end: int | None = None) -> str:
    lines = text.splitlines()
    if end is None:
        end = len(lines)
    selected = line_slice(text, start, end)
    width = len(str(end))
    return "\n".join(f"{num:>{width}} | {line}" for num, line in selected)


def classify_layer(path: str) -> str:
    p = path.lower()
    if any(x in p for x in ["test", "spec", "__tests__"]):
        return "test"
    if any(x in p for x in ["payment", "billing", "checkout", "invoice", "order"]):
        return "payment"
    if any(x in p for x in ["notification", "notify", "email", "sms", "push", "message"]):
        return "notification"
    if any(x in p for x in ["config", "settings", "env"]):
        return "config"
    if any(x in p for x in ["route", "controller", "api", "handler"]):
        return "entrypoint"
    if any(x in p for x in ["worker", "queue", "job", "task"]):
        return "worker"
    return "other"


def is_test_path(path: str) -> bool:
    p = path.lower()
    return any(x in p for x in ["test", "spec", "__tests__"])


def is_config_path(path: str) -> bool:
    p = path.lower()
    return any(x in p for x in ["config", "settings", ".toml", ".yaml", ".yml", ".json"])

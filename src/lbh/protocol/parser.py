from __future__ import annotations

import json
import re
from typing import Any

from lbh.core.models import ReadRange, ToolRequest
from lbh.core.paths import normalize_relpath

FENCE_RE = re.compile(r"```([A-Za-z0-9_-]+)?\s*\n(.*?)```", re.S)
LEGACY_READ_RE = re.compile(r"\[READ:\s*([^\]#\s]+)(?:#(\d+)-(\d+))?\s*\]")
SENTINEL_DIFF_RE = re.compile(r"<<<LBH_DIFF_BEGIN[^>]*>>>\s*(.*?)\s*<<<LBH_DIFF_END>>>", re.S)


def _parse_ranges(value: Any) -> list[ReadRange]:
    ranges: list[ReadRange] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                start = int(item.get("start", 1))
                end = int(item.get("end", start))
                ranges.append(ReadRange(start, end))
    return ranges


def parse_tool_requests(raw: str) -> list[ToolRequest]:
    requests: list[ToolRequest] = []

    for lang, body in FENCE_RE.findall(raw):
        if (lang or "").strip().lower() != "lbh-tool":
            continue
        data = json.loads(body.strip())
        for item in data.get("requests", []):
            op = str(item.get("op", "")).upper()
            path = item.get("path", "") or ""
            if path:
                path = normalize_relpath(path)
            requests.append(
                ToolRequest(
                    op=op,
                    path=path,
                    ranges=_parse_ranges(item.get("ranges", [])),
                    pattern=item.get("pattern", "") or "",
                    query=item.get("query", "") or "",
                    globs=list(item.get("globs", [])) if isinstance(item.get("globs", []), list) else [],
                    max_results=int(item.get("max_results", 80)),
                    why=item.get("why", "") or "",
                    raw=item,
                )
            )

    # Legacy syntax is intentionally simple and useful in manual paste workflows.
    for m in LEGACY_READ_RE.finditer(raw):
        path = normalize_relpath(m.group(1))
        if m.group(2) and m.group(3):
            ranges = [ReadRange(int(m.group(2)), int(m.group(3)))]
        else:
            ranges = []
        requests.append(ToolRequest(op="READ", path=path, ranges=ranges, why="legacy READ request"))

    return requests


def extract_diff(raw: str) -> str | None:
    sentinel = SENTINEL_DIFF_RE.findall(raw)
    if len(sentinel) == 1:
        return sentinel[0].strip() + "\n"
    if len(sentinel) > 1:
        raise ValueError("multiple LBH diff sentinel blocks found")

    lbh_blocks: list[str] = []
    diff_blocks: list[str] = []
    for lang, body in FENCE_RE.findall(raw):
        normalized = (lang or "").strip().lower()
        if normalized == "lbh-diff":
            lbh_blocks.append(body.strip())
        elif normalized == "diff":
            diff_blocks.append(body.strip())

    if len(lbh_blocks) == 1:
        return lbh_blocks[0] + "\n"
    if len(lbh_blocks) > 1:
        raise ValueError("multiple lbh-diff blocks found")
    if len(diff_blocks) == 1:
        return diff_blocks[0] + "\n"
    if len(diff_blocks) > 1:
        raise ValueError("multiple diff blocks found")

    # Last resort: raw response itself may be a diff.
    stripped = raw.strip()
    if stripped.startswith("diff --git "):
        return stripped + "\n"
    return None

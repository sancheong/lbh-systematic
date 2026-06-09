from __future__ import annotations

import json
import re
from typing import Any

from lbh.core.models import HashLinePatchEdit, ReadRange, ToolRequest
from lbh.core.paths import normalize_relpath

FENCE_RE = re.compile(r"(?ms)^```(?!`)([^\n]*)\n(.*?)^```(?!`)[ \t]*$")
LEGACY_READ_RE = re.compile(r"\[READ:\s*([^\]#\s]+)(?:#(\d+)-(\d+))?\s*\]")
SENTINEL_DIFF_RE = re.compile(r"(?ms)^<<<LBH_DIFF_BEGIN[^>\n]*>>>[ \t]*\n(.*?)^<<<LBH_DIFF_END>>>[ \t]*$")
TOP_LEVEL_DIFF_FENCE_RE = re.compile(r"(?ms)^```(?!`)(?:lbh-diff|diff)(?:[^\n]*)\n.*?^```(?!`)[ \t]*$")
VARIABLE_FENCE_RE = re.compile(r"(?ms)^(`{3,})([^\n]*)\n(.*?)^\1[ \t]*$")
TOP_LEVEL_HASHLINE_PATCH_FENCE_RE = re.compile(r"(?ms)^(`{3,})lbh-hashline-patch(?:[^\n]*)\n.*?^\1[ \t]*$")


def _parse_ranges(value: Any) -> list[ReadRange]:
    ranges: list[ReadRange] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                start = int(item.get("start", 1))
                end = int(item.get("end", start))
                ranges.append(ReadRange(start, end))
    return ranges


def _normalize_fence_lang(info: str | None) -> str:
    if not info:
        return ""
    stripped = info.strip()
    if not stripped:
        return ""
    return stripped.split()[0].lower()


def _iter_variable_fences(raw: str) -> list[tuple[str, str]]:
    fences: list[tuple[str, str]] = []
    for _delim, info, body in VARIABLE_FENCE_RE.findall(raw):
        fences.append((info, body))
    return fences


def _extract_first_json_object(raw: str, start: int = 0) -> tuple[int, int, str] | None:
    obj_start = raw.find("{", start)
    if obj_start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for idx in range(obj_start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return obj_start, idx + 1, raw[obj_start : idx + 1]
    return None


def _extract_unfenced_labeled_json(raw: str, label: str) -> tuple[int, int, str] | None:
    leading_ws = len(raw) - len(raw.lstrip())
    if leading_ws >= len(raw):
        return None

    line_end = raw.find("\n", leading_ws)
    if line_end == -1:
        first_line = raw[leading_ws:].strip()
        body_start = len(raw)
    else:
        first_line = raw[leading_ws:line_end].strip()
        body_start = line_end + 1

    if not first_line:
        return None

    parts = first_line.split()
    if not parts or parts[0] != label:
        return None

    json_obj = _extract_first_json_object(raw, body_start)
    if json_obj is None:
        return None
    _obj_start, obj_end, payload = json_obj
    return leading_ws, obj_end, payload


def strip_diff_payloads(raw: str) -> str:
    without_sentinels = SENTINEL_DIFF_RE.sub("", raw)
    without_diff_fences = TOP_LEVEL_DIFF_FENCE_RE.sub("", without_sentinels)
    stripped = raw.strip()
    if stripped.startswith("diff --git "):
        return ""
    return without_diff_fences


def strip_hashline_patch_payloads(raw: str) -> str:
    stripped = TOP_LEVEL_HASHLINE_PATCH_FENCE_RE.sub("", raw)
    unfenced = _extract_unfenced_labeled_json(stripped, "lbh-hashline-patch")
    if unfenced is None:
        return stripped
    start, end, _payload = unfenced
    return stripped[:start] + stripped[end:]


def extract_hashline_patch(raw: str) -> list[HashLinePatchEdit] | None:
    blocks: list[dict[str, Any]] = []
    for lang, body in _iter_variable_fences(raw):
        if _normalize_fence_lang(lang) != "lbh-hashline-patch":
            continue
        blocks.append(json.loads(body.strip()))

    if not blocks:
        unfenced = _extract_unfenced_labeled_json(raw, "lbh-hashline-patch")
        if unfenced is not None:
            _start, _end, payload = unfenced
            blocks.append(json.loads(payload))

    if not blocks:
        return None
    if len(blocks) > 1:
        raise ValueError("multiple lbh-hashline-patch blocks found")

    data = blocks[0]
    edits_raw = data.get("edits", [])
    if not isinstance(edits_raw, list):
        raise ValueError("lbh-hashline-patch edits must be a list")

    edits: list[HashLinePatchEdit] = []
    for item in edits_raw:
        if not isinstance(item, dict):
            raise ValueError("lbh-hashline-patch edit items must be objects")
        edits.append(
            HashLinePatchEdit(
                path=normalize_relpath(str(item.get("path", ""))),
                start_line=int(item.get("start_line", 0)),
                start_hash=str(item.get("start_hash", "")),
                end_line=int(item.get("end_line", 0)),
                end_hash=str(item.get("end_hash", "")),
                new=str(item.get("new", "")),
                block_hash=str(item.get("block_hash", "")),
                old=str(item.get("old", "")),
                create=bool(item.get("create", False)),
            )
        )
    return edits


def parse_tool_requests(raw: str) -> list[ToolRequest]:
    requests: list[ToolRequest] = []
    found_fenced = False

    for lang, body in FENCE_RE.findall(raw):
        if _normalize_fence_lang(lang) != "lbh-tool":
            continue
        found_fenced = True
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

    if not found_fenced:
        unfenced = _extract_unfenced_labeled_json(raw, "lbh-tool")
        if unfenced is not None:
            _start, _end, payload = unfenced
            data = json.loads(payload)
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
        normalized = _normalize_fence_lang(lang)
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

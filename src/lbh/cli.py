from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lbh import __version__
from lbh.context.packer import ContextPacker
from lbh.core.config import Config, init_config
from lbh.core.fs import format_numbered_lines, read_text, redact_secrets
from lbh.core.paths import find_repo_root, index_dir, resolve_repo_path
from lbh.indexer.builder import RepoIndexer
from lbh.patch.apply import git_apply, git_apply_check
from lbh.patch.diff import validate_diff
from lbh.protocol.parser import extract_diff, parse_tool_requests
from lbh.protocol.tools import ToolExecutor
from lbh.search.ranker import SearchRanker
from lbh.session.manager import SessionManager


def cmd_init(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    path = init_config(repo, force=args.force)
    (repo / ".lbh" / "index").mkdir(parents=True, exist_ok=True)
    (repo / ".lbh" / "sessions").mkdir(parents=True, exist_ok=True)
    print(f"LBH initialized: {path}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    config = Config.load(repo)
    stats = RepoIndexer(repo, config).rebuild()
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"Indexed {stats['files']} files, {stats['symbols']} symbols, {stats['imports']} imports, {stats['edges']} edges in {stats['elapsed_ms']}ms")
    return 0


def ensure_index(repo: Path) -> None:
    db = index_dir(repo) / "files.sqlite"
    if not db.exists():
        raise SystemExit("LBH index not found. Run: lbh index")


def cmd_search(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    ensure_index(repo)
    ranked = SearchRanker(repo).rank(args.query, limit=args.limit)
    for i, item in enumerate(ranked, start=1):
        reasons = "; ".join(item.reasons[:4])
        print(f"{i:>2}. {item.path}  score={item.score:.2f} layer={item.layer}")
        if reasons:
            print(f"    {reasons}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    ensure_index(repo)
    config = Config.load(repo)
    ranked = SearchRanker(repo).rank(args.request, limit=args.limit or config.initial_file_limit)
    manager = SessionManager(repo)
    session = manager.create(args.request, ranked=[item.__dict__ for item in ranked])
    prompt = ContextPacker(repo, config).build_initial_prompt(args.request, ranked)
    session.initial_prompt.write_text(prompt, encoding="utf-8")
    print(f"Session: {session.root}")
    print(f"Initial prompt: {session.initial_prompt}")
    print("Paste initial_prompt.md into your model. Then save the model response and run:")
    print(f"  lbh respond response.md --session {session.root}")
    return 0


def cmd_respond(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    config = Config.load(repo)
    session_root = Path(args.session)
    if not session_root.is_absolute():
        session_root = (Path.cwd() / session_root).resolve()
    manager = SessionManager(repo)
    raw = Path(args.response_file).read_text(encoding="utf-8")
    manager.append_event(session_root, {"type": "model_response", "file": str(args.response_file)})

    requests = parse_tool_requests(raw)
    diff = extract_diff(raw)

    if requests and diff:
        print("Response contains both tool requests and diff. Please provide only one kind of response.", file=sys.stderr)
        return 2

    if requests:
        executor = ToolExecutor(repo, config, session_root)
        append_text = executor.execute(requests)
        out = manager.next_context_append_path(session_root)
        out.write_text(append_text, encoding="utf-8")
        manager.append_event(session_root, {"type": "context_append", "file": out.name, "request_count": len(requests)})
        print(f"Context append written: {out}")
        print("Paste this context_append file back into the model.")
        return 0

    if diff:
        manifest = manager.load_manifest(session_root)
        validation = validate_diff(diff, repo, config, read_files=manifest.get("read_files", {}))
        session_paths = manager.paths(session_root)
        session_paths.patch.write_text(diff, encoding="utf-8")
        manifest["patch"] = {"path": session_paths.patch.name, "validation": validation.__dict__}
        manager.write_manifest(session_root, manifest)
        if validation.ok:
            print(f"Patch extracted and validated: {session_paths.patch}")
            print(f"Modified files: {', '.join(validation.modified_files) or '(none)'}")
            print("Next:")
            print(f"  lbh apply {session_paths.patch} --session {session_root} --check")
        else:
            print(f"Patch extracted but validation failed: {session_paths.patch}", file=sys.stderr)
            for err in validation.errors:
                print(f"- {err}", file=sys.stderr)
            return 3
        return 0

    print("No lbh-tool request or diff found in response.", file=sys.stderr)
    return 1


def cmd_read(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    config = Config.load(repo)
    path = resolve_repo_path(repo, args.path)
    text = read_text(path)
    if config.redact_secrets:
        text = redact_secrets(text)
    start = 1
    end = len(text.splitlines())
    if args.range:
        a, b = args.range.split(":", 1)
        start, end = int(a), int(b)
    rel = path.relative_to(repo).as_posix()
    print(f'<file path="{rel}" lines="{start}-{end}">')
    print(format_numbered_lines(text, start, end))
    print("</file>")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    config = Config.load(repo)
    diff_path = Path(args.patch)
    if not diff_path.is_absolute():
        diff_path = (Path.cwd() / diff_path).resolve()
    diff = diff_path.read_text(encoding="utf-8")
    read_files = {}
    if args.session:
        session_root = Path(args.session)
        if not session_root.is_absolute():
            session_root = (Path.cwd() / session_root).resolve()
        read_files = SessionManager(repo).load_manifest(session_root).get("read_files", {})
    validation = validate_diff(diff, repo, config, read_files=read_files)
    if not validation.ok:
        print("Diff validation failed:", file=sys.stderr)
        for err in validation.errors:
            print(f"- {err}", file=sys.stderr)
        return 2
    ok, output = git_apply_check(repo, diff_path)
    if not ok:
        print("git apply --check failed:", file=sys.stderr)
        print(output, file=sys.stderr)
        return 3
    print("git apply --check passed")
    if args.check:
        return 0
    if not args.yes:
        print("Not applying because --yes was not provided.")
        return 0
    output = git_apply(repo, diff_path)
    print(output.strip() or "Patch applied")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    session_root = Path(args.session)
    if not session_root.is_absolute():
        session_root = (Path.cwd() / session_root).resolve()
    manifest = SessionManager(repo).load_manifest(session_root)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    config_exists = (repo / ".lbh" / "config.toml").exists()
    db_exists = (index_dir(repo) / "files.sqlite").exists()
    print(f"repo_root: {repo}")
    print(f"config: {'ok' if config_exists else 'missing'}")
    print(f"index: {'ok' if db_exists else 'missing'}")
    try:
        import sqlite3
        print(f"sqlite: ok {sqlite3.sqlite_version}")
    except Exception as exc:
        print(f"sqlite: error {exc}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lbh", description="Local-Browser-Hybrid context broker")
    p.add_argument("--version", action="version", version=f"lbh {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="initialize .lbh config in current project")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("index", help="build local SQLite index")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("search", help="rank relevant files for a request")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=12)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("ask", help="create a session and initial prompt")
    sp.add_argument("request")
    sp.add_argument("--limit", type=int, default=None)
    sp.set_defaults(func=cmd_ask)

    sp = sub.add_parser("respond", help="process a model response file")
    sp.add_argument("response_file")
    sp.add_argument("--session", required=True)
    sp.set_defaults(func=cmd_respond)

    sp = sub.add_parser("read", help="print a file in LBH context format")
    sp.add_argument("path")
    sp.add_argument("--range", help="line range like 1:120")
    sp.set_defaults(func=cmd_read)

    sp = sub.add_parser("apply", help="validate or apply a diff")
    sp.add_argument("patch")
    sp.add_argument("--session")
    sp.add_argument("--check", action="store_true")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("status", help="show session manifest")
    sp.add_argument("--session", required=True)
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("doctor", help="check LBH project health")
    sp.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

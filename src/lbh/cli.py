from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

from lbh import __version__
from lbh.automation import AutomationOptions, AutomationRunner, ShellBrowserController
from lbh.core.config import Config, init_config
from lbh.core.fs import format_numbered_lines, read_text, redact_secrets
from lbh.core.paths import find_repo_root, index_dir, resolve_repo_path
from lbh.indexer.builder import RepoIndexer
from lbh.search.ranker import SearchRanker
from lbh.session.manager import SessionManager
from lbh.workflow import apply_patch_file, ask_request, process_response_file


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
    result = ask_request(repo, args.request, limit=args.limit)
    print(f"Session: {result.session_root}")
    print(f"Initial prompt: {result.initial_prompt}")
    print("Paste initial_prompt.md into your model. Then save the model response and run:")
    print(f"  lbh respond response.md --session {result.session_root}")
    return 0


def cmd_respond(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    session_root = Path(args.session)
    if not session_root.is_absolute():
        session_root = (Path.cwd() / session_root).resolve()
    outcome = process_response_file(repo, session_root, Path(args.response_file))

    if outcome.kind == "error":
        print(outcome.error_message, file=sys.stderr)
        return outcome.return_code
    if outcome.kind == "context_append" and outcome.context_append is not None:
        print(f"Context append written: {outcome.context_append}")
        print("Paste this context_append file back into the model.")
        return outcome.return_code
    if outcome.kind in {"candidate_ok", "candidate_failed"} and outcome.candidate is not None:
        print(f"Candidate extracted: {outcome.candidate}")
        if outcome.kind == "candidate_ok" and outcome.patch_path is not None:
            print("Candidate validation passed.")
            print(f"Promoted to patch: {outcome.patch_path}")
            print(f"Modified files: {', '.join(outcome.modified_files) or '(none)'}")
            print("Next:")
            print(f"  lbh apply {outcome.patch_path} --session {session_root} --check")
        elif outcome.critique_path is not None and outcome.repair_prompt_path is not None:
            print("Candidate validation failed.", file=sys.stderr)
            print(f"Critique: {outcome.critique_path}", file=sys.stderr)
            print(f"Repair prompt: {outcome.repair_prompt_path}", file=sys.stderr)
            print("Patch was not promoted.", file=sys.stderr)
        return outcome.return_code

    print(outcome.error_message or "No lbh-tool request or diff found in response.", file=sys.stderr)
    return outcome.return_code


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
    diff_path = Path(args.patch)
    if not diff_path.is_absolute():
        diff_path = (Path.cwd() / diff_path).resolve()
    session_root = None
    if args.session:
        session_root = Path(args.session)
        if not session_root.is_absolute():
            session_root = (Path.cwd() / session_root).resolve()
    outcome = apply_patch_file(repo, diff_path, session_root=session_root, check=args.check, yes=args.yes)
    if not outcome.ok:
        if outcome.return_code == 2:
            print("Diff validation failed:", file=sys.stderr)
            for err in outcome.validation_errors:
                print(f"- {err}", file=sys.stderr)
        else:
            print("git apply --check failed:", file=sys.stderr)
            print(outcome.output, file=sys.stderr)
        return outcome.return_code
    if args.check:
        print("git apply --check passed")
        return 0
    print(outcome.output)
    return 0


def build_browser_controller(args: argparse.Namespace) -> ShellBrowserController:
    command_text = args.controller_command or os.environ.get("LBH_BROWSER_CONTROLLER_COMMAND", "")
    if not command_text:
        raise SystemExit(
            "Browser controller command is required. Pass --controller-command or set LBH_BROWSER_CONTROLLER_COMMAND."
        )
    command = tuple(shlex.split(command_text, posix=False))
    return ShellBrowserController(command, timeout_seconds=max(args.timeout_seconds, 60))


def cmd_automate(args: argparse.Namespace) -> int:
    repo = find_repo_root()
    if args.request is None and not args.session:
        print("Provide a request or --session to resume.", file=sys.stderr)
        return 2
    if args.request is not None and args.session:
        print("Provide either a request or --session, not both.", file=sys.stderr)
        return 2
    if args.request is not None:
        ensure_index(repo)
    controller = build_browser_controller(args)
    options = AutomationOptions(
        chrome_profile=args.chrome_profile,
        apply_mode=args.apply_mode,
        max_retries=args.max_retries,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
        controller_kind="shell_command",
        controller_command=tuple(shlex.split(args.controller_command or os.environ.get("LBH_BROWSER_CONTROLLER_COMMAND", ""), posix=False)),
    )
    runner = AutomationRunner(repo, controller, options)
    if args.session:
        session_root = Path(args.session)
        if not session_root.is_absolute():
            session_root = (Path.cwd() / session_root).resolve()
        result = runner.resume(session_root)
    else:
        result = runner.start(args.request, limit=args.limit)
    print(f"Session: {result.session_root}")
    print(f"Automation state: {result.state}")
    if result.chat_ref:
        print(f"Chat ref: {result.chat_ref}")
    if result.latest_outbound_artifact:
        print(f"Latest outbound artifact: {result.latest_outbound_artifact}")
    if result.latest_inbound_response:
        print(f"Latest inbound response: {result.latest_inbound_response}")
    if result.patch_path is not None:
        print(f"Patch: {result.patch_path}")
    if result.state == "blocked":
        print("Automation stopped and is awaiting human intervention.", file=sys.stderr)
        return 3
    if result.state != "completed":
        return 0
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

    sp = sub.add_parser("automate", help="run LBH plus Chrome/ChatGPT automation")
    sp.add_argument("request", nargs="?")
    sp.add_argument("--session", help="resume an existing LBH session")
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--chrome-profile", default="Profile 4")
    sp.add_argument("--controller-command", help="external browser controller command")
    sp.add_argument("--apply-mode", choices=["check", "yes"], default="yes")
    sp.add_argument("--max-retries", type=int, default=2)
    sp.add_argument("--poll-seconds", type=float, default=2.0)
    sp.add_argument("--timeout-seconds", type=int, default=300)
    sp.set_defaults(func=cmd_automate)

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

from pathlib import Path
import subprocess

from lbh.core.fs import format_hashline_lines, short_block_hash, short_line_hash, write_text_exact
from lbh.core.models import HashLinePatchEdit
from lbh.patch.hashline import HashLinePatchError, materialize_hashline_patch


def test_format_hashline_lines():
    text = "alpha\nbeta\n"
    formatted = format_hashline_lines(text, 1, 2)
    lines = formatted.splitlines()
    assert lines[0] == f"1#{short_line_hash('alpha')} | alpha"
    assert lines[1] == f"2#{short_line_hash('beta')} | beta"


def test_materialize_hashline_patch(tmp_path: Path):
    repo = tmp_path
    path = repo / "sample.py"
    path.write_text("def foo():\n    pass\n", encoding="utf-8")

    edit = HashLinePatchEdit(
        path="sample.py",
        start_line=1,
        start_hash=short_line_hash("def foo():"),
        end_line=2,
        end_hash=short_line_hash("    pass"),
        new='def foo():\n    return "ok"',
    )

    materialized = materialize_hashline_patch(repo, [edit])
    assert materialized.modified_files == ["sample.py"]
    assert "diff --git a/sample.py b/sample.py" in materialized.diff
    assert '+    return "ok"' in materialized.diff

    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    patch_path = repo / "candidate.diff"
    write_text_exact(patch_path, materialized.diff)
    proc = subprocess.run(
        ["git", "apply", "--check", str(patch_path)],
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout


def test_materialize_hashline_patch_rejects_stale_hash(tmp_path: Path):
    repo = tmp_path
    path = repo / "sample.py"
    path.write_text("def foo():\n    pass\n", encoding="utf-8")

    edit = HashLinePatchEdit(
        path="sample.py",
        start_line=1,
        start_hash="deadbe",
        end_line=2,
        end_hash=short_line_hash("    pass"),
        new='def foo():\n    return "ok"',
    )

    try:
        materialize_hashline_patch(repo, [edit])
    except HashLinePatchError as exc:
        assert "start hash mismatch" in str(exc)
    else:
        raise AssertionError("expected HashLinePatchError")


def test_write_text_exact_preserves_lf_for_materialized_diff(tmp_path: Path):
    repo = tmp_path
    path = repo / "sample.py"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("def foo():\n    pass\n")

    edit = HashLinePatchEdit(
        path="sample.py",
        start_line=1,
        start_hash=short_line_hash("def foo():"),
        end_line=2,
        end_hash=short_line_hash("    pass"),
        new='def foo():\n    return "ok"',
    )

    materialized = materialize_hashline_patch(repo, [edit])
    patch_path = repo / "candidate.diff"
    write_text_exact(patch_path, materialized.diff)
    patch_bytes = patch_path.read_bytes()
    assert b"\r\n" not in patch_bytes


def test_materialize_hashline_patch_validates_optional_block_hash(tmp_path: Path):
    repo = tmp_path
    path = repo / "sample.py"
    path.write_text("def foo():\n    pass\n", encoding="utf-8")

    edit = HashLinePatchEdit(
        path="sample.py",
        start_line=1,
        start_hash=short_line_hash("def foo():"),
        end_line=2,
        end_hash=short_line_hash("    pass"),
        block_hash=short_block_hash("def foo():\n    pass"),
        new='def foo():\n    return "ok"',
    )

    materialized = materialize_hashline_patch(repo, [edit])
    assert '+    return "ok"' in materialized.diff


def test_materialize_hashline_patch_rejects_bad_optional_block_hash(tmp_path: Path):
    repo = tmp_path
    path = repo / "sample.py"
    path.write_text("def foo():\n    pass\n", encoding="utf-8")

    edit = HashLinePatchEdit(
        path="sample.py",
        start_line=1,
        start_hash=short_line_hash("def foo():"),
        end_line=2,
        end_hash=short_line_hash("    pass"),
        block_hash="deadbeefcafe",
        new='def foo():\n    return "ok"',
    )

    try:
        materialize_hashline_patch(repo, [edit])
    except HashLinePatchError as exc:
        assert "block hash mismatch" in str(exc)
    else:
        raise AssertionError("expected HashLinePatchError")

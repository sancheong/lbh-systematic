from pathlib import Path

from lbh.core.config import Config
from lbh.patch.diff import modified_paths, validate_diff


def test_modified_paths():
    diff = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-a
+b
"""
    modified, new, deleted = modified_paths(diff)
    assert modified == ["src/a.py"]
    assert new == []
    assert deleted == []


def test_require_read_before_modify(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("a\n", encoding="utf-8")
    diff = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-a
+b
"""
    result = validate_diff(diff, tmp_path, Config({}), read_files={})
    assert not result.ok
    assert "not READ" in result.errors[0]
    result = validate_diff(diff, tmp_path, Config({}), read_files={"src/a.py": {"ranges": [{"start": 1, "end": 1}]}})
    assert result.ok


def test_require_read_before_modify_rejects_unread_ranges(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("a\nb\n", encoding="utf-8")
    diff = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -2 +2 @@
-b
+c
"""
    result = validate_diff(diff, tmp_path, Config({}), read_files={"src/a.py": {"ranges": [{"start": 1, "end": 1}]}})
    assert not result.ok
    assert "unread lines" in result.errors[0]


def test_require_read_before_modify_rejects_insertion_outside_read_range(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("a\nb\nc\n", encoding="utf-8")
    diff = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -2,2 +2,3 @@
 b
+x
 c
"""
    result = validate_diff(diff, tmp_path, Config({}), read_files={"src/a.py": {"ranges": [{"start": 1, "end": 1}]}})
    assert not result.ok
    assert "unread lines" in result.errors[0]
    assert "src/a.py:2-2" in result.errors[0]


def test_require_read_before_modify_accepts_insertion_adjacent_to_read_range(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("a\nb\nc\n", encoding="utf-8")
    diff = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,3 @@
 a
+x
 b
"""
    result = validate_diff(diff, tmp_path, Config({}), read_files={"src/a.py": {"ranges": [{"start": 1, "end": 1}]}})
    assert result.ok

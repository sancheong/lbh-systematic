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
    result = validate_diff(diff, tmp_path, Config({}), read_files={"src/a.py": {}})
    assert result.ok

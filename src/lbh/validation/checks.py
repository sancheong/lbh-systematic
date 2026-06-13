from __future__ import annotations

import ast
import builtins
import compileall
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    kind: str
    status: str
    command: list[str] | None = None
    artifact: str | None = None
    summary: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "command": list(self.command) if self.command is not None else None,
            "artifact": self.artifact,
            "summary": self.summary,
            "warnings": list(self.warnings),
        }


def run_compile_check(sandbox_root: Path, modified_files: list[str], artifact_dir: Path) -> CheckResult:
    python_files = [path for path in modified_files if path.endswith(".py") and (sandbox_root / path).exists()]
    if not python_files:
        return CheckResult(name="compileall", kind="static", status="skipped", summary="no modified Python files")

    command = [sys.executable, "-m", "compileall", "-q", *python_files]
    result = _run(command, sandbox_root)
    artifact = artifact_dir / "compileall.log"
    artifact.write_text(result.stdout, encoding="utf-8")
    return CheckResult(
        name="compileall",
        kind="static",
        status="passed" if result.returncode == 0 else "failed",
        command=command,
        artifact=artifact.name,
        summary="compileall passed" if result.returncode == 0 else _first_line(result.stdout, "compileall failed"),
    )


def run_undefined_name_check(sandbox_root: Path, modified_files: list[str], artifact_dir: Path) -> CheckResult:
    python_files = [path for path in modified_files if path.endswith(".py") and (sandbox_root / path).exists()]
    if not python_files:
        return CheckResult(name="undefined_names", kind="static", status="skipped", summary="no modified Python files")

    issues: list[str] = []
    for rel_path in python_files:
        issues.extend(_undefined_name_issues(sandbox_root / rel_path, rel_path))

    artifact = artifact_dir / "undefined_names.log"
    artifact.write_text("\n".join(issues) + ("\n" if issues else ""), encoding="utf-8")
    return CheckResult(
        name="undefined_names",
        kind="static",
        status="failed" if issues else "passed",
        artifact=artifact.name,
        summary=issues[0] if issues else "no undefined names detected",
    )


def run_targeted_tests(sandbox_root: Path, tests: list[str], artifact_dir: Path) -> CheckResult:
    if not tests:
        return CheckResult(name="pytest", kind="targeted_tests", status="skipped", summary="no targeted tests selected")
    command = [sys.executable, "-m", "pytest", "-q", *tests]
    result = _run(command, sandbox_root)
    artifact = artifact_dir / "targeted_tests.log"
    artifact.write_text(result.stdout, encoding="utf-8")
    return CheckResult(
        name="pytest",
        kind="targeted_tests",
        status="passed" if result.returncode == 0 else "failed",
        command=command,
        artifact=artifact.name,
        summary="targeted tests passed" if result.returncode == 0 else _first_line(result.stdout, "targeted tests failed"),
    )


def run_cli_smoke(sandbox_root: Path, artifact_dir: Path) -> CheckResult:
    commands = [
        [sys.executable, "-m", "lbh.cli", "run", "--help"],
        [sys.executable, "-m", "lbh.cli", "preflight", "--help"],
        [sys.executable, "-m", "lbh.cli", "apply", "--help"],
    ]
    output: list[str] = []
    for command in commands:
        result = _run(command, sandbox_root)
        output.append("$ " + " ".join(command))
        output.append(result.stdout)
        if result.returncode != 0:
            artifact = artifact_dir / "cli_smoke.log"
            artifact.write_text("\n".join(output), encoding="utf-8")
            return CheckResult(
                name="cli_smoke",
                kind="cli_smoke",
                status="failed",
                command=command,
                artifact=artifact.name,
                summary=_first_line(result.stdout, "CLI smoke failed"),
            )
    artifact = artifact_dir / "cli_smoke.log"
    artifact.write_text("\n".join(output), encoding="utf-8")
    return CheckResult(
        name="cli_smoke",
        kind="cli_smoke",
        status="passed",
        command=commands[-1],
        artifact=artifact.name,
        summary="CLI smoke passed",
    )


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    package_src = str(Path(__file__).resolve().parents[2])
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = package_src if not existing else package_src + os.pathsep + existing
    env["GIT_CEILING_DIRECTORIES"] = str(cwd.parent)
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _first_line(text: str, fallback: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean
    return fallback


class _Scope:
    def __init__(self, parent: "_Scope | None" = None):
        self.parent = parent
        self.defined: set[str] = set()

    def has(self, name: str) -> bool:
        if name in self.defined:
            return True
        if self.parent is not None:
            return self.parent.has(name)
        return False


class _UndefinedNameVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str):
        self.rel_path = rel_path
        self.scope = _Scope()
        self.issues: list[str] = []
        self.builtins = set(dir(builtins)) | {"__file__", "__name__", "__package__"}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.defined.add(node.name)
        self._visit_function_like(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.defined.add(node.name)
        self._visit_function_like(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        previous = self.scope
        self.scope = _Scope(previous)
        self._define_args(node.args)
        self.visit(node.body)
        self.scope = previous

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.defined.add(node.name)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword)
        previous = self.scope
        self.scope = _Scope(previous)
        for stmt in node.body:
            self.visit(stmt)
        self.scope = previous

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.scope.defined.add((alias.asname or alias.name.split(".")[0]))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                continue
            self.scope.defined.add(alias.asname or alias.name)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._define_target(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        self._define_target(node.target)
        self.visit(node.annotation)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.target)
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        self._define_target(node.target)
        for stmt in node.body + node.orelse:
            self.visit(stmt)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._define_target(item.optional_vars)
        for stmt in node.body:
            self.visit(stmt)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name:
            self.scope.defined.add(node.name)
        for stmt in node.body:
            self.visit(stmt)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and node.id not in self.builtins and not self.scope.has(node.id):
            self.issues.append(f"{self.rel_path}:{node.lineno}:{node.col_offset + 1}: undefined name {node.id}")
        elif isinstance(node.ctx, (ast.Store, ast.Param)):
            self.scope.defined.add(node.id)

    def _visit_function_like(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults + node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        previous = self.scope
        self.scope = _Scope(previous)
        self._define_args(node.args)
        for stmt in node.body:
            self.visit(stmt)
        self.scope = previous

    def _define_args(self, args: ast.arguments) -> None:
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            self.scope.defined.add(arg.arg)
        if args.vararg:
            self.scope.defined.add(args.vararg.arg)
        if args.kwarg:
            self.scope.defined.add(args.kwarg.arg)

    def _define_target(self, target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self.scope.defined.add(target.id)
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._define_target(item)
            return
        self.visit(target)


def _undefined_name_issues(path: Path, rel_path: str) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)
    except SyntaxError as exc:
        return [f"{rel_path}:{exc.lineno or 0}:{exc.offset or 0}: syntax error: {exc.msg}"]
    visitor = _UndefinedNameVisitor(rel_path)
    visitor.visit(tree)
    return visitor.issues

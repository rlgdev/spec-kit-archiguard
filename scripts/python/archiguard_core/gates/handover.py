"""H - handover 4 -> 5: entry checks for the deterministic test loop and the test-handover manifest."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Sequence

from ..common import ArchiGuardError, files_matching, parse_tasks, read_text, rel_path, sha256_file
from ..verdict import ADVISORY, CheckResult, Finding
from . import a4
from .context import GateContext


# --------------------------------------------------------------------------- #
# Build / test commands per stack                                               #
# --------------------------------------------------------------------------- #


def _gradle(ctx: GateContext) -> str:
    if (ctx.root / "gradlew").is_file() or (ctx.root / "gradlew.bat").is_file():
        return "gradlew.bat" if os.name == "nt" else "./gradlew"
    return "gradle"


def stack_commands(ctx: GateContext, kind: str) -> List[str]:
    """kind = build | test. Explicit config wins; 'auto' derives them from the stack markers."""
    key = "build" if kind == "build" else "command"
    configured = (ctx.cfg["tests"] or {}).get(key, "auto")
    if configured in (None, "", [], "none", False):
        return []
    if configured != "auto":
        return [str(c) for c in (configured if isinstance(configured, list) else [configured])]
    cmds: List[str] = []
    root = ctx.root
    for stack in ctx.stacks:
        if stack == "java":
            if (root / "pom.xml").is_file():
                cmds.append("mvn -B -q -DskipTests package" if kind == "build" else "mvn -B test")
            elif any((root / f).is_file() for f in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")):
                g = _gradle(ctx)
                cmds.append(f"{g} build -x test" if kind == "build" else f"{g} test")
        elif stack == "node" and (root / "package.json").is_file():
            cmds.append("npm run build --if-present" if kind == "build" else "npm test")
        elif stack == "python":
            if kind == "test":
                cmds.append("python -m pytest")
        elif stack == "dotnet":
            cmds.append("dotnet build" if kind == "build" else "dotnet test")
        elif stack == "go":
            cmds.append("go build ./..." if kind == "build" else "go test ./...")
    return cmds


def run_command(ctx: GateContext, command: str, timeout: int) -> Dict[str, Any]:
    try:
        proc = subprocess.run(command, shell=True, cwd=str(ctx.root), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
        tail = "\n".join((proc.stdout + proc.stderr).strip().split("\n")[-20:])
        return {"command": command, "exit_code": proc.returncode, "tail": tail}
    except subprocess.TimeoutExpired:
        return {"command": command, "exit_code": -1, "tail": f"timed out after {timeout}s"}
    except OSError as exc:
        raise ArchiGuardError(f"cannot run '{command}': {exc}")


# --------------------------------------------------------------------------- #
# Entry checks                                                                  #
# --------------------------------------------------------------------------- #


def check_h1(ctx: GateContext, res: CheckResult) -> None:
    tasks = parse_tasks(ctx.require_file("tasks.md"))
    open_tasks = [t for t in tasks if not t.checked]
    for t in open_tasks:
        res.add(Finding(rule="H1", where=f"tasks.md:{t.line}", message=f"open task {t.task_id or ''}: {t.text[:120]}",
                        fix_hint="finish the task (or the Convergence phase) before the test loop"))
    res.data["tasks"] = {"total": len(tasks), "open": len(open_tasks)}


def check_h2(ctx: GateContext, res: CheckResult) -> None:
    a4.check_a4_5(ctx, res)


def check_h3(ctx: GateContext, res: CheckResult) -> None:
    path = ctx.gates_dir / "A4" / "A4.4.json"
    if not path.is_file():
        res.add(Finding(rule="H3", where=rel_path(path, ctx.root),
                        message="no fitness verdict (A4.4) for this feature",
                        fix_hint="run the implement step B gates (archiguard run implement b) first"))
        return
    try:
        verdict = json.loads(read_text(path))
    except ValueError:
        raise ArchiGuardError(f"{rel_path(path, ctx.root)} is not valid JSON")
    status = verdict.get("status")
    res.data["A4.4"] = status
    if status not in ("pass", "waived"):
        res.add(Finding(rule="H3", where=rel_path(path, ctx.root), message=f"the fitness verdict is '{status}'",
                        fix_hint="repair the fitness findings in implement step B"))


def in_scope_for_tests(ctx: GateContext) -> List[str]:
    prefixes = ctx.cfg.option("H4", "prefixes", ["AC", "BR"]) or []
    return a4.in_scope_ids(ctx, prefixes)


def check_h4(ctx: GateContext, res: CheckResult) -> None:
    wanted = in_scope_for_tests(ctx)
    res.data["in_scope"] = [ctx.label(i) for i in wanted]
    if not wanted:
        res.add(Finding(rule="H4", severity=ADVISORY,
                        message="no in-scope ids with the traced prefixes (options.H4.prefixes) - nothing to inventory"))
        return
    globs = a4.test_globs(ctx)
    rx = a4.lenient_id_regex(sorted({i.split("-")[0] for i in wanted}))
    carriers: Dict[str, List[str]] = {i: [] for i in wanted}
    for f in files_matching(ctx.root, globs):
        found = a4.lenient_ids(read_text(ctx.root / f), rx)
        for i in found:
            if i in carriers:
                carriers[i].append(f)
    res.data["tests"] = {ctx.label(i): files for i, files in carriers.items()}
    for i, files in carriers.items():
        if not files:
            label = ctx.label(i)
            res.add(Finding(rule=label, where="tests", message=f"no test carries {label}",
                            fix_hint=f"write a test that verifies {label} and tag it with the id"))


def check_h5(ctx: GateContext, res: CheckResult) -> None:
    cmds = stack_commands(ctx, "build")
    if not cmds:
        res.add(Finding(rule="H5", severity=ADVISORY, message="no build command configured or detected (tests.build)"))
        return
    timeout = int((ctx.cfg["tests"] or {}).get("timeout") or 1800)
    runs = []
    for cmd in cmds:
        result = run_command(ctx, cmd, timeout)
        runs.append(result)
        if result["exit_code"] != 0:
            res.add(Finding(rule="H5", message=f"build failed (exit {result['exit_code']}): {cmd}",
                            fix_hint="make the build green before the test loop", excerpt=result["tail"]))
    res.data["builds"] = runs


def check_h6(ctx: GateContext, res: CheckResult) -> None:
    a4.check_a4_1(ctx, res)


CHECKS = {
    "H1": check_h1,
    "H2": check_h2,
    "H3": check_h3,
    "H4": check_h4,
    "H5": check_h5,
    "H6": check_h6,
}


# --------------------------------------------------------------------------- #
# Manifest                                                                      #
# --------------------------------------------------------------------------- #


def build_manifest(ctx: GateContext, results: Sequence[CheckResult]) -> Dict[str, Any]:
    from .. import __version__

    commit, dirty = ctx.head()
    by_check = {r.check: r for r in results}
    verdicts = {}
    for gate, check in (("A3", "A3.3"), ("A3", "A3.5"), ("A3", "A3.7"), ("A4", "A4.4"), ("A4", "A4.6"), ("A0", "A0.5")):
        path = ctx.gates_dir / gate / f"{check}.json"
        if path.is_file():
            try:
                verdicts[check] = {"file": rel_path(path, ctx.root), "status": json.loads(read_text(path)).get("status")}
            except ValueError:
                verdicts[check] = {"file": rel_path(path, ctx.root), "status": "unreadable"}
    waivers = []
    today = ctx.today()
    for entry in ctx.ledger.latest.values():
        if entry.get("status") == "approved" and entry.get("rules") and ctx.ledger.check_entry(entry["id"], today) is None:
            waivers.append({"id": entry["id"], "rules": entry.get("rules"), "expires": entry.get("expires")})
    tasks = parse_tasks(read_text(ctx.feature_file("tasks.md"))) if ctx.feature_file("tasks.md").is_file() else []
    from ..common import git_branch

    return {
        "tool": "archiguard",
        "version": __version__,
        "feature": ctx.feature,
        "branch": git_branch(ctx.root) or None,
        "commit": commit,
        "dirty": dirty,
        "hashes": {
            "spec.md": sha256_file(ctx.feature_file("spec.md")),
            "plan.md": sha256_file(ctx.feature_file("plan.md")),
        },
        "pins": ctx.pins(),
        "tasks": {"total": len(tasks), "done": sum(1 for t in tasks if t.checked)},
        "requirements_to_tests": (by_check.get("H4").data.get("tests") if by_check.get("H4") else None),
        "stack": ctx.stacks,
        "test_commands": stack_commands(ctx, "test"),
        "build_commands": stack_commands(ctx, "build"),
        "verdicts": verdicts,
        "waivers": waivers,
        "entry_checks": {r.check: r.status for r in results},
    }

"""The deterministic test loop 4 <-> 5: run the test command, read the JUnit reports, trace the ids."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .common import ArchiGuardError, files_matching, glob_match, read_text, walk_files
from .gates import a4
from .gates.context import GateContext
from .gates.handover import in_scope_for_tests, run_command, stack_commands
from .verdict import CheckResult, Finding


def _junit_files(ctx: GateContext, since: Optional[float]) -> List[Path]:
    patterns = (ctx.cfg["tests"] or {}).get("junit") or []
    if isinstance(patterns, str):
        patterns = [patterns]
    # reports live in build output folders, so walk without the default excludes (except VCS / deps)
    found = []
    for rel in walk_files(ctx.root, (".git", "node_modules", ".venv", "venv", "__pycache__", ".specify", ".claude")):
        if glob_match(rel, patterns):
            path = ctx.root / rel
            if since is None or path.stat().st_mtime >= since - 1:
                found.append(path)
    return found


def parse_junit(path: Path) -> List[Dict[str, Any]]:
    try:
        tree = ET.parse(str(path))
    except (ET.ParseError, OSError) as exc:
        raise ArchiGuardError(f"{path}: not a readable JUnit XML report ({exc})")
    cases = []
    for case in tree.getroot().iter("testcase"):
        status = "passed"
        message = ""
        for child in case:
            tag = child.tag.lower()
            if tag in ("failure", "error"):
                status = "failed"
                message = (child.get("message") or child.text or "").strip()[:300]
                break
            if tag == "skipped":
                status = "skipped"
        cases.append({
            "name": case.get("name") or "",
            "classname": case.get("classname") or "",
            "file": case.get("file") or "",
            "status": status,
            "message": message,
        })
    return cases


_DECORATION = re.compile(r"^\s*(?:@|//|#|\*|/\*|\[|<|--)")


class SourceIndex:
    """Ids a test declares next to its definition: tags, annotations, attributes or comments.

    JUnit reports carry only the class and test names. A test tagged `@Tag("AC-001")` or commented
    `// BR-042` above `void createsOneLinePerItem()` is traced through its source file: the lines
    directly above the test's definition (annotations, comments, attributes) and the definition line.
    """

    def __init__(self, ctx: GateContext, rx: "re.Pattern[str]"):
        self.root = ctx.root
        self.rx = rx
        self.by_stem: Dict[str, List[str]] = {}
        for rel in files_matching(ctx.root, a4.test_globs(ctx)):
            self.by_stem.setdefault(Path(rel).stem.lower(), []).append(rel)
        self._text: Dict[str, List[str]] = {}

    def _lines(self, rel: str) -> List[str]:
        if rel not in self._text:
            self._text[rel] = read_text(self.root / rel).split("\n")
        return self._text[rel]

    def ids(self, case: Dict[str, Any]) -> Set[str]:
        name = re.sub(r"\(.*$", "", case["name"]).strip()           # JUnit 5 display names: "method()"
        if not name:
            return set()
        simple = case["classname"].split(".")[-1].split("$")[0].lower()
        files = [case["file"]] if case.get("file") and (self.root / case["file"]).is_file() else self.by_stem.get(simple, [])
        found: Set[str] = set()
        definition = re.compile(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])")
        for rel in files:
            lines = self._lines(rel)
            for idx, line in enumerate(lines):
                if not definition.search(line):
                    continue
                block = [line]
                k = idx - 1
                while k >= 0 and (_DECORATION.match(lines[k]) or not lines[k].strip()) and idx - k <= 12:
                    block.append(lines[k])
                    k -= 1
                found |= a4.lenient_ids("\n".join(block), self.rx)
        return found


def run_tests(ctx: GateContext, res: CheckResult, *, run: bool = True) -> None:
    started: Optional[float] = None
    runs: List[Dict[str, Any]] = []
    if run:
        cmds = stack_commands(ctx, "test")
        if not cmds:
            raise ArchiGuardError("no test command configured or detected (tests.command in archiguard-config.yml)")
        timeout = int((ctx.cfg["tests"] or {}).get("timeout") or 1800)
        started = time.time()
        for cmd in cmds:
            runs.append(run_command(ctx, cmd, timeout))
    res.data["commands"] = runs

    reports = _junit_files(ctx, started)
    cases: List[Dict[str, Any]] = []
    for path in reports:
        cases.extend(parse_junit(path))
    res.data["reports"] = [p.relative_to(ctx.root).as_posix() for p in reports]

    wanted = in_scope_for_tests(ctx)
    prefixes = sorted({i.split("-")[0] for i in wanted}) or ["AC", "BR"]
    rx = a4.lenient_id_regex(prefixes)
    index = SourceIndex(ctx, rx)

    def case_ids(case: Dict[str, Any]) -> Set[str]:
        return a4.lenient_ids(f"{case['classname']} {case['name']} {case['file']}", rx) | index.ids(case)

    failed = [c for c in cases if c["status"] == "failed"]
    for c in failed:
        ids = [ctx.label(i) for i in sorted(case_ids(c))]
        res.add(Finding(rule=", ".join(ids) or "test", where=c["file"] or c["classname"] or None,
                        message=f"failing test {c['classname']}.{c['name']}" + (f" ({', '.join(ids)})" if ids else "")
                        + (f": {c['message']}" if c["message"] else ""),
                        fix_hint="fix the implementation (not the test) unless the test contradicts the specification"))
    for r in runs:
        if r["exit_code"] != 0 and not failed:
            res.add(Finding(rule="test", message=f"test command failed (exit {r['exit_code']}): {r['command']}",
                            fix_hint="make the suite run; a red build or a crash counts as a failing suite",
                            excerpt=r["tail"]))

    passing: Dict[str, List[str]] = {i: [] for i in wanted}
    for c in cases:
        if c["status"] != "passed":
            continue
        for i in case_ids(c):
            if i in passing:
                passing[i].append(f"{c['classname']}.{c['name']}")
    if wanted and not cases:
        raise ArchiGuardError(
            "no JUnit test reports found (tests.junit) - the ids "
            + ", ".join(ctx.label(i) for i in wanted[:8]) + (" ..." if len(wanted) > 8 else "") + " cannot be traced"
        )
    for i, tests in passing.items():
        if not tests:
            label = ctx.label(i)
            res.add(Finding(rule=label, message=f"no passing test carries {label}",
                            fix_hint=f"make a test that verifies {label} (tagged with the id) pass"))
    res.data["trace"] = {ctx.label(i): tests for i, tests in passing.items()}
    res.data["summary"] = {
        "cases": len(cases),
        "failed": len(failed),
        "skipped": sum(1 for c in cases if c["status"] == "skipped"),
        "traced": sum(1 for v in passing.values() if v),
        "in_scope": len(wanted),
    }

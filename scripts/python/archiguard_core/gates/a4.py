"""A4 - fitness functions (and the entry pin check)."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set

from .. import standards
from ..common import (
    ArchiGuardError,
    git,
    glob_match,
    id_regex,
    ids_in,
    parse_tasks,
    read_text,
    spec_ids,
    write_text,
)
from ..verdict import ADVISORY, CheckResult, Finding
from .context import GateContext

TEST_GLOBS: Dict[str, List[str]] = {
    "java": ["**/src/test/**/*.{java,kt,groovy,scala}", "**/*Test.java", "**/*Tests.java", "**/*IT.java"],
    "node": ["**/*.{test,spec}.{js,jsx,ts,tsx,mjs,cjs}", "**/__tests__/**/*.{js,jsx,ts,tsx}",
             "**/test/**/*.{js,ts}", "**/tests/**/*.{js,ts}"],
    "python": ["**/test_*.py", "**/*_test.py", "**/tests/**/*.py"],
    "dotnet": ["**/*Tests.cs", "**/*Test.cs", "**/*.Tests/**/*.cs"],
    "go": ["**/*_test.go"],
    "cobol": [],
}
GHERKIN_GLOBS = ["**/*.feature"]


def test_globs(ctx: GateContext) -> List[str]:
    configured = (ctx.cfg["tests"] or {}).get("globs", "auto")
    if configured != "auto":
        return [str(g) for g in (configured if isinstance(configured, list) else [configured])]
    out: List[str] = list(GHERKIN_GLOBS)
    for stack in ctx.stacks:
        out.extend(TEST_GLOBS.get(stack, []))
    if not ctx.stacks:
        for globs in TEST_GLOBS.values():
            out.extend(globs)
    return sorted(set(out))


def lenient_id_regex(prefixes: Sequence[str]) -> "re.Pattern[str]":
    """IDs as they appear in test code: BR-042, BR_042, BR042 (method names cannot hold a hyphen)."""
    alts = "|".join(re.escape(p) for p in sorted(set(prefixes), key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])({alts})[-_]?0*(\d+)(?![0-9])")


def lenient_ids(text: str, rx: "re.Pattern[str]") -> Set[str]:
    return {f"{m.group(1)}-{int(m.group(2))}" for m in rx.finditer(text)}


def in_scope_ids(ctx: GateContext, prefixes: Sequence[str]) -> List[str]:
    """The feature's scope: the handover record's in-scope ids when it lists them, else the ids spec.md defines."""
    h = ctx.handover
    ids = list(h.scope) if h is not None and h.scope else list(spec_ids(ctx.spec_text, prefixes))
    return [i for i in ids if any(i.startswith(p + "-") for p in prefixes)]


def known_ids(ctx: GateContext, prefixes: Sequence[str]) -> List[str]:
    ids = list(spec_ids(ctx.spec_text, prefixes))
    if ctx.handover is not None:
        for i in ctx.handover.scope:
            if i not in ids:
                ids.append(i)
    return ids


# --------------------------------------------------------------------------- #
# A4.1 entry pin check (also H6)                                                #
# --------------------------------------------------------------------------- #


def check_a4_1(ctx: GateContext, res: CheckResult) -> None:
    so = ctx.signoff
    if so is None:
        res.add(Finding(rule=res.check, where=f"{ctx.feature}/gates/signoff.json",
                        message="no design authority sign-off is recorded for this feature",
                        fix_hint="the design authority signs the plan: archiguard signoff --by <name>"))
        return
    from ..runner import artefact_hashes

    reopen = "a design change re-opens Design: archiguard reopen, re-run the plan and tasks gates, sign again"
    hashes = {k: v for k, v in (so.get("hashes") or {}).items() if k != "tasks.md" and not k.startswith("gates/")}
    current_all = artefact_hashes(ctx.feature_dir, ctx.cfg)
    signed = f"{so.get('at', '?')} by {so.get('by', '?')}"
    for name in sorted(set(hashes) | {k for k in current_all if k.startswith("contracts/")}):
        recorded, current = hashes.get(name), current_all.get(name)
        if current == recorded:
            continue
        change = "was added" if recorded is None else ("was removed" if current is None else "changed")
        res.add(Finding(rule=res.check, where=f"{ctx.feature}/{name}",
                        message=f"{name} {change} since the design authority sign-off ({signed})",
                        fix_hint=reopen))
    h = ctx.handover
    if h is not None and h.spec_sha256:
        current = ctx.spec_hash()
        if current != h.spec_sha256:
            res.add(Finding(rule=res.check, where=f"{ctx.feature}/spec.md",
                            message="spec.md differs from the released specification recorded by the handover",
                            fix_hint="specification changes come from the BA as a new released version"))
    pins = so.get("pins") or {}
    if pins.get("lock"):
        lock = ctx.lock
        rb = lock.get("rulebook") or {}
        now_rb = f"{rb.get('name')}@{rb.get('tag')}"
        if pins.get("rulebook") and pins["rulebook"] != now_rb:
            res.add(Finding(rule=res.check, message=f"the rulebook moved from {pins['rulebook']} to {now_rb} after the sign-off",
                            fix_hint="re-open Design (archiguard reopen), re-run the gates on the new policy and sign again"))
        elif standards.lock_hash(lock) != pins["lock"]:
            res.add(Finding(rule=res.check, message="standards.lock.yml changed after the sign-off",
                            fix_hint="re-open Design (archiguard reopen), re-run the gates on the new policy and sign again"))
    if pins.get("domain_map"):
        dm = ctx.domain_map
        now = dm.version if dm else None
        if now != pins["domain_map"]:
            res.add(Finding(rule=res.check, message=f"the domain map moved from {pins['domain_map']} to {now} after the sign-off",
                            fix_hint="re-open Design (archiguard reopen), re-run the gates on the new policy and sign again"))


# --------------------------------------------------------------------------- #
# A4.2 edit rules over the files changed on the branch                          #
# --------------------------------------------------------------------------- #


def base_ref(ctx: GateContext) -> Optional[str]:
    base = str((ctx.cfg["git"] or {}).get("base") or "main")
    for candidate in (base, f"origin/{base}"):
        code, _ = git(ctx.root, "rev-parse", "--verify", "--quiet", candidate + "^{commit}")
        if code == 0:
            return candidate
    return None


def changed_files(ctx: GateContext) -> Optional[List[str]]:
    """Files changed on the branch (vs the base) plus uncommitted ones; None without git."""
    code, _ = git(ctx.root, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        return None
    files: Set[str] = set()
    base = base_ref(ctx)
    if base:
        code, out = git(ctx.root, "diff", "--name-only", f"{base}...HEAD")
        if code == 0:
            files.update(l.strip() for l in out.split("\n") if l.strip())
    code, out = git(ctx.root, "status", "--porcelain", "--untracked-files=all")
    if code == 0:
        for line in out.split("\n"):
            if len(line) > 3:
                path = line[3:].strip()
                if " -> " in path:
                    path = path.split(" -> ", 1)[1]
                files.add(path.strip('"'))
    return sorted(f for f in files if (ctx.root / f).is_file())


def check_a4_2(ctx: GateContext, res: CheckResult) -> None:
    rules, _ = ctx.applicable
    files = changed_files(ctx)
    if files is None:
        res.info.append("A4.2: no git repository - checking every file")
    evaluator = ctx.evaluator
    for rule in rules:
        checks = [c for c in standards.checks_for(rule, ("edit",)) if c.get("kind") != "readonly"]
        findings: List[Finding] = []
        for chk in checks:
            findings.extend(evaluator.run(rule, chk, only_files=files))
        if findings:
            waiver = ctx.waiver(rule["id"])
            if waiver:
                res.waive(rule["id"], waiver["id"], str(waiver.get("expires")), reason="ledger waiver")
                continue
            for f in findings:
                res.add(f)


# --------------------------------------------------------------------------- #
# A4.4 fitness runner                                                           #
# --------------------------------------------------------------------------- #


def check_a4_4(ctx: GateContext, res: CheckResult) -> None:
    provider = (ctx.cfg["fitness"] or {}).get("provider", "graph-free")
    if provider != "graph-free":
        raise ArchiGuardError(
            "fitness.provider 'graph' (Graphify behind the seam) is not available in this version - use 'graph-free', "
            "or declare the graph queries as 'command' checks in the rulebook"
        )
    rules, _ = ctx.applicable
    evaluator = ctx.evaluator
    outcome: Dict[str, str] = {}
    for rule in rules:
        rid = rule["id"]
        checks = standards.checks_for(rule, ("code",))
        if not checks:
            if "code" in (rule.get("targets") or []):
                res.skip(rid, "no fitness function declared for the code - agent judgement")
            continue
        findings: List[Finding] = []
        for chk in checks:
            findings.extend(evaluator.run(rule, chk))
        blocking = [f for f in findings if f.severity != ADVISORY]
        if findings:
            waiver = ctx.waiver(rid)
            if waiver:
                res.waive(rid, waiver["id"], str(waiver.get("expires")), reason="ledger waiver")
                outcome[rid] = "waived"
                continue
            for f in findings:
                res.add(f)
        outcome[rid] = "fail" if blocking else "pass"
    res.data["rules"] = outcome
    if ctx.write and outcome:
        _tick_fitness(ctx, outcome)


def _tick_fitness(ctx: GateContext, outcome: Dict[str, str]) -> None:
    path = ctx.feature_file("tasks.md")
    if not path.is_file():
        return
    marker = ctx.cfg.option("A3.5", "fitness_marker", "[FITNESS]")
    rx = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")
    lines = read_text(path).split("\n")
    changed = False
    for i, line in enumerate(lines):
        if marker not in line:
            continue
        m = re.match(r"^(\s*[-*]\s+\[)( |x|X)(\].*)$", line)
        if not m:
            continue
        rids = [r for r in rx.findall(line) if r in outcome]
        if not rids:
            continue
        done = all(outcome[r] in ("pass", "waived") for r in rids)
        want = "x" if done else " "
        if (m.group(2) in "xX") != done:
            lines[i] = m.group(1) + want + m.group(3)
            changed = True
    if changed:
        write_text(path, "\n".join(lines))


# --------------------------------------------------------------------------- #
# A4.5 converge (also H2)                                                       #
# --------------------------------------------------------------------------- #


def check_a4_5(ctx: GateContext, res: CheckResult) -> None:
    text = ctx.require_file("tasks.md")
    phase_rx = re.compile(ctx.cfg.option("A4.5", "phase_pattern", r"(?i)\bconvergence\b"))
    open_tasks = [t for t in parse_tasks(text) if not t.checked and phase_rx.search(t.phase)]
    for t in open_tasks:
        res.add(Finding(rule=res.check, where=f"tasks.md:{t.line}",
                        message=f"open convergence task {t.task_id or ''}: {t.text[:120]}",
                        fix_hint="implement the Convergence phase tasks, then run /speckit.converge again"))
    res.data["open"] = len(open_tasks)


# --------------------------------------------------------------------------- #
# A4.6 traceability                                                             #
# --------------------------------------------------------------------------- #


def check_a4_6(ctx: GateContext, res: CheckResult) -> None:
    prefixes = ctx.cfg.option("A4.6", "id_prefixes", None) or ["UC", "SC", "AC", "BR", "D", "FR", "NFR"]
    known = set(known_ids(ctx, prefixes))
    rx = id_regex(prefixes, stories=True)
    task_rx = re.compile(r"\bT\d{3,}\b")
    code, _ = git(ctx.root, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        raise ArchiGuardError("A4.6 needs a git repository (commits carry the task and requirement ids)")
    base = base_ref(ctx)
    if base is None:
        raise ArchiGuardError(
            f"A4.6: base branch '{(ctx.cfg['git'] or {}).get('base')}' not found - set git.base or fetch it"
        )
    if ctx.cfg.option("A4.6", "commits", True):
        code, out = git(ctx.root, "log", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e", f"{base}..HEAD")
        if code != 0:
            raise ArchiGuardError(f"A4.6: git log failed: {out.strip()}")
        for record in out.split("\x1e"):
            record = record.strip()
            if not record:
                continue
            sha, _, rest = record.partition("\x1f")
            subject, _, body = rest.partition("\x1f")
            message = f"{subject}\n{body}"
            code, names = git(ctx.root, "show", "--name-only", "--format=", sha.strip())
            touched = [n.strip() for n in names.split("\n") if n.strip()] if code == 0 else []
            if touched and all(n.startswith(("specs/", ".specify/")) for n in touched):
                continue  # design, evidence and policy commits; traceability is about the code
            ids = [i for i in ids_in(message, rx) if not known or i in known]
            has_task = bool(task_rx.search(message))
            if not (has_task and ids):
                missing = " and ".join(x for x, ok in (("task (T###)", has_task), ("requirement id", bool(ids))) if not ok)
                res.add(Finding(rule="A4.6", where=f"commit {sha[:10]}",
                                message=f"commit '{subject[:80]}' names no {missing}",
                                fix_hint="reword the commit message to name its task and the requirement ids it implements"))
    if ctx.cfg.option("A4.6", "tests", True):
        globs = test_globs(ctx)
        lenient = lenient_id_regex(prefixes)
        files = changed_files(ctx) or []
        for f in files:
            if not glob_match(f, globs):
                continue
            text = read_text(ctx.root / f)
            found = lenient_ids(text, lenient) | set(ids_in(text, rx))
            if not (found & known if known else found):
                res.add(Finding(rule="A4.6", where=f,
                                message=f"test file {f} carries no requirement id it verifies",
                                fix_hint="tag the tests with the ids they verify (name, annotation, Gherkin tag or a '// BA: BR-042' comment)"))


CHECKS = {
    "A4.1": check_a4_1,
    "A4.2": check_a4_2,
    "A4.4": check_a4_4,
    "A4.5": check_a4_5,
    "A4.6": check_a4_6,
}

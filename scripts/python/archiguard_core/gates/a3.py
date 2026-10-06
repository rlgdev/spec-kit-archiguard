"""A3 - plan conformance."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .. import standards
from ..common import (
    ArchiGuardError,
    column_index,
    find_section,
    id_regex,
    ids_in,
    is_placeholder,
    parse_tasks,
    read_text,
    rel_path,
    spec_ids,
    strip_html_comments,
    tables_in,
    write_json,
)
from ..ledger import cited_ids
from ..verdict import ADVISORY, BLOCKING, CheckResult, Finding
from .context import GateContext

PLAN_TARGETS = ("plan", "contract")
STATUS_SATISFIED = "satisfied"
STATUS_NA = "not applicable"
STATUS_DEVIATION = "deviation"
_STATUS_WORDS = {
    STATUS_SATISFIED: ("satisfied", "compliant", "met", "yes", "ok", "pass", "conforms", "✅", "✓"),
    STATUS_NA: ("not applicable", "n/a", "na", "not-applicable", "none", "➖"),
    STATUS_DEVIATION: ("deviation", "deviates", "waived", "waiver", "exception", "⚠️", "⚠"),
}
LEDGER_ID_PATTERN = r"\b(?:ADR|CLDD|SECD|DATD|WVR|WAIVER)-\d+\b"
RULE_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")


def _severity(rule: Dict[str, Any]) -> str:
    return BLOCKING if rule.get("level") == "must" else ADVISORY


def normalise_status(raw: str) -> Optional[str]:
    low = raw.strip().lower()
    for status, words in _STATUS_WORDS.items():
        for w in words:
            if low == w or low.startswith(w + " ") or low.startswith(w + " ("):
                return status
    return None


def skill_location(ctx: GateContext, rule: Dict[str, Any]) -> Optional[str]:
    if not rule.get("skill_path"):
        return None
    base = str(ctx.cfg["standards"].get("path") or "").rstrip("/")
    return f"{base}/{rule['skill_path']}" if base else rule["skill_path"]


def conformance_row(rule: Dict[str, Any]) -> str:
    return f"| {rule['id']} | {rule.get('title') or ''} | satisfied | <where the plan meets it> | |"


# --------------------------------------------------------------------------- #
# A3.1 context loader                                                           #
# --------------------------------------------------------------------------- #


def check_a3_1(ctx: GateContext, res: CheckResult) -> None:
    lock = ctx.lock
    rules, filtered = ctx.applicable
    rb = lock.get("rulebook") or {}
    payload = {
        "rulebook": f"{rb.get('name')}@{rb.get('tag')}",
        "lock": standards.lock_hash(lock),
        "stacks": ctx.stacks,
        "home_context": ctx.home_context,
        "rules": [
            {
                "id": r["id"], "title": r.get("title"), "level": r.get("level"), "targets": r.get("targets"),
                "check": r.get("check"), "skill": r.get("skill"), "skill_path": skill_location(ctx, r),
                "text": r.get("text"),
            }
            for r in rules
        ],
        "filtered_out": filtered,
    }
    if ctx.write and ctx.feature_dir is not None:
        write_json(ctx.gates_dir / "applicable-rules.json", payload)
    res.data["applicable"] = len(rules)
    res.data["filtered_out"] = len(filtered)

    info = [
        f"ARCHITECTURE CONTRACT - rulebook {payload['rulebook']} | stacks: {', '.join(ctx.stacks) or 'none detected'} "
        f"| home context: {ctx.home_context or 'unknown'}",
        "Read the SKILL.md of every rule below before you design; the plan and the code are checked against them.",
    ]
    for r in rules:
        loc = skill_location(ctx, r) or "-"
        info.append(f"  {r['id']:<10} [{r.get('level')}] {r.get('title')}  ({', '.join(r.get('targets') or [])}; "
                    f"{'declared check' if r.get('check') == 'declared' else 'agent judgement'})  {loc}")
    plan_rules = [r for r in rules if set(r.get("targets") or []) & set(PLAN_TARGETS)]
    section = ctx.cfg.option("A3.3", "section", "Architecture Conformance")
    reasons = lock.get("not_applicable_reasons") or standards.DEFAULT_NA_REASONS
    if plan_rules:
        info += [
            "",
            f"plan.md must contain '## {section}' with exactly one row per rule that targets the plan or a contract:",
            "| Rule | Title | Status | Plan reference | ADR / reason |",
            "|------|-------|--------|----------------|--------------|",
        ]
        info += [conformance_row(r) for r in plan_rules]
        info.append(
            "Status: satisfied (say where the plan meets it) · not applicable (reason from: "
            + ", ".join(reasons) + ") · deviation (ADR id from the decision ledger, approved and unexpired)."
        )
    code_rules = [r for r in rules if any(c.get("target") == "code" for c in r.get("checks") or [])]
    if code_rules:
        info.append("")
        info.append("tasks.md needs one fitness-test task per rule with a code check, e.g. "
                    "'- [ ] T0xx [FITNESS] <what is verified> - " + code_rules[0]["id"] + "':")
        info.append("  " + ", ".join(r["id"] for r in code_rules))
    res.info = info


# --------------------------------------------------------------------------- #
# A3.3 check-plan                                                               #
# --------------------------------------------------------------------------- #


def _conformance_rows(plan: str, section_title: str) -> Tuple[Optional[Any], Dict[str, List[Tuple[int, str, str, str]]], List[Tuple[int, str]]]:
    """(section, rows by rule id -> [(line, status, reference, reason)], unparsable rows)."""
    sec = find_section(plan, re.escape(section_title))
    rows: Dict[str, List[Tuple[int, str, str, str]]] = {}
    bad: List[Tuple[int, str]] = []
    if sec is None:
        return None, rows, bad
    for table in tables_in(sec.lines, sec.start + 1):
        c_rule = column_index(table.header, "rule", "id")
        c_status = column_index(table.header, "status")
        c_ref = column_index(table.header, "reference", "where", "plan ref", "evidence")
        c_reason = column_index(table.header, "adr", "reason", "justification", "deviation")
        if c_rule is None or c_status is None:
            bad.append((table.line, "the table needs 'Rule' and 'Status' columns"))
            continue
        for line, cells in table.rows:
            def cell(i):
                return cells[i].strip() if i is not None and i < len(cells) else ""
            ids = RULE_TOKEN.findall(cell(c_rule))
            if not ids:
                if any(c.strip() for c in cells):
                    bad.append((line, f"row without a rule id: {' | '.join(cells)}"))
                continue
            for rid in ids:
                rows.setdefault(rid, []).append((line, cell(c_status), cell(c_ref), cell(c_reason)))
    return sec, rows, bad


def check_a3_3(ctx: GateContext, res: CheckResult) -> None:
    lock = ctx.lock
    rules, filtered = ctx.applicable
    plan_rules = [r for r in rules if set(r.get("targets") or []) & set(PLAN_TARGETS)]
    all_ids = {r["id"] for r in lock.get("rules") or []}
    filtered_ids = {f["rule"] for f in filtered}
    applicable_ids = {r["id"] for r in rules}
    section_title = ctx.cfg.option("A3.3", "section", "Architecture Conformance")
    reasons = [r.lower() for r in (lock.get("not_applicable_reasons") or standards.DEFAULT_NA_REASONS)]
    plan = strip_html_comments(ctx.require_file("plan.md"))
    sec, rows, bad = _conformance_rows(plan, section_title)
    res.data["rules"] = len(plan_rules)

    if sec is None:
        if plan_rules:
            res.add(Finding(
                rule="A3.3", where="plan.md",
                message=f"plan.md has no '## {section_title}' section ({len(plan_rules)} applicable rule(s) target the plan)",
                fix_hint="add the section with one row per rule:\n" + "\n".join(
                    ["| Rule | Title | Status | Plan reference | ADR / reason |", "|------|-------|--------|----------------|--------------|"]
                    + [conformance_row(r) for r in plan_rules]),
            ))
        return
    for line, msg in bad:
        res.add(Finding(rule="A3.3", where=f"plan.md:{line}", message=msg))

    evaluator = ctx.evaluator
    for rule in plan_rules:
        rid = rule["id"]
        sev = _severity(rule)
        entries = rows.get(rid) or []
        excerpt = rule.get("text")
        if not entries:
            res.add(Finding(rule=rid, severity=sev, where=f"plan.md:{sec.start}",
                            message=f"{rid} {rule.get('title') or ''} is missing from '{section_title}'",
                            fix_hint=f"add: {conformance_row(rule)}  (read {skill_location(ctx, rule) or 'the rule'} first)",
                            excerpt=excerpt))
            continue
        statuses = {normalise_status(e[1]) for e in entries}
        line, raw_status, ref, reason = entries[0]
        if len(statuses) > 1:
            res.add(Finding(rule=rid, severity=sev, where=f"plan.md:{line}",
                            message=f"{rid} has conflicting rows ({', '.join(e[1] for e in entries)})",
                            fix_hint="keep one row per rule"))
            continue
        status = statuses.pop()
        if status is None:
            res.add(Finding(rule=rid, severity=sev, where=f"plan.md:{line}",
                            message=f"{rid}: unknown status '{raw_status}'",
                            fix_hint="use satisfied · not applicable · deviation"))
            continue
        if status == STATUS_NA:
            if not reason or not any(r in reason.lower() for r in reasons):
                res.add(Finding(rule=rid, severity=sev, where=f"plan.md:{line}",
                                message=f"{rid} is marked not applicable without an allowed reason ('{reason or ''}')",
                                fix_hint=f"allowed reasons: {', '.join(reasons)} - otherwise plan it or record a deviation"))
            else:
                res.data.setdefault("not_applicable", []).append({"rule": rid, "reason": reason})
            continue
        if status == STATUS_DEVIATION:
            cited = re.findall(LEDGER_ID_PATTERN, f"{reason} {ref}")
            if not cited:
                res.add(Finding(rule=rid, severity=sev, where=f"plan.md:{line}",
                                message=f"{rid} is a deviation without an ADR id",
                                fix_hint="record the deviation in the decision ledger (approved, with owner and expiry) and cite its id"))
                continue
            problem = ctx.ledger.check_entry(cited[0], ctx.today(), rid)
            if problem:
                res.add(Finding(rule=rid, severity=sev, where=f"plan.md:{line}",
                                message=f"{rid} deviation: {problem}",
                                fix_hint="the waiver approver must approve the ADR in the ledger before the plan can cite it"))
                continue
            entry = ctx.ledger.get(cited[0]) or {}
            res.waive(rid, cited[0], str(entry.get("expires")), reason="deviation recorded in plan.md")
            continue
        # satisfied
        if is_placeholder(ref):
            res.add(Finding(rule=rid, severity=sev, where=f"plan.md:{line}",
                            message=f"{rid} is satisfied without a plan reference",
                            fix_hint="say where the plan meets the rule (section, contract, entity, decision)"))
        checks = standards.checks_for(rule, PLAN_TARGETS)
        if not checks:
            res.skip(rid, "no check declared for the plan - agent judgement, reviewed at sign-off")
            continue
        findings: List[Finding] = []
        for chk in checks:
            findings.extend(evaluator.run(rule, chk))
        if findings:
            waiver = ctx.waiver(rid)
            if waiver:
                res.waive(rid, waiver["id"], str(waiver.get("expires")), reason="ledger waiver")
                continue
            for f in findings:
                res.add(f)

    for rid, entries in sorted(rows.items()):
        if rid in {r["id"] for r in plan_rules}:
            continue
        line = entries[0][0]
        if rid in applicable_ids:
            res.add(Finding(rule=rid, severity=ADVISORY, where=f"plan.md:{line}",
                            message=f"{rid} does not target the plan or a contract; its row is not needed"))
        elif rid in filtered_ids:
            res.add(Finding(rule=rid, severity=ADVISORY, where=f"plan.md:{line}",
                            message=f"{rid} does not apply to this feature ({next(f['reason'] for f in filtered if f['rule'] == rid)})"))
        elif rid in all_ids:
            res.add(Finding(rule=rid, severity=ADVISORY, where=f"plan.md:{line}", message=f"{rid} is not applicable here"))
        else:
            res.add(Finding(rule=rid, where=f"plan.md:{line}",
                            message=f"{rid} is not a rule of the pinned rulebook ({(lock.get('rulebook') or {}).get('tag')})",
                            fix_hint="remove the row or correct the rule id"))


# --------------------------------------------------------------------------- #
# A3.4 constitution check                                                       #
# --------------------------------------------------------------------------- #


def check_a3_4(ctx: GateContext, res: CheckResult) -> None:
    plan = strip_html_comments(ctx.require_file("plan.md"))
    title = ctx.cfg.option("A3.4", "section", "Constitution Check")
    sec = find_section(plan, re.escape(title))
    if sec is None:
        res.add(Finding(rule="A3.4", where="plan.md", message=f"plan.md has no '## {title}' section",
                        fix_hint="fill the Constitution Check from .specify/memory/constitution.md"))
        return
    body_lines = [(sec.start + 1 + i, l) for i, l in enumerate(sec.lines)]
    meaningful = [(n, l) for n, l in body_lines if l.strip() and not re.match(r"^\s*\*GATE:.*\*\s*$", l)]
    if not meaningful:
        res.add(Finding(rule="A3.4", where=f"plan.md:{sec.start}", message="the Constitution Check is empty"))
        return
    for n, line in meaningful:
        if "[Gates determined based on constitution file]" in line:
            res.add(Finding(rule="A3.4", where=f"plan.md:{n}", message="the Constitution Check still holds the template placeholder"))
        elif re.search(r"NEEDS CLARIFICATION", line):
            res.add(Finding(rule="A3.4", where=f"plan.md:{n}", message="unresolved NEEDS CLARIFICATION in the Constitution Check"))
        elif re.search(r"\bERROR\b|\bFAIL(ED)?\b|❌", line) and not re.search(r"justif", line, re.I):
            res.add(Finding(rule="A3.4", where=f"plan.md:{n}", message=f"a constitution gate fails without justification: {line.strip()[:120]}",
                            fix_hint="fix the design, or justify the violation in Complexity Tracking"))
        elif re.match(r"^\s*[-*]\s+\[ \]", line):
            res.add(Finding(rule="A3.4", where=f"plan.md:{n}", message=f"unchecked constitution gate: {line.strip()[:120]}"))
    article = ctx.cfg.option("A3.4", "article")
    if article and not any(article.lower() in l.lower() for _, l in meaningful):
        res.add(Finding(rule="A3.4", where=f"plan.md:{sec.start}",
                        message=f"the Constitution Check does not cover the corporate article '{article}'",
                        fix_hint=f"evaluate the plan against '{article}' in .specify/memory/constitution.md"))


# --------------------------------------------------------------------------- #
# A3.5 task guard                                                               #
# --------------------------------------------------------------------------- #

_STORY_PHASE = re.compile(r"(?i)\buser\s+story\b|\bUS\s*-?\d+\b|\bstory\b|\bSC-\d+\b|\bUC-\d+\b")
_STORY_LABEL = re.compile(r"\[(?:US\s*-?\d+|[A-Z]{1,4}-\d+)\]")


def check_a3_5(ctx: GateContext, res: CheckResult) -> None:
    tasks_text = ctx.require_file("tasks.md")
    tasks = parse_tasks(tasks_text)
    if not tasks:
        res.add(Finding(rule="A3.5", where="tasks.md", message="tasks.md has no tasks ('- [ ] T001 ...')"))
        return
    prefixes = ctx.cfg.option("A3.5", "id_prefixes", None) or ["UC", "SC", "AC", "BR", "D", "FR", "NFR"]
    rx = id_regex(prefixes, stories=True)
    known = set(spec_ids(ctx.spec_text, prefixes))
    if ctx.handover is not None:
        known |= set(ctx.handover.scope)
    marker = ctx.cfg.option("A3.5", "carries_marker", "Carries:")
    require_ids = ctx.cfg.option("A3.5", "require_ids", "story")
    require_marker = bool(ctx.cfg.option("A3.5", "require_marker", False))

    # 1. every (story) task carries requirement ids
    if require_ids not in ("off", False, None):
        for t in tasks:
            in_story = bool(_STORY_PHASE.search(t.phase)) or bool(_STORY_LABEL.search(t.text))
            if require_ids == "story" and not in_story:
                continue
            carried = [i for i in ids_in(t.text, rx) if not known or i in known]
            if require_marker and marker not in t.text:
                res.add(Finding(rule="A3.5", where=f"tasks.md:{t.line}",
                                message=f"{t.task_id or 'task'} has no '{marker}' clause",
                                fix_hint=f"end the task with '{marker} <requirement ids>'"))
            elif not carried:
                res.add(Finding(rule="A3.5", where=f"tasks.md:{t.line}",
                                message=f"{t.task_id or 'task'} carries no requirement id: {t.text[:100]}",
                                fix_hint=f"name the requirement ids the task implements ('{marker} BR-042, AC-017' or a [USn] label)"))

    # 2. test tasks before implementation tasks, for every acceptance criterion
    test_prefixes = ctx.cfg.option("A3.5", "test_first_prefixes", ["AC"]) or []
    test_rx = re.compile(ctx.cfg.option("A3.5", "test_task_pattern", r"(?i)\b(tests?|spec|scenario|acceptance|verify)\b"))
    from .a4 import in_scope_ids

    targets = sorted(in_scope_ids(ctx, test_prefixes))
    for item in targets:
        carrying = [t for t in tasks if item in ids_in(t.text, rx)]
        tests = [t for t in carrying if test_rx.search(t.text)]
        impl = [t for t in carrying if not test_rx.search(t.text)]
        label = ctx.label(item)
        if not tests:
            res.add(Finding(rule="A3.5", where="tasks.md",
                            message=f"{label} has no test task",
                            fix_hint=f"add a test task for {label} before its implementation tasks"))
        elif impl and min(t.line for t in tests) > min(t.line for t in impl):
            res.add(Finding(rule="A3.5", where=f"tasks.md:{min(t.line for t in impl)}",
                            message=f"{label}: the first test task comes after an implementation task (tests first)",
                            fix_hint="move the test task for this criterion before its implementation tasks"))

    # 3. rules with a tasks target, and fitness-test tasks for rules with code checks
    try:
        rules, _ = ctx.applicable
    except ArchiGuardError as exc:
        if ctx.cfg.option("A3.5", "rules", True):
            raise
        rules = []
        res.info.append(f"rules not checked: {exc}")
    evaluator = ctx.evaluator
    fitness_marker = ctx.cfg.option("A3.5", "fitness_marker", "[FITNESS]")
    for rule in rules:
        rid = rule["id"]
        findings: List[Finding] = []
        for chk in standards.checks_for(rule, ("tasks",)):
            findings.extend(evaluator.run(rule, chk))
        if any(c.get("target") == "code" for c in rule.get("checks") or []) and ctx.cfg.option("A3.5", "fitness_tasks", True):
            if not any(fitness_marker in t.text and re.search(rf"\b{re.escape(rid)}\b", t.text) for t in tasks):
                findings.append(Finding(rule=rid, severity=_severity(rule), where="tasks.md",
                                        message=f"no fitness-test task for {rid} {rule.get('title') or ''}",
                                        fix_hint=f"add '- [ ] T0xx {fitness_marker} <what is verified> - {rid}'"))
        if findings:
            waiver = ctx.waiver(rid)
            if waiver:
                res.waive(rid, waiver["id"], str(waiver.get("expires")), reason="ledger waiver")
                continue
            for f in findings:
                res.add(f)


# --------------------------------------------------------------------------- #
# A3.6 analyze                                                                  #
# --------------------------------------------------------------------------- #


def check_a3_6(ctx: GateContext, res: CheckResult) -> None:
    name = ctx.cfg.option("A3.6", "report", "gates/analyze-report.md")
    path = ctx.feature_file(name)
    if not path.is_file():
        raise ArchiGuardError(
            f"{rel_path(path, ctx.root)} not found - run /speckit.analyze (the archiGuard preset saves its report there)"
        )
    text = strip_html_comments(read_text(path))
    critical: List[Tuple[int, str]] = []
    for table in tables_in(text.split("\n"), 1):
        c_sev = column_index(table.header, "severity")
        if c_sev is None:
            continue
        c_sum = column_index(table.header, "summary", "finding")
        for line, cells in table.rows:
            if c_sev < len(cells) and cells[c_sev].strip().upper() == "CRITICAL":
                summary = cells[c_sum] if c_sum is not None and c_sum < len(cells) else " | ".join(cells)
                critical.append((line, summary))
    metric = re.search(r"Critical Issues Count\D{0,10}(\d+)", text, re.I)
    count = max(len(critical), int(metric.group(1)) if metric else 0)
    res.data["critical"] = count
    for line, summary in critical:
        res.add(Finding(rule="A3.6", where=f"{name}:{line}", message=f"CRITICAL analyze finding: {summary[:160]}",
                        fix_hint="fix spec / plan / tasks, then re-run /speckit.analyze"))
    if count > len(critical):
        res.add(Finding(rule="A3.6", where=name, message=f"{count} CRITICAL issue(s) reported by /speckit.analyze"))


# --------------------------------------------------------------------------- #
# A3.7 ledger check                                                             #
# --------------------------------------------------------------------------- #


def check_a3_7(ctx: GateContext, res: CheckResult) -> None:
    ledger = ctx.ledger
    for problem in ledger.problems:
        res.add(Finding(rule="A3.7", where=f"{rel_path(ledger.path, ctx.root)}:{problem.line}",
                        message=f"decision ledger: {problem.message}",
                        fix_hint="the ledger is append-only and hash-chained; escalate to the lead architect"))
    plan = ctx.require_file("plan.md")
    pattern = ctx.cfg.option("A3.7", "id_pattern", LEDGER_ID_PATTERN)
    today = ctx.today()
    for entry_id, line in cited_ids(plan, pattern):
        problem = ledger.check_entry(entry_id, today)
        if problem:
            res.add(Finding(rule="A3.7", where=f"plan.md:{line}", message=f"cited decision {problem}",
                            fix_hint="cite only approved, unexpired ledger entries with an owner"))
    for ex in ctx.cfg["standards"].get("exclude") or []:
        if not ex.get("waiver"):
            continue
        problem = ledger.check_entry(ex["waiver"], today, ex["rule"])
        if problem:
            res.add(Finding(rule=ex["rule"], where="archiguard-config.yml standards.exclude",
                            message=f"the exclusion of {ex['rule']} is no longer covered: {problem}",
                            fix_hint="renew the waiver or bring the rule back into scope (archiguard resolve)"))


CHECKS = {
    "A3.1": check_a3_1,
    "A3.3": check_a3_3,
    "A3.4": check_a3_4,
    "A3.5": check_a3_5,
    "A3.6": check_a3_6,
    "A3.7": check_a3_7,
}

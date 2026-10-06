"""The archiGuard commands behind the CLI."""

from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape as xml_escape

from . import __version__, standards
from .common import (
    ENGINE_ROOT,
    EXIT_ERROR,
    EXIT_ESCALATE,
    EXIT_FAIL,
    EXIT_PASS,
    GATES_DIRNAME,
    ArchiGuardError,
    feature_dirs,
    git,
    git_branch,
    git_head,
    glob_match,
    read_text,
    rel_path,
    sha256_file,
    write_json,
    write_text,
)
from .config import COMMANDS, Config, normalise_command, short_command
from .domain import load_domain_map
from .gates.context import GateContext
from .gates.dispatch import run_entry
from .gates.handover import build_manifest
from .gates.registry import resolve_entry
from .ledger import Ledger, make_entry
from .runner import StepOutcome, render_text, verify
from .verdict import CheckResult

SEVERITY_ORDER = {EXIT_PASS: 0, EXIT_FAIL: 1, EXIT_ESCALATE: 2, EXIT_ERROR: 3}


def worst(*codes: int) -> int:
    return max(codes, key=lambda c: SEVERITY_ORDER.get(c, 3)) if codes else EXIT_PASS


def parse_check_ref(ref: str) -> Tuple[str, str]:
    """'A3.6' -> (A3, A3.6); 'H4' -> (H, H4); 'scope.plan' -> (scope, plan)."""
    m = re.match(r"^(A[0-9])\.\d+$", ref)
    if m:
        return m.group(1), ref
    if re.match(r"^H\d+$", ref):
        return "H", ref
    if "." in ref:
        gate, _, check = ref.partition(".")
        return gate, check
    raise ArchiGuardError(f"cannot tell which gate runs {ref!r} (use A3.6, H4 or <gate>.<check>)")


EXCERPT_LINES = 20


def results_exit(results: Sequence[CheckResult]) -> int:
    if any(r.error for r in results):
        return EXIT_ERROR
    if any(r.blocking for r in results if not r.repairable):
        return EXIT_ESCALATE
    if any(r.blocking for r in results):
        return EXIT_FAIL
    return EXIT_PASS


def render_results(title: str, results: Sequence[CheckResult], verbose: bool = False) -> str:
    out = [title]
    for r in results:
        mark = {"pass": "[PASS]", "waived": "[WAIV]", "violation": "[FAIL]", "error": "[ERR ]"}[r.status]
        detail = f"cannot evaluate: {r.error}" if r.error else (
            f"{len(r.blocking)} blocking" if r.blocking else (f"{len(r.waived)} waived" if r.waived else ""))
        out.append(f"  {mark} {r.gate} · {r.check} {r.name:<28} {detail}".rstrip())
        for f in r.blocking:
            out.append(f"         - {f.rule}: {f.message}" + (f" ({f.where})" if f.where else ""))
            if f.fix_hint and verbose:
                out.append(f"           fix: {f.fix_hint}")
            if f.excerpt:
                lines = str(f.excerpt).rstrip().split("\n")
                out.extend(f"           | {line}" for line in lines[-EXCERPT_LINES:])
        if verbose:
            for f in r.advisory:
                out.append(f"         ~ {f.rule}: {f.message}" + (f" ({f.where})" if f.where else ""))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# check (plug-in contract invocation of built-in gates)                         #
# --------------------------------------------------------------------------- #


def cmd_check(root: Path, cfg: Config, feature_dir: Optional[Path], gate: str, checks: List[str],
              iteration: Optional[int], as_json: bool, verbose: bool) -> int:
    resolved = resolve_entry(cfg, {"gate": gate, "run": checks, "repair": None, "mode": None}, "check")
    ctx = GateContext(root, cfg, feature_dir, iteration=iteration)
    results = run_entry(ctx, resolved)
    code = results_exit(results)
    if as_json:
        commit, _ = ctx.head()
        print(json.dumps({"verdicts": [r.to_verdict(version=__version__, feature=ctx.feature, commit=commit,
                                                      pins=ctx.pins(), iteration=iteration, max_iterations=None)
                                       for r in results]}, indent=2, ensure_ascii=False))
    else:
        print(render_results(f"archiGuard {__version__} | {gate} {' '.join(checks)} | feature: {ctx.feature}", results, verbose))
        for r in results:
            if r.info:
                print("\n".join(r.info))
    return code


# --------------------------------------------------------------------------- #
# rules (A3.1)                                                                  #
# --------------------------------------------------------------------------- #


def cmd_rules(root: Path, cfg: Config, feature_dir: Optional[Path], as_json: bool) -> int:
    ctx = GateContext(root, cfg, feature_dir)
    res = CheckResult(gate="A3", check="A3.1", name="context loader", stage="plan")
    from .gates.a3 import check_a3_1

    try:
        check_a3_1(ctx, res)
    except ArchiGuardError as exc:
        print(f"archiGuard: ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if as_json:
        rules, filtered = ctx.applicable
        print(json.dumps({"stacks": ctx.stacks, "home_context": ctx.home_context,
                          "rules": [r["id"] for r in rules], "filtered_out": filtered}, indent=2))
    else:
        print("\n".join(res.info))
    return EXIT_PASS


# --------------------------------------------------------------------------- #
# resolve / validate-standards                                                  #
# --------------------------------------------------------------------------- #


def _domain_map_optional(cfg: Config):
    path = cfg.path("domain", "map")
    if path is None or not path.is_file():
        return None
    dm = load_domain_map(path)
    problems = dm.problems()
    if problems:
        raise ArchiGuardError(f"the domain map {path} is not valid: {problems[0]}")
    return dm


def cmd_resolve(root: Path, cfg: Config, check_only: bool, as_json: bool) -> int:
    from .common import today

    ledger = Ledger.load(cfg.path("ledger", "path"))
    lock = standards.resolve(cfg, ledger, _domain_map_optional(cfg), today(ci=cfg.ci))
    path = cfg.path("standards", "lock")
    if check_only:
        if path is None or not path.is_file():
            print(f"archiGuard: standards lock {path} is missing - run 'archiguard resolve' and commit it", file=sys.stderr)
            return EXIT_FAIL
        old = standards.read_lock(path)
        diff = standards.diff_locks(old, lock)
        if as_json:
            print(json.dumps({"drift": diff}, indent=2))
        elif diff:
            print("archiGuard: standards.lock.yml drifted from the rulebook / config:")
            for d in diff:
                print(f"  - {d}")
            print("Run 'archiguard resolve', review the change and commit the lock.")
        else:
            print(f"archiGuard: standards.lock.yml is current ({len(lock['rules'])} rules, {lock['rulebook']['name']}@{lock['rulebook']['tag']})")
        return EXIT_FAIL if diff else EXIT_PASS
    standards.write_lock(path, lock)
    if as_json:
        print(json.dumps({"lock": rel_path(path, root), "rules": len(lock["rules"]), "hash": standards.lock_hash(lock)}, indent=2))
    else:
        judged = sum(1 for r in lock["rules"] if r["check"] == "judgement")
        print(f"archiGuard: wrote {rel_path(path, root)} - {lock['rulebook']['name']}@{lock['rulebook']['tag']}, "
              f"{len(lock['rules'])} rule(s) ({judged} by agent judgement), {len(lock['excluded'])} excluded")
    return EXIT_PASS


def cmd_validate_standards(path: Path, as_json: bool) -> int:
    rb = standards.load_rulebook(path)
    if as_json:
        print(json.dumps({"rulebook": rb.name, "version": rb.version, "rules": len(rb.rules),
                          "profiles": sorted(rb.profiles), "packs": sorted(rb.packs), "problems": rb.problems}, indent=2))
    else:
        print(f"archiGuard validate-standards | {rb.name or '?'} {rb.version or '?'} | {len(rb.rules)} rules, "
              f"{len(rb.profiles)} profiles, {len(rb.packs)} packs")
        for p in rb.problems:
            print(f"  [FAIL] {p}")
        if not rb.problems:
            declared = sum(1 for r in rb.rules.values() if r.get("checks"))
            print(f"  [PASS] rulebook is valid ({declared} rule(s) with declared checks)")
    return EXIT_FAIL if rb.problems else EXIT_PASS


# --------------------------------------------------------------------------- #
# signoff / reopen                                                              #
# --------------------------------------------------------------------------- #


def _branch_matches(branch: str, feature_dir: Path) -> bool:
    name = feature_dir.name
    last = branch.split("/")[-1]
    if last == name:
        return True
    num_b, num_f = re.match(r"^(\d{3,})-", last), re.match(r"^(\d{3,})-", name)
    return bool(num_b and num_f and num_b.group(1) == num_f.group(1))


def design_paths(feature_dir: Path, cfg: Config) -> List[Path]:
    from .runner import ARTEFACTS

    paths = [feature_dir / n for n in ARTEFACTS + (cfg["feature"]["handover"],)]
    paths.append(feature_dir / "contracts")
    return paths


def cmd_signoff(root: Path, cfg: Config, feature_dir: Path, by: str, role: str, as_json: bool) -> int:
    from .runner import artefact_hashes

    if not by or not by.strip():
        raise ArchiGuardError("--by is required: the name of the design authority who signs the plan")
    evidence: Dict[str, str] = {}
    problems: List[str] = []
    existing = feature_dir / GATES_DIRNAME / "signoff.json"
    if existing.is_file():
        try:
            prev = json.loads(read_text(existing))
        except ValueError:
            prev = {}
        problems.append(f"the design is already signed ({prev.get('at', '?')} by {prev.get('by', '?')}) - "
                        "re-open it first: archiguard reopen --by <name> --reason <text>")
    code, _ = git(root, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        raise ArchiGuardError("the design sign-off needs a git repository (the signed design is a commit)")
    branch = git_branch(root)
    if not _branch_matches(branch, feature_dir):
        problems.append(f"the design is signed on the feature branch ({feature_dir.name}); the current branch is "
                        f"'{branch or '?'}'")
    rels = [rel_path(p, root) for p in design_paths(feature_dir, cfg) if p.exists()]
    code, out = git(root, "status", "--porcelain", "--untracked-files=all", "--", *rels)
    if code == 0 and out.strip():
        changed = sorted({line[3:].strip().strip('"') for line in out.split("\n") if len(line) > 3})
        problems.append("the design has uncommitted changes - commit it first: " + ", ".join(changed[:8])
                        + (" ..." if len(changed) > 8 else ""))
    for item in cfg["signoff"]["require"]:
        if normalise_command(item) in COMMANDS:
            outcome = verify(root, cfg, item, feature_dir)
            evidence[normalise_command(item)] = outcome.status
            if outcome.status != "pass":
                problems.append(f"{normalise_command(item)} gates: {outcome.status}")
        else:
            gate, check = parse_check_ref(item)
            resolved = resolve_entry(cfg, {"gate": gate, "run": [check], "repair": None, "mode": None}, "signoff.require")
            ctx = GateContext(root, cfg, feature_dir)
            results = run_entry(ctx, resolved)
            status = results[0].status if results else "error"
            evidence[item] = status
            if status not in ("pass", "waived"):
                problems.append(f"{item}: {status}" + (f" ({results[0].error})" if results and results[0].error else ""))
    if problems:
        print("archiGuard: sign-off refused - the design is not ready to sign:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("Commit the design on the feature branch with green evidence (archiguard verify plan / tasks), "
              "then sign again.", file=sys.stderr)
        return EXIT_FAIL
    ctx = GateContext(root, cfg, feature_dir)
    commit, dirty = git_head(root)
    hashes = artefact_hashes(feature_dir, cfg)
    applicable = feature_dir / GATES_DIRNAME / "applicable-rules.json"
    if applicable.is_file():
        hashes["gates/applicable-rules.json"] = sha256_file(applicable)
    record = {
        "by": by.strip(),
        "role": role,
        "at": _dt.datetime.now().replace(microsecond=0).isoformat(),
        "feature": ctx.feature,
        "commit": commit,
        "dirty": dirty,
        "hashes": hashes,
        "pins": ctx.pins(),
        "evidence": evidence,
        "archiguard": __version__,
    }
    path = feature_dir / GATES_DIRNAME / "signoff.json"
    write_json(path, record)
    if as_json:
        print(json.dumps(record, indent=2))
    else:
        print(f"archiGuard: design sign-off recorded by {record['by']} ({role}) in {rel_path(path, root)}")
        print("Commit it with the plan; spec.md, plan.md and the design artefacts are now read-only for agents.")
    return EXIT_PASS


def cmd_reopen(root: Path, feature_dir: Path, by: str, reason: str) -> int:
    path = feature_dir / GATES_DIRNAME / "signoff.json"
    if not path.is_file():
        print("archiGuard: no sign-off to re-open", file=sys.stderr)
        return EXIT_FAIL
    if not by.strip() or not reason.strip():
        raise ArchiGuardError("--by and --reason are required to re-open a signed design")
    record = json.loads(read_text(path))
    record["reopened"] = {"by": by.strip(), "reason": reason.strip(),
                          "at": _dt.datetime.now().replace(microsecond=0).isoformat()}
    history = feature_dir / GATES_DIRNAME / "signoff-history"
    stamp = record["reopened"]["at"].replace(":", "").replace("-", "")
    write_json(history / f"signoff-{stamp}.json", record)
    path.unlink()
    print(f"archiGuard: design re-opened by {by.strip()} - the previous sign-off is kept in {rel_path(history, root)}")
    return EXIT_PASS


# --------------------------------------------------------------------------- #
# handover 4 -> 5                                                               #
# --------------------------------------------------------------------------- #


def cmd_handover(root: Path, cfg: Config, feature_dir: Path, as_json: bool, verbose: bool) -> int:
    checks = cfg.option("handover", "checks", ["H1", "H2", "H3", "H4", "H5", "H6"])
    resolved = resolve_entry(cfg, {"gate": "H", "run": list(checks), "repair": None, "mode": None}, "handover")
    ctx = GateContext(root, cfg, feature_dir)
    results = run_entry(ctx, resolved)
    code = results_exit(results)
    manifest = build_manifest(ctx, results)
    manifest["status"] = {EXIT_PASS: "pass", EXIT_FAIL: "violation", EXIT_ESCALATE: "escalated", EXIT_ERROR: "error"}[code]
    path = feature_dir / GATES_DIRNAME / "handover-4-5.json"
    write_json(path, manifest)
    if as_json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(render_results(f"archiGuard {__version__} | handover 4 -> 5 | feature: {ctx.feature}", results, verbose))
        print(f"\nRESULT: {manifest['status'].upper()} | manifest: {rel_path(path, root)}")
        if code == EXIT_FAIL:
            print("NEXT: back to implement - fix the entry checks above (this is not a test-loop iteration).")
    return code


# --------------------------------------------------------------------------- #
# test loop                                                                     #
# --------------------------------------------------------------------------- #


def cmd_test(root: Path, cfg: Config, feature_dir: Path, run: bool, as_json: bool, verbose: bool) -> int:
    from .testloop import run_tests

    ctx = GateContext(root, cfg, feature_dir)
    res = CheckResult(gate="T", check="T1", name="test loop", stage="tests")
    try:
        run_tests(ctx, res, run=run)
    except ArchiGuardError as exc:
        res.error = str(exc)
    commit, _ = ctx.head()
    verdict = res.to_verdict(version=__version__, feature=ctx.feature, commit=commit, pins=ctx.pins(),
                             iteration=None, max_iterations=None)
    write_json(feature_dir / GATES_DIRNAME / "test-loop.json", verdict)
    if as_json:
        print(json.dumps(verdict, indent=2, ensure_ascii=False))
    else:
        s = res.data.get("summary") or {}
        print(render_results(f"archiGuard {__version__} | test loop 4 <-> 5 | feature: {ctx.feature}", [res], True))
        if s:
            print(f"\n{s.get('cases', 0)} test case(s), {s.get('failed', 0)} failed, {s.get('skipped', 0)} skipped; "
                  f"{s.get('traced', 0)}/{s.get('in_scope', 0)} in-scope id(s) traced to a passing test")
    return results_exit([res])


# --------------------------------------------------------------------------- #
# loop counter (workflow-driven loops)                                          #
# --------------------------------------------------------------------------- #


def _loop_state(feature_dir: Path, name: str) -> Path:
    return feature_dir / GATES_DIRNAME / ".state" / f"loop-{name}.json"


def cmd_loop(root: Path, cfg: Config, feature_dir: Path, name: str, reset: bool, status: bool,
             inner: List[str], runner) -> int:
    bound = cfg.loop_bound(name)
    path = _loop_state(feature_dir, name)
    state = json.loads(read_text(path)) if path.is_file() else {"count": 0, "last": None}
    if reset:
        if path.exists():
            path.unlink()
        print(f"archiGuard: loop {name} reset (bound {bound})")
        return EXIT_PASS
    if status:
        last = state.get("last")
        print(f"archiGuard: loop {name}: {last or 'not run'} - {state.get('count', 0)} red run(s) since the last pass "
              f"(bound: {bound} repair iteration(s))")
        return {"pass": EXIT_PASS, None: EXIT_FAIL, "red": EXIT_FAIL, "escalated": EXIT_ESCALATE}.get(last, EXIT_ERROR)
    if not inner:
        raise ArchiGuardError("loop needs the archiguard command to run after '--', e.g. loop test_loop -- test")
    code = runner(inner)
    if code == EXIT_PASS:
        # green is terminal: the next red starts a new loop with the full budget
        write_json(path, {"count": 0, "last": "pass", "red_runs_before_pass": state.get("count", 0)})
        return EXIT_PASS
    if code in (EXIT_ERROR, EXIT_ESCALATE):
        state["last"] = "escalated" if code == EXIT_ESCALATE else "error"
        write_json(path, state)
        return code
    count = int(state.get("count", 0)) + 1
    if count > bound:
        state = {"count": count, "last": "escalated"}
        write_json(path, state)
        note = feature_dir / GATES_DIRNAME / f"escalation-loop-{name}.md"
        write_text(note, (
            f"# archiGuard escalation - loop {name}\n\n"
            f"- Feature: `{rel_path(feature_dir, root)}`\n- Reason: still red after {bound} repair iteration(s) (loops.{name})\n"
            f"- Last command: `archiguard {' '.join(inner)}`\n\n"
            "The loop stopped. See the latest verdict in the gates/ folder for the open findings.\n\n"
            "- What was attempted: TODO(agent)\n- Blocker: TODO(agent)\n"
            "- Decision needed (fix the artefact · RFI to the BA · waiver in the ledger): TODO(agent)\n"
        ))
        print(f"archiGuard: loop {name} ESCALATED - still red after {bound} repair iteration(s); "
              f"complete every TODO(agent) in {rel_path(note, root)}")
        return EXIT_ESCALATE
    state = {"count": count, "last": "red"}
    write_json(path, state)
    print(f"archiGuard: loop {name}: red - repair iteration {count} of {bound}")
    return EXIT_FAIL


# --------------------------------------------------------------------------- #
# compliance report                                                             #
# --------------------------------------------------------------------------- #


def _verdict_files(feature_dir: Path) -> List[Tuple[str, Dict[str, Any]]]:
    out = []
    gates_dir = feature_dir / GATES_DIRNAME
    for gate in ("A0", "A3", "A4", "H", "scope"):
        for path in sorted((gates_dir / gate).glob("*.json")) if (gates_dir / gate).is_dir() else []:
            try:
                out.append((f"{gate}/{path.name}", json.loads(read_text(path))))
            except ValueError:
                continue
    for path in sorted(gates_dir.glob("*/*.json")) if gates_dir.is_dir() else []:
        gate = path.parent.name
        if gate in ("A0", "A3", "A4", "H", "scope", ".state", "signoff-history"):
            continue
        try:
            out.append((f"{gate}/{path.name}", json.loads(read_text(path))))
        except ValueError:
            continue
    return out


def build_report(root: Path, cfg: Config, feature_dir: Path) -> Tuple[str, Dict[str, Any]]:
    ctx = GateContext(root, cfg, feature_dir, write=False)
    commit, dirty = ctx.head()
    pins = ctx.pins()
    lines = [
        f"# Architecture compliance report - {ctx.feature}",
        "",
        f"archiGuard {__version__} · commit {commit or '-'}{' (uncommitted changes)' if dirty else ''}",
        f"Rulebook {pins.get('rulebook') or '-'} · domain map {pins.get('domain_map') or '-'} · specification {pins.get('spec') or '-'}",
        "",
        "## Verdicts",
        "",
        "| Gate | Check | Status | Blocking | Advisory | Waived | Iteration |",
        "|---|---|---|---|---|---|---|",
    ]
    rows = []
    for name, v in _verdict_files(feature_dir):
        findings = v.get("findings") or []
        blocking = sum(1 for f in findings if f.get("severity") == "blocking")
        advisory = len(findings) - blocking
        lines.append(f"| {v.get('gate')} | {v.get('check')} | {v.get('status')} | {blocking} | {advisory} | "
                     f"{len(v.get('waived') or [])} | {v.get('iteration') if v.get('iteration') is not None else '-'} |")
        rows.append({"file": name, "gate": v.get("gate"), "check": v.get("check"), "status": v.get("status"),
                     "blocking": blocking, "waived": len(v.get("waived") or [])})
    steps = []
    for path in sorted((feature_dir / GATES_DIRNAME).glob("*-*.json")):
        if path.name.startswith(("handover-", "test-")):
            continue
        try:
            data = json.loads(read_text(path))
        except ValueError:
            continue
        if "step" in data:
            steps.append((path.name, data))
    if steps:
        lines += ["", "## Steps", "", "| Evidence | Command | Step | Status | Iteration |", "|---|---|---|---|---|"]
        for name, data in steps:
            lines.append(f"| {name} | {data.get('command')} | {data.get('step')} | {data.get('status')} | "
                         f"{data.get('iteration') if data.get('iteration') is not None else '-'} |")
    waived = []
    for _, v in _verdict_files(feature_dir):
        for w in v.get("waived") or []:
            waived.append((v.get("check"), w))
    lines += ["", "## Waivers and deviations", ""]
    if waived:
        lines += ["| Check | Rule | Waiver | Expires | Reason |", "|---|---|---|---|---|"]
        for check, w in waived:
            lines.append(f"| {check} | {w.get('rule')} | {w.get('waiver')} | {w.get('expires') or '-'} | {w.get('reason') or ''} |")
    else:
        lines.append("None.")
    skipped = []
    for _, v in _verdict_files(feature_dir):
        for s in v.get("rules_skipped") or []:
            skipped.append((v.get("check"), s))
    if skipped:
        lines += ["", "## Rules judged by the agent (no declared check)", ""]
        lines += [f"- {check}: {s.get('rule')} - {s.get('reason')}" for check, s in skipped]
    so = ctx.signoff
    lines += ["", "## Design authority sign-off", ""]
    if so:
        lines.append(f"Signed by {so.get('by')} ({so.get('role')}) on {so.get('at')} at commit {so.get('commit') or '-'}; "
                     f"evidence: {', '.join(f'{k}: {v}' for k, v in (so.get('evidence') or {}).items())}.")
    else:
        lines.append("Not signed yet.")
    hand = feature_dir / GATES_DIRNAME / "handover-4-5.json"
    if hand.is_file():
        try:
            h = json.loads(read_text(hand))
            lines += ["", "## Handover 4 -> 5", "",
                      f"Status {h.get('status')}; entry checks: {', '.join(f'{k}: {v}' for k, v in (h.get('entry_checks') or {}).items())}."]
        except ValueError:
            pass
    tl = feature_dir / GATES_DIRNAME / "test-loop.json"
    if tl.is_file():
        try:
            t = json.loads(read_text(tl))
            s = (t.get("data") or {}).get("summary") or {}
            lines += ["", "## Test loop", "",
                      f"Status {t.get('status')}; {s.get('cases', 0)} test case(s), {s.get('failed', 0)} failed, "
                      f"{s.get('traced', 0)}/{s.get('in_scope', 0)} in-scope id(s) traced."]
        except ValueError:
            pass
    statuses = [r["status"] for r in rows]
    overall = "error" if "error" in statuses else ("violation" if "violation" in statuses else ("waived" if "waived" in statuses else ("pass" if statuses else "no evidence")))
    lines[5:5] = [f"**Overall: {overall}**", ""]
    data = {"feature": ctx.feature, "commit": commit, "pins": pins, "overall": overall, "verdicts": rows,
            "signoff": so, "waivers": [w for _, w in waived]}
    return "\n".join(lines) + "\n", data


def cmd_report(root: Path, cfg: Config, feature_dir: Path, save: bool, as_json: bool, out: Optional[str]) -> int:
    md, data = build_report(root, cfg, feature_dir)
    if save:
        write_text(feature_dir / GATES_DIRNAME / "architecture-compliance.md", md)
    if out:
        write_text(Path(out), md)
    print(json.dumps(data, indent=2, ensure_ascii=False) if as_json else md)
    return EXIT_PASS


# --------------------------------------------------------------------------- #
# CI                                                                            #
# --------------------------------------------------------------------------- #


def cmd_ci(root: Path, cfg: Config, feature: Optional[Path], all_features: bool, implement: bool,
           as_json: bool, junit: Optional[str], out: Optional[str]) -> int:
    report: Dict[str, Any] = {"tool": "archiguard", "version": __version__, "checks": [], "features": []}
    codes: List[int] = []
    lines = [f"archiGuard {__version__} | CI | {root.name}"]

    # 1. the standards lock must match the rulebook at the pinned tag
    if cfg["standards"].get("rulebook"):
        try:
            from .common import today

            ledger = Ledger.load(cfg.path("ledger", "path"))
            fresh = standards.resolve(cfg, ledger, _domain_map_optional(cfg), today(ci=True))
            old = standards.read_lock(cfg.path("standards", "lock"))
            diff = standards.diff_locks(old, fresh)
            status = "violation" if diff else "pass"
            codes.append(EXIT_FAIL if diff else EXIT_PASS)
            report["checks"].append({"check": "standards-lock", "status": status, "drift": diff})
            lines.append(f"  {'[FAIL]' if diff else '[PASS]'} standards lock " + ("; ".join(diff) if diff else "current"))
        except ArchiGuardError as exc:
            codes.append(EXIT_ERROR)
            report["checks"].append({"check": "standards-lock", "status": "error", "error": str(exc)})
            lines.append(f"  [ERR ] standards lock: {exc}")
    # 2. the decision ledger must be intact
    ledger = Ledger.load(cfg.path("ledger", "path"))
    if ledger.problems:
        codes.append(EXIT_FAIL)
        report["checks"].append({"check": "ledger", "status": "violation",
                                 "problems": [f"line {p.line}: {p.message}" for p in ledger.problems]})
        lines.append(f"  [FAIL] decision ledger: {ledger.problems[0].message} (line {ledger.problems[0].line})")
    else:
        report["checks"].append({"check": "ledger", "status": "pass", "entries": len(ledger.entries)})
        lines.append(f"  [PASS] decision ledger intact ({len(ledger.entries)} entries)")

    # 3. every plugged gate once, per feature, on the final commit
    if feature is not None:
        features = [feature]
    else:
        exclude = cfg.option("ci", "exclude_features", []) or []
        features = [f for f in feature_dirs(root) if not glob_match(f.name, exclude)]
    outcomes: List[Tuple[Path, StepOutcome]] = []
    for fd in features:
        entry = {"feature": rel_path(fd, root), "commands": {}}
        for command in COMMANDS:
            short = short_command(command)
            if short == "plan" and not (fd / "plan.md").is_file():
                continue
            if short == "tasks" and not (fd / "tasks.md").is_file():
                continue
            if short == "implement" and not (implement or (fd / GATES_DIRNAME / "signoff.json").is_file()):
                continue
            if not (cfg.step_entries(command, "a") or cfg.step_entries(command, "b")):
                continue
            outcome = verify(root, cfg, command, fd, ci=True)
            outcomes.append((fd, outcome))
            codes.append(outcome.exit_code)
            entry["commands"][command] = {"status": outcome.status, "combined": outcome.combined}
            lines.append("")
            lines.append(render_text(outcome, root))
        report["features"].append(entry)
    code = worst(*codes) if codes else EXIT_PASS
    if code == EXIT_ESCALATE:
        code = EXIT_FAIL
    report["exit_code"] = code
    lines.append("")
    lines.append(f"CI RESULT: {'PASS' if code == EXIT_PASS else ('ERROR' if code == EXIT_ERROR else 'FAIL')}")
    text = "\n".join(lines)
    if junit:
        write_text(Path(junit), _junit(report, outcomes, root))
    if out:
        write_text(Path(out), "```text\n" + text + "\n```\n")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str) if as_json else text)
    return code


def _junit(report: Dict[str, Any], outcomes, root: Path) -> str:
    cases = []
    for chk in report["checks"]:
        body = ""
        if chk["status"] == "violation":
            body = f'<failure message="{xml_escape(chk["check"])}">{xml_escape(json.dumps(chk, default=str))}</failure>'
        elif chk["status"] == "error":
            body = f'<error message="{xml_escape(str(chk.get("error")), {chr(34): "&quot;"})}"/>'
        cases.append(f'<testcase classname="archiguard" name="{xml_escape(chk["check"])}">{body}</testcase>')
    for fd, outcome in outcomes:
        for r in outcome.results:
            name = f"{rel_path(fd, root)} {outcome.command} {r.gate} {r.check}"
            body = ""
            if r.error:
                body = f'<error message="{xml_escape(r.error, {chr(34): "&quot;"})}"/>'
            elif r.blocking:
                text = "\n".join(f"{f.rule}: {f.message} ({f.where or '-'})" for f in r.blocking)
                body = f'<failure message="{len(r.blocking)} blocking finding(s)">{xml_escape(text)}</failure>'
            cases.append(f'<testcase classname="archiguard.{xml_escape(r.gate)}" name="{xml_escape(name, {chr(34): "&quot;"})}">{body}</testcase>')
    failures = sum(1 for c in cases if "<failure" in c)
    errors = sum(1 for c in cases if "<error" in c)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="archiguard" tests="{len(cases)}" '
            f'failures="{failures}" errors="{errors}">\n' + "\n".join(cases) + "\n</testsuite>\n")


# --------------------------------------------------------------------------- #
# ledger                                                                        #
# --------------------------------------------------------------------------- #


def cmd_ledger(root: Path, cfg: Config, action: str, args: Any) -> int:
    path = cfg.path("ledger", "path")
    ledger = Ledger.load(path)
    if action == "verify":
        if ledger.problems:
            for p in ledger.problems:
                print(f"  [FAIL] line {p.line}: {p.message}")
            return EXIT_FAIL
        print(f"archiGuard: decision ledger {rel_path(path, root) if path else '-'} is intact ({len(ledger.entries)} entries)")
        return EXIT_PASS
    if action == "list":
        from .common import today

        t = today(ci=cfg.ci)
        for eid, e in sorted(ledger.latest.items()):
            state = ledger.check_entry(eid, t) or "usable"
            print(f"  {eid:<10} {e.get('type'):<7} {e.get('status'):<9} expires {e.get('expires') or '-':<10} "
                  f"rules {', '.join(e.get('rules') or []) or '-':<20} {state}")
        return EXIT_PASS
    if action == "add":
        if ledger.get(args.id) is not None:
            raise ArchiGuardError(
                f"{args.id} is already in the ledger (status {ledger.get(args.id).get('status')}) - an entry is never "
                "rewritten: revoke it ('ledger revoke') and add the new decision under a new id"
            )
        if args.status == "approved" and not (args.approver or "").strip():
            raise ArchiGuardError("an approved entry needs --approver (the person who approved it)")
        entry = make_entry(entry_id=args.id, entry_type=args.type, title=args.title, rules=args.rule or [],
                           owner=args.owner, approver=args.approver, expires=args.expires, evidence=args.evidence,
                           status=args.status, features=args.feature, contexts=args.context)
        new = ledger.append(entry)
        print(f"archiGuard: appended {new['id']} (seq {new['seq']}) to {rel_path(path, root)}")
        return EXIT_PASS
    if action == "revoke":
        current = ledger.get(args.id)
        if current is None:
            raise ArchiGuardError(f"{args.id} is not in the ledger")
        entry = {k: v for k, v in current.items() if k not in ("seq", "prev", "hash")}
        entry["status"] = "revoked"
        entry["revoked_by"] = args.by
        entry["revoked"] = _dt.date.today().isoformat()
        new = ledger.append(entry)
        print(f"archiGuard: {new['id']} revoked (seq {new['seq']})")
        return EXIT_PASS
    raise ArchiGuardError(f"unknown ledger action {action}")


# --------------------------------------------------------------------------- #
# scaffold                                                                      #
# --------------------------------------------------------------------------- #


def cmd_scaffold(root: Path, cfg: Config, what: str, out: Optional[str], feature_dir: Optional[Path], force: bool) -> int:
    templates = ENGINE_ROOT / "templates"
    if what == "domain-map":
        source = templates / "domain-map-template.yaml"
        target = Path(out) if out else (cfg.path("domain", "map") or root / "domain-map.yaml")
    elif what == "handover":
        if feature_dir is None:
            raise ArchiGuardError("scaffold handover needs --feature-dir")
        source = templates / "handover-template.yml"
        target = Path(out) if out else feature_dir / cfg["feature"]["handover"]
    elif what == "rulebook":
        source = ENGINE_ROOT / "templates" / "rulebook"
        target = Path(out) if out else root / "standards"
    else:
        raise ArchiGuardError("scaffold what? domain-map | handover | rulebook")
    if not target.is_absolute():
        target = root / target
    if target.exists() and not force:
        raise ArchiGuardError(f"{rel_path(target, root)} already exists (use --force to overwrite)")
    if source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
    else:
        text = read_text(source)
        if what == "handover" and feature_dir is not None:
            spec_hash = sha256_file(feature_dir / "spec.md") or "<sha256 of spec.md>"
            text = text.replace("<sha256 of spec.md as released>", spec_hash)
        write_text(target, text)
    print(f"archiGuard: wrote {rel_path(target, root)} from the template - fill it in and commit it")
    return EXIT_PASS

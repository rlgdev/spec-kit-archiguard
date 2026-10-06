"""The gate runner: steps A and B of the wrapped Spec Kit commands, the per-step budget, escalation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .common import (
    EXIT_ERROR,
    EXIT_ESCALATE,
    EXIT_FAIL,
    EXIT_PASS,
    GATES_DIRNAME,
    PRESET_REL,
    SPECIFY_DIR,
    ArchiGuardError,
    read_text,
    rel_path,
    sha256_file,
    sha256_text,
    write_json,
    write_text,
)
from .config import Config, normalise_command, short_command
from .gates.context import GateContext
from .gates.dispatch import run_entry
from .gates.registry import resolve_entry
from .verdict import CheckResult

ARTEFACTS = ("spec.md", "plan.md", "research.md", "data-model.md", "quickstart.md", "tasks.md")
STATUS_PASS, STATUS_VIOLATION, STATUS_ESCALATED, STATUS_ERROR = "pass", "violation", "escalated", "error"


# --------------------------------------------------------------------------- #
# Integration                                                                   #
# --------------------------------------------------------------------------- #


def preset_installed(root: Path) -> bool:
    preset = root / PRESET_REL
    if not all((preset / "commands" / f"{name}.md").is_file() for name in ("speckit.plan", "speckit.tasks", "speckit.implement")):
        return False
    registry = root / SPECIFY_DIR / "presets" / ".registry"
    if registry.is_file():
        try:
            entry = json.loads(read_text(registry)).get("presets", {}).get("archiguard-templates")
            if isinstance(entry, dict) and entry.get("enabled") is False:
                return False
        except (ValueError, AttributeError):
            pass
    return True


def effective_integration(root: Path, cfg: Config) -> Tuple[str, Optional[str]]:
    wanted = cfg["integration"]
    if wanted == "inline" and not preset_installed(root):
        return "hooks", ("integration is 'inline' but the archiguard-templates preset is not installed or is disabled, "
                         "so the gates run through the hooks")
    return wanted, None


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #


def artefact_hashes(feature_dir: Path, cfg: Config) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name in ARTEFACTS + (cfg["feature"]["handover"],):
        h = sha256_file(feature_dir / name)
        if h:
            out[name] = h
    contracts = feature_dir / "contracts"
    if contracts.is_dir():
        for p in sorted(contracts.rglob("*")):
            if p.is_file():
                h = sha256_file(p)
                if h:
                    out[p.relative_to(feature_dir).as_posix()] = h
    return out


def fingerprint(results: List[CheckResult]) -> Optional[str]:
    keys = sorted(f.key() for r in results for f in r.blocking)
    return sha256_text("\n".join(keys)) if keys else None


def _state_path(feature_dir: Path, command: str) -> Path:
    return feature_dir / GATES_DIRNAME / ".state" / f"{short_command(command)}-b.json"


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"runs": [], "terminal": True}
    try:
        data = json.loads(read_text(path))
        if isinstance(data, dict) and isinstance(data.get("runs"), list):
            return data
    except ValueError:
        pass
    return {"runs": [], "terminal": True}


def _combined_path(feature_dir: Path, command: str, step: str) -> Path:
    return feature_dir / GATES_DIRNAME / f"{short_command(command)}-{step}.json"


def _escalation_path(feature_dir: Path, command: str, step: str) -> Path:
    return feature_dir / GATES_DIRNAME / f"escalation-{short_command(command)}-{step}.md"


class StepOutcome:
    def __init__(self, command: str, step: str, status: str, exit_code: int, combined: Dict[str, Any],
                 results: List[CheckResult], escalation: Optional[Path] = None, reason: Optional[str] = None,
                 skipped: Optional[str] = None):
        self.command = command
        self.step = step
        self.status = status
        self.exit_code = exit_code
        self.combined = combined
        self.results = results
        self.escalation = escalation
        self.reason = reason
        self.skipped = skipped


# --------------------------------------------------------------------------- #
# Running a step                                                                #
# --------------------------------------------------------------------------- #


def _run_entries(ctx: GateContext, cfg: Config, entries: List[Dict[str, Any]], where: str) -> List[Tuple[Any, List[CheckResult]]]:
    out = []
    for idx, raw in enumerate(entries, start=1):
        resolved = resolve_entry(cfg, raw, f"{where}[{idx}]")
        out.append((resolved, run_entry(ctx, resolved)))
    return out


def _combined(ctx: GateContext, cfg: Config, command: str, step: str, groups, *, iteration, budget,
              status: str, reason: Optional[str], history: List[Dict[str, Any]], escalation: Optional[Path],
              mode_label: str) -> Dict[str, Any]:
    commit, dirty = ctx.head()
    gates = []
    findings = []
    for resolved, results in groups:
        for r in results:
            gates.append({
                "gate": resolved.gate, "check": r.check, "name": r.name, "mode": r.mode,
                "repair": r.repairable, "status": r.status, "blocking": len(r.blocking),
                "advisory": len(r.advisory), "waived": len(r.waived), "error": r.error,
                "verdict": f"{GATES_DIRNAME}/{resolved.gate}/{r.check}.json",
            })
            for f in r.blocking:
                d = f.to_dict()
                d["repairable"] = r.repairable
                findings.append(d)
    return {
        "tool": "archiguard",
        "version": __version__,
        "command": command,
        "step": step,
        "run": mode_label,
        "mode": cfg["mode"],
        "feature": ctx.feature,
        "commit": commit,
        "dirty": dirty,
        "artefacts": artefact_hashes(ctx.feature_dir, cfg) if ctx.feature_dir else {},
        "pins": ctx.pins(),
        "iteration": iteration,
        "max_iterations": budget,
        "status": status,
        "escalation": ({"reason": reason, "report": rel_path(escalation, ctx.root)} if escalation else None),
        "gates": gates,
        "findings": findings,
        "history": history,
    }


def run_step(root: Path, cfg: Config, command: str, step: str, feature_dir: Path, *, via: Optional[str] = None) -> StepOutcome:
    command = normalise_command(command)
    step = step.lower()
    if step not in ("a", "b"):
        raise ArchiGuardError("step must be a or b")
    if via:
        eff, note = effective_integration(root, cfg)
        wanted = "inline" if via == "inline" else "hooks"
        if eff != wanted:
            msg = (f"archiGuard: {command} step {step.upper()} skipped here - integration is '{eff}', so the gates run "
                   + ("inside the wrapped Spec Kit command." if eff == "inline" else "through the archiGuard hook commands.")
                   + " Nothing to do; continue.")
            if note:
                msg += f" Note: {note}."
            return StepOutcome(command, step, "skipped", EXIT_PASS, {"status": "skipped", "message": msg}, [], skipped=msg)

    entries = cfg.step_entries(command, step)
    state_path = _state_path(feature_dir, command)
    budget = cfg.budget(command)

    if step == "a":
        if state_path.exists():
            state_path.unlink()
        ctx = GateContext(root, cfg, feature_dir)
        groups = _run_entries(ctx, cfg, entries, f"pipeline.{command}.step_a")
        results = [r for _, rs in groups for r in rs]
        if any(r.error for r in results):
            status, code, reason = STATUS_ERROR, EXIT_ERROR, "a gate could not evaluate"
        elif any(r.blocking for r in results if not r.repairable):
            status, code, reason = STATUS_ESCALATED, EXIT_ESCALATE, "a check no agent may repair is red"
        elif any(r.blocking for r in results):
            status, code, reason = STATUS_VIOLATION, EXIT_FAIL, None
        else:
            status, code, reason = STATUS_PASS, EXIT_PASS, None
        escalation = _escalation_path(feature_dir, command, step)
        history = [{"iteration": None, "status": status}]
        combined = _combined(ctx, cfg, command, step, groups, iteration=None, budget=None, status=status,
                             reason=reason, history=history, escalation=escalation if status == STATUS_ESCALATED else None,
                             mode_label="step")
        write_json(_combined_path(feature_dir, command, step), combined)
        if status == STATUS_ESCALATED:
            write_text(escalation, render_escalation(ctx, combined, groups, reason or ""))
        elif escalation.exists():
            escalation.unlink()
        return StepOutcome(command, step, status, code, combined, results,
                           escalation if status == STATUS_ESCALATED else None, reason)

    # step B: the bounded repair loop, one budget for the insertion point
    state = _load_state(state_path)
    runs = [] if state.get("terminal") else list(state.get("runs") or [])
    iteration = (runs[-1]["iteration"] + 1) if runs else 0
    ctx = GateContext(root, cfg, feature_dir, iteration=iteration, max_iterations=budget)
    groups = _run_entries(ctx, cfg, entries, f"pipeline.{command}.step_b")
    results = [r for _, rs in groups for r in rs]
    fp = fingerprint([r for r in results if r.repairable])
    reason: Optional[str] = None
    if any(r.error for r in results):
        status, code, reason = STATUS_ERROR, EXIT_ERROR, "a gate could not evaluate (fail-closed, no repair)"
    elif any(r.blocking for r in results if not r.repairable):
        status, code, reason = STATUS_ESCALATED, EXIT_ESCALATE, "a check no agent may repair is red"
    elif any(r.blocking for r in results):
        seen = [run for run in runs if run.get("fingerprint") == fp]
        if seen:
            status, code = STATUS_ESCALATED, EXIT_ESCALATE
            reason = (f"no progress: the same findings came back as in iteration {seen[0]['iteration']} "
                      "(the repairs conflict or cannot satisfy the rules)")
        elif iteration >= budget:
            status, code, reason = STATUS_ESCALATED, EXIT_ESCALATE, f"the budget of {budget} repair iteration(s) is used up"
        else:
            status, code = STATUS_VIOLATION, EXIT_FAIL
    else:
        status, code = STATUS_PASS, EXIT_PASS
    terminal = status != STATUS_VIOLATION
    runs.append({
        "iteration": iteration,
        "status": status,
        "fingerprint": fp,
        "gates": {f"{r.gate} {r.check}": r.status for r in results},
        "blocking": sum(len(r.blocking) for r in results),
    })
    write_json(state_path, {"runs": runs, "terminal": terminal})
    escalation = _escalation_path(feature_dir, command, step)
    combined = _combined(ctx, cfg, command, step, groups, iteration=iteration, budget=budget, status=status,
                         reason=reason, history=runs, escalation=escalation if status == STATUS_ESCALATED else None,
                         mode_label="step")
    write_json(_combined_path(feature_dir, command, step), combined)
    if status == STATUS_ESCALATED:
        write_text(escalation, render_escalation(ctx, combined, groups, reason or ""))
    elif escalation.exists() and status == STATUS_PASS:
        escalation.unlink()
    return StepOutcome(command, step, status, code, combined, results,
                       escalation if status == STATUS_ESCALATED else None, reason)


def verify(root: Path, cfg: Config, command: str, feature_dir: Path, *, ci: bool = False) -> StepOutcome:
    """Every gate plugged into the command (step A and step B) once: no budget, no state, no repair."""
    command = normalise_command(command)
    ctx = GateContext(root, cfg, feature_dir, ci=ci)
    entries = cfg.step_entries(command, "a") + cfg.step_entries(command, "b")
    groups = _run_entries(ctx, cfg, entries, f"pipeline.{command}")
    results = [r for _, rs in groups for r in rs]
    if any(r.error for r in results):
        status, code = STATUS_ERROR, EXIT_ERROR
    elif any(r.blocking for r in results):
        status, code = STATUS_VIOLATION, EXIT_FAIL
    else:
        status, code = STATUS_PASS, EXIT_PASS
    combined = _combined(ctx, cfg, command, "verify", groups, iteration=None, budget=None, status=status,
                         reason=None, history=[], escalation=None, mode_label="ci" if ci else "verify")
    if ctx.write:
        write_json(feature_dir / GATES_DIRNAME / f"{short_command(command)}-verify.json", combined)
    return StepOutcome(command, "verify", status, code, combined, results)


# --------------------------------------------------------------------------- #
# Rendering                                                                     #
# --------------------------------------------------------------------------- #

MARK = {"pass": "[PASS]", "waived": "[WAIV]", "violation": "[FAIL]", "error": "[ERR ]"}


def render_text(outcome: StepOutcome, root: Path, verbose: bool = False) -> str:
    if outcome.skipped:
        return outcome.skipped
    c = outcome.combined
    head = f"archiGuard {__version__} | {c['command']} · step {str(c['step']).upper()} | feature: {c['feature']}"
    if c.get("iteration") is not None:
        head += f" | iteration {c['iteration']} (budget {c['max_iterations']})"
    out = [head]
    blocking = advisory = waived = 0
    for r in outcome.results:
        label = f"{r.gate} · {r.check} {r.name}"
        status = r.status
        detail = ""
        if r.error:
            detail = f"cannot evaluate: {r.error}"
        elif status == "violation":
            detail = f"{len(r.blocking)} blocking"
        elif r.mode == "report" and r.findings:
            detail = f"{len(r.findings)} finding(s), report mode"
            status = "pass"
        elif r.waived:
            detail = f"{len(r.waived)} waived"
        if r.advisory and r.mode != "report":
            detail += (", " if detail else "") + f"{len(r.advisory)} advisory"
        out.append(f"  {MARK.get(status, '[    ]')} {label:<38} {detail}".rstrip())
        blocking += len(r.blocking)
        advisory += len(r.advisory)
        waived += len(r.waived)
    out.append("")
    combined_file = f"{c['feature']}/{GATES_DIRNAME}/{short_command(c['command'])}-{c['step']}.json"
    out.append(f"RESULT: {outcome.status.upper()} | {blocking} blocking, {advisory} advisory, {waived} waived"
               + (f" | evidence: {combined_file}" if c.get("run") != "ci" else ""))

    infos = [line for r in outcome.results for line in r.info]
    if infos and outcome.step == "a":
        out.append("")
        out.extend(infos)

    errors = [r for r in outcome.results if r.error]
    if errors:
        out.append("")
        out.append("CANNOT EVALUATE (fail-closed - fix the setup, do not repair artefacts):")
        for r in errors:
            out.append(f"  - {r.gate} {r.check}: {r.error}")

    items = [(r, f) for r in outcome.results for f in r.blocking]
    if items and outcome.status in ("violation", "escalated"):
        out.append("")
        if outcome.status != "violation":
            title = "OPEN ITEMS:"
        elif outcome.step == "b":
            title = "RESOLVE - fix every item, then run the same command again (the runner counts the iterations):"
        else:
            title = "RESOLVE - fix every item:"
        out.append(title)
        for n, (r, f) in enumerate(items, start=1):
            tag = "" if r.repairable else "  [no repair - needs a person]"
            out.append(f"  {n}. [{r.check}] {f.rule} - {f.message}{tag}")
            if f.where:
                out.append(f"       where: {f.where}")
            if f.fix_hint:
                hint = f.fix_hint.replace("\n", "\n              ")
                out.append(f"       fix:   {hint}")
            if f.excerpt and (verbose or outcome.status == "violation"):
                text = f.excerpt.strip()
                if len(text) > 900 and not verbose:
                    text = text[:900] + " ..."
                out.append("       text:  " + text.replace("\n", "\n              "))
    if advisory and verbose:
        out.append("")
        out.append("ADVISORY:")
        for r in outcome.results:
            for f in r.advisory:
                out.append(f"  - [{r.check}] {f.rule} - {f.message}" + (f" ({f.where})" if f.where else ""))
    out.append("")
    if outcome.status == "violation" and outcome.step == "b":
        out.append(f"NEXT: resolve all items above, then re-run: archiguard run {short_command(c['command'])} b")
    elif outcome.status == "violation" and outcome.step == "a":
        out.append("NEXT: the items above are part of the contract for this command; step B verifies them.")
    elif outcome.status == "escalated":
        out.append(f"ESCALATE: {outcome.reason}.")
        out.append(f"NEXT: complete every TODO(agent) in {rel_path(outcome.escalation, root) if outcome.escalation else 'the escalation note'}, "
                   "report to the user and end the command - it is not complete.")
    elif outcome.status == "error":
        out.append("NEXT: stop. Show the messages above to the user; the step cannot be evaluated until the setup is fixed.")
    elif outcome.step == "b":
        out.append(f"archiGuard: PASS after {c.get('iteration') or 0} repair iteration(s).")
    return "\n".join(out)


def render_escalation(ctx: GateContext, combined: Dict[str, Any], groups, reason: str) -> str:
    c = combined
    lines = [
        f"# archiGuard escalation - {c['command']} · step {str(c['step']).upper()}",
        "",
        f"- Feature: `{c['feature']}`",
        f"- Reason: {reason}",
        f"- Iteration: {c.get('iteration') if c.get('iteration') is not None else '-'} of budget {c.get('max_iterations') or '-'}",
        f"- Commit: {c.get('commit') or '-'}{' (uncommitted changes)' if c.get('dirty') else ''}",
        f"- Pins: rulebook {c['pins'].get('rulebook') or '-'} · domain map {c['pins'].get('domain_map') or '-'} · spec {c['pins'].get('spec') or '-'}",
        "",
        "The step stopped. The human of this step decides between: fix the artefact, change the specification "
        "through the BA (RFI), or raise a waiver in the decision ledger (approved, with owner and expiry).",
        "",
        "## Open findings",
        "",
    ]
    n = 0
    for resolved, results in groups:
        for r in results:
            for f in r.blocking:
                n += 1
                lines += [
                    f"### {n}. [{r.check}] {f.rule}",
                    "",
                    f"- Finding: {f.message}",
                    f"- Where: {f.where or '-'}",
                    f"- Repairable by the agent: {'yes' if r.repairable else 'no'}",
                ]
                if f.fix_hint:
                    lines.append(f"- Suggested fix: {f.fix_hint}")
                lines += [
                    "- What was attempted: TODO(agent)",
                    "- Blocker: TODO(agent)",
                    "- Decision needed (fix the artefact · RFI to the BA · waiver in the ledger): TODO(agent)",
                    "",
                ]
    errors = [r for _, rs in groups for r in rs if r.error]
    if errors:
        lines += ["## Gates that could not evaluate", ""]
        lines += [f"- {r.gate} {r.check}: {r.error}" for r in errors]
        lines.append("")
    history = c.get("history") or []
    if history and history[0].get("iteration") is not None:
        lines += ["## Iteration history", "", "| Iteration | Status | Blocking | Gates |", "|---|---|---|---|"]
        for run in history:
            gates = ", ".join(f"{k}: {v}" for k, v in (run.get("gates") or {}).items())
            lines.append(f"| {run.get('iteration')} | {run.get('status')} | {run.get('blocking', '-')} | {gates} |")
        lines.append("")
    return "\n".join(lines) + "\n"

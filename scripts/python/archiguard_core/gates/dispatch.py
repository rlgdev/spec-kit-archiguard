"""Run the checks of one pipeline entry and write their verdict files."""

from __future__ import annotations

import re
from typing import Dict, List

from .. import __version__
from ..common import ArchiGuardError, write_json
from ..verdict import BLOCKING, CheckResult, Finding
from . import a0, a3, a4, handover, plugged
from .context import GateContext
from .registry import ResolvedEntry

BUILTIN_CHECKS = {"A0": a0.CHECKS, "A3": a3.CHECKS, "A4": a4.CHECKS, "H": handover.CHECKS}


def run_entry(ctx: GateContext, entry: ResolvedEntry, *, write_verdicts: bool = True) -> List[CheckResult]:
    manifest = entry.manifest
    results: Dict[str, CheckResult] = {}
    for cid in entry.checks:
        spec = manifest.check(cid)
        results[cid] = CheckResult(gate=manifest.id, check=cid, name=spec.name, stage=spec.target,
                                   repairable=entry.repair and spec.repairable, mode=entry.mode)
    if manifest.protocol == "builtin":
        table = BUILTIN_CHECKS[manifest.id]
        for cid, res in results.items():
            fn = table.get(cid)
            if fn is None:
                res.error = f"{manifest.id} {cid} is not implemented by this archiGuard version"
                continue
            _guarded(fn, ctx, res)
    elif manifest.protocol == "scopeguard":
        for cid, res in results.items():
            _guarded(lambda c, r, _cid=cid: plugged.run_scopeguard(c, manifest, _cid, r), ctx, res)
            if cid == "plan" and not res.error:
                _deferral_references(ctx, res)
    else:
        try:
            plugged.run_external(ctx, manifest, list(results), results)
        except ArchiGuardError as exc:
            for res in results.values():
                res.error = str(exc)

    out = list(results.values())
    if write_verdicts and ctx.write and ctx.feature_dir is not None:
        pins = ctx.pins()
        commit, _ = ctx.head()
        for res in out:
            verdict = res.to_verdict(version=__version__, feature=ctx.feature, commit=commit, pins=pins,
                                     iteration=ctx.iteration, max_iterations=ctx.max_iterations)
            write_json(ctx.gates_dir / manifest.id / f"{res.check}.json", verdict)
    return out


def _guarded(fn, ctx: GateContext, res: CheckResult) -> None:
    try:
        fn(ctx, res)
    except ArchiGuardError as exc:
        res.error = str(exc)


def _deferral_references(ctx: GateContext, res: CheckResult) -> None:
    """Optional (decision 11): a scope deferral must cite an RFI or a decision-ledger entry."""
    if not ctx.cfg.option("scope", "require_deferral_reference", False):
        return
    pattern = re.compile(ctx.cfg.option("scope", "deferral_reference_pattern",
                                        r"\b(?:RFI|ADR|CLDD|SECD|DATD|WVR)-\d+\b"))
    for w in list(res.waived):
        if w.get("waiver") == "deferred" and not pattern.search(str(w.get("reason") or "")):
            res.waived.remove(w)
            res.add(Finding(rule=str(w["rule"]), severity=BLOCKING, where="plan.md",
                            message=f"{w['rule']} is deferred without an RFI or ledger reference ({w.get('reason') or 'no reason'})",
                            fix_hint="a scope deferral is a scope change: cite the RFI answered by the BA or the approved ledger entry"))

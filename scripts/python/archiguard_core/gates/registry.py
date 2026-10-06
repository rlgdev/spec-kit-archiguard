"""Gate manifests and the pipeline validation (the plug-in contract)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import yamlio
from ..common import ENGINE_ROOT, ArchiGuardError, version_satisfies

BUILTIN = ("A0", "A3", "A4", "H")
MANIFEST_TARGETS = ("spec", "plan", "contract", "tasks", "edit", "code", "tests")
PROTOCOLS = ("builtin", "scopeguard", "archiguard")


@dataclass
class CheckSpec:
    id: str
    name: str
    target: str
    repairable: bool = True
    checker: bool = True
    provided_by: Optional[str] = None
    native: Optional[str] = None


@dataclass
class GateManifest:
    id: str
    name: str
    version: str
    protocol: str
    checks: Dict[str, CheckSpec]
    source: str
    registration: Dict[str, Any] = field(default_factory=dict)

    def check(self, check_id: str) -> CheckSpec:
        if check_id not in self.checks:
            raise ArchiGuardError(
                f"gate {self.id} has no check {check_id!r} (available: {', '.join(self.checks)})"
            )
        return self.checks[check_id]


def _parse_manifest(data: Dict[str, Any], source: str, gate_id: str) -> GateManifest:
    if str(data.get("id", gate_id)) != gate_id:
        raise ArchiGuardError(f"{source}: manifest id {data.get('id')!r} does not match gate {gate_id!r}")
    protocol = str(data.get("protocol") or ("builtin" if data.get("implementation") == "builtin" else "archiguard"))
    if protocol not in PROTOCOLS:
        raise ArchiGuardError(f"{source}: protocol must be one of {', '.join(PROTOCOLS)}")
    raw_checks = data.get("checks") or {}
    if not isinstance(raw_checks, dict) or not raw_checks:
        raise ArchiGuardError(f"{source}: 'checks' must map check ids to {{name, target, repairable}}")
    checks: Dict[str, CheckSpec] = {}
    for cid, c in raw_checks.items():
        c = c or {}
        target = str(c.get("target") or "")
        if target not in MANIFEST_TARGETS:
            raise ArchiGuardError(f"{source}: check {cid}: target must be one of {', '.join(MANIFEST_TARGETS)}")
        checks[str(cid)] = CheckSpec(
            id=str(cid),
            name=str(c.get("name") or cid),
            target=target,
            repairable=bool(c.get("repairable", True)),
            checker=bool(c.get("checker", True)),
            provided_by=c.get("provided_by"),
            native=c.get("native"),
        )
    return GateManifest(id=gate_id, name=str(data.get("name") or gate_id), version=str(data.get("version") or "0"),
                        protocol=protocol, checks=checks, source=source)


def load_manifest(cfg: Any, gate_id: str) -> GateManifest:
    registry = cfg.gate_registry()
    reg = registry.get(gate_id) or {}
    if gate_id not in BUILTIN and gate_id not in registry:
        raise ArchiGuardError(
            f"gate {gate_id!r} is not registered - add it under 'gates:' in archiguard-config.yml "
            f"(built-in gates: {', '.join(BUILTIN)})"
        )
    if reg.get("manifest"):
        path = Path(str(reg["manifest"]))
        if not path.is_absolute():
            path = cfg.root / path
        data = yamlio.load_file(path)
        source = str(path)
    elif isinstance(reg.get("checks"), dict):
        data = {"id": gate_id, **reg}
        source = f"archiguard-config.yml gates.{gate_id}"
    else:
        path = ENGINE_ROOT / "manifests" / f"{gate_id}.yml"
        if not path.is_file():
            raise ArchiGuardError(f"no manifest for gate {gate_id!r} (expected {path} or gates.{gate_id}.manifest)")
        data = yamlio.load_file(path)
        source = str(path)
    manifest = _parse_manifest(data, source, gate_id)
    if gate_id in BUILTIN and manifest.protocol != "builtin":
        raise ArchiGuardError(f"{source}: {gate_id} is a built-in gate")
    manifest.registration = dict(reg)
    return manifest


@dataclass
class ResolvedEntry:
    gate: str
    checks: List[str]
    repair: bool
    mode: str
    manifest: GateManifest


def resolve_entry(cfg: Any, entry: Dict[str, Any], where: str = "pipeline") -> ResolvedEntry:
    manifest = load_manifest(cfg, entry["gate"])
    repairable_all = True
    for cid in entry["run"]:
        spec = manifest.check(cid)
        if spec.provided_by:
            g, _, c = spec.provided_by.partition(".")
            raise ArchiGuardError(
                f"{where}: {manifest.id} {cid} runs on another gate - plug {{ gate: {g}, run: [{c}] }} instead"
            )
        if spec.native:
            raise ArchiGuardError(f"{where}: {manifest.id} {cid} is native to Spec Kit ({spec.native}); nothing to plug")
        repairable_all = repairable_all and spec.repairable
    # repair omitted: each check follows its manifest (a non-repairable check escalates, the others loop);
    # repair: false turns repair off for every check of the entry; repair: true needs every check repairable.
    repair = entry.get("repair")
    if repair is True and not repairable_all:
        bad = [c for c in entry["run"] if not manifest.check(c).repairable]
        raise ArchiGuardError(
            f"{where}: {manifest.id} {', '.join(bad)} cannot be repaired by the agent - set repair: false"
        )
    return ResolvedEntry(gate=manifest.id, checks=list(entry["run"]), repair=repair is not False,
                         mode=entry.get("mode") or cfg["mode"], manifest=manifest)


def validate_pipeline(cfg: Any) -> None:
    for cmd, spec in cfg["pipeline"].items():
        for step_key in ("step_a", "step_b"):
            entries = spec[step_key] if step_key == "step_a" else spec[step_key]["gates"]
            for idx, entry in enumerate(entries, start=1):
                resolve_entry(cfg, entry, f"pipeline.{cmd}.{step_key}[{idx}]")
    for gid, reg in cfg.gate_registry().items():
        if gid in BUILTIN:
            raise ArchiGuardError(f"gates.{gid}: built-in gates need no registration")
        if reg.get("version") and not isinstance(reg.get("version"), str):
            raise ArchiGuardError(f"gates.{gid}.version must be a version range string such as '>=0.3.0,<0.5'")
        if reg.get("version"):
            version_satisfies("0", str(reg["version"]))  # syntax check only

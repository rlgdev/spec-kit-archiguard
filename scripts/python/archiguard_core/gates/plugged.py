"""Adapters for plugged-in gates: the scopeGuard engine and any gate that speaks the archiGuard protocol."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .. import yamlio
from ..common import ArchiGuardError, rel_path, sha256_file, version_satisfies
from ..verdict import ADVISORY, BLOCKING, CheckResult, Finding
from .context import GateContext
from .registry import GateManifest


def _command_path(ctx: GateContext, manifest: GateManifest) -> Path:
    reg = manifest.registration
    command = reg.get("command")
    if not command:
        raise ArchiGuardError(f"gates.{manifest.id}: 'command' is not set")
    path = Path(str(command))
    if path.is_absolute():
        return path
    if reg.get("extension"):
        return ctx.root / ".specify" / "extensions" / str(reg["extension"]) / path
    return ctx.root / path


def _installed_version(ctx: GateContext, manifest: GateManifest, script: Path) -> Optional[str]:
    reg = manifest.registration
    if reg.get("extension"):
        ext_yml = ctx.root / ".specify" / "extensions" / str(reg["extension"]) / "extension.yml"
        if ext_yml.is_file():
            data = yamlio.load_file(ext_yml)
            v = (data.get("extension") or {}).get("version")
            if v:
                return str(v)
    try:
        argv = [sys.executable, str(script)] if script.suffix == ".py" else [str(script)]
        proc = subprocess.run(argv + ["--version"], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (proc.stdout or proc.stderr).strip().split()
    return out[-1] if out else None


def _check_version(ctx: GateContext, manifest: GateManifest, script: Path) -> str:
    want = manifest.registration.get("version")
    have = _installed_version(ctx, manifest, script)
    if want and (have is None or not version_satisfies(have, str(want))):
        raise ArchiGuardError(
            f"gate {manifest.id}: installed version {have or 'unknown'} does not satisfy {want} "
            f"({rel_path(script, ctx.root)})"
        )
    pinned = manifest.registration.get("sha256")
    if pinned:
        actual = sha256_file(script)
        if (actual or "").lower() != str(pinned).strip().lower():
            raise ArchiGuardError(
                f"gate {manifest.id}: {rel_path(script, ctx.root)} has sha256 {actual}, the registration pins {pinned} "
                "- install the pinned release"
            )
    return have or "unknown"


def _script(ctx: GateContext, manifest: GateManifest) -> Path:
    script = _command_path(ctx, manifest)
    if not script.is_file():
        ext = manifest.registration.get("extension")
        hint = f" - install the {ext} extension" if ext else ""
        raise ArchiGuardError(f"gate {manifest.id}: {rel_path(script, ctx.root)} not found{hint}")
    return script


def _run(argv: List[str], cwd: Path, timeout: int = 600) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ArchiGuardError(f"{' '.join(argv[:3])} timed out after {timeout}s")
    except OSError as exc:
        raise ArchiGuardError(f"cannot run {argv[0]}: {exc}")
    return proc.returncode, proc.stdout, proc.stderr


# --------------------------------------------------------------------------- #
# scopeGuard                                                                    #
# --------------------------------------------------------------------------- #


def run_scopeguard(ctx: GateContext, manifest: GateManifest, check: str, res: CheckResult) -> None:
    script = _script(ctx, manifest)
    version = _check_version(ctx, manifest, script)
    res.data["engine"] = f"scopeguard {version}"
    if ctx.feature_dir is None:
        raise ArchiGuardError("the scope gate needs a feature directory")
    argv = [sys.executable, str(script), check, "--root", str(ctx.root), "--feature-dir", str(ctx.feature_dir)]
    cfg_file = manifest.registration.get("config")
    if cfg_file:
        p = Path(str(cfg_file))
        p = p if p.is_absolute() else ctx.root / p
        if p.is_file():
            argv += ["--config", str(p)]
    if check == "inventory":
        code, out, err = _run(argv, ctx.root)
        if code != 0:
            raise ArchiGuardError(f"scopeGuard inventory failed (exit {code}): {(err or out).strip()[:400]}")
        res.info = [line for line in out.rstrip().split("\n")]
        return
    code, out, err = _run(argv + ["--json"], ctx.root)
    try:
        payload = json.loads(out)
    except ValueError:
        raise ArchiGuardError(f"scopeGuard {check} returned no JSON (exit {code}): {(err or out).strip()[:400]}")
    if payload.get("verdict") == "error" or code == 2:
        raise ArchiGuardError(f"scopeGuard {check}: {payload.get('error') or err.strip()[:400]}")
    for gate in payload.get("gates") or []:
        res.data["summary"] = gate.get("summary")
        skeleton = gate.get("fix_skeleton") or []
        target = gate.get("fix_target")
        for item in gate.get("items") or []:
            verdict = item.get("verdict")
            if verdict == "violation":
                fix = next((row for row in skeleton if row.startswith(f"| {item.get('id')} |")), None)
                res.add(Finding(
                    rule=str(item.get("id")),
                    message=f"{item.get('id')} {item.get('title') or ''}: {item.get('detail')}",
                    where=item.get("location") or target,
                    fix_hint=(f"add to {target}: {fix}" if fix and target else None),
                    excerpt=item.get("spec_excerpt"),
                ))
            elif verdict == "waived":
                res.waive(str(item.get("id")), "deferred", None, reason=str(item.get("detail") or ""))
        for f in gate.get("findings") or []:
            # scopeGuard's own hint points at its preset; under archiGuard the archiguard-templates preset
            # carries the section, and installing scopeguard-templates as well would wrap the commands twice.
            message = str(f.get("message")).replace(
                "(install the scopeguard preset, or add the table shown below)",
                "(add it from the scope contract printed by step A; archiGuard's plan template carries the section)")
            res.add(Finding(rule=str(f.get("item") or "scope"), message=message,
                            severity=BLOCKING if f.get("level") == "violation" else ADVISORY,
                            where=f.get("location")))


# --------------------------------------------------------------------------- #
# Generic plug-in protocol                                                      #
# --------------------------------------------------------------------------- #


def run_external(ctx: GateContext, manifest: GateManifest, checks: List[str], results: Dict[str, CheckResult]) -> None:
    """Invoke `<command> <check...> --feature-dir <dir> --iteration N --config <file> --json` and read verdicts."""
    script = _script(ctx, manifest)
    _check_version(ctx, manifest, script)
    reg = manifest.registration
    argv = [sys.executable, str(script)] if script.suffix == ".py" else [str(script)]
    argv += list(checks)
    if ctx.feature_dir is not None:
        argv += ["--feature-dir", str(ctx.feature_dir)]
    if ctx.iteration is not None:
        argv += ["--iteration", str(ctx.iteration)]
    if reg.get("config"):
        p = Path(str(reg["config"]))
        argv += ["--config", str(p if p.is_absolute() else ctx.root / p)]
    argv.append("--json")
    code, out, err = _run(argv, ctx.root, timeout=int(reg.get("timeout") or 600))
    if code == 2:
        for c in checks:
            results[c].error = (err or out).strip()[:400] or f"{manifest.id} could not evaluate (exit 2)"
        return
    try:
        payload = json.loads(out)
    except ValueError:
        raise ArchiGuardError(f"gate {manifest.id} returned no JSON on stdout (exit {code})")
    verdicts = payload if isinstance(payload, list) else payload.get("verdicts", [payload])
    seen = set()
    for v in verdicts:
        cid = str(v.get("check") or (checks[0] if len(checks) == 1 else ""))
        if cid not in results:
            continue
        seen.add(cid)
        r = results[cid]
        if v.get("status") == "error":
            r.error = str(v.get("error") or "the gate could not evaluate")
            continue
        for f in v.get("findings") or []:
            r.add(Finding(rule=str(f.get("rule") or cid), message=str(f.get("message") or ""),
                          severity=BLOCKING if f.get("severity", BLOCKING) == BLOCKING else ADVISORY,
                          where=f.get("where"), fix_hint=f.get("fix_hint"), excerpt=f.get("excerpt")))
        for w in v.get("waived") or []:
            r.waive(str(w.get("rule")), str(w.get("waiver")), w.get("expires"))
        for s in v.get("rules_skipped") or []:
            r.skip(str(s.get("rule")), str(s.get("reason")))
    for c in checks:
        if c not in seen:
            results[c].error = f"gate {manifest.id} returned no verdict for {c}"
    if code == 3:
        # the gate escalated by itself: its red checks need a person, not another repair iteration
        for c in checks:
            if results[c].blocking:
                results[c].repairable = False

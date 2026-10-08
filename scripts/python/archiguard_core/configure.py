"""archiguard configure: apply the config to Spec Kit's hook registry and report what is in force."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import __version__, standards
from .common import EXTENSIONS_YML, ArchiGuardError, line_ending, read_text, rel_path, version_satisfies, write_text
from .config import COMMANDS, Config, short_command
from .ledger import Ledger
from .runner import effective_integration

HOOKS: Dict[Tuple[str, str], Tuple[str, str]] = {
    # (event, command) -> (Spec Kit command, kind)
    ("before_plan", "speckit.archiguard.planentry"): ("speckit.plan", "entry"),
    ("after_plan", "speckit.archiguard.plangate"): ("speckit.plan", "gate"),
    ("before_tasks", "speckit.archiguard.tasksentry"): ("speckit.tasks", "entry"),
    ("after_tasks", "speckit.archiguard.tasksgate"): ("speckit.tasks", "gate"),
    ("before_implement", "speckit.archiguard.implemententry"): ("speckit.implement", "entry"),
    ("after_implement", "speckit.archiguard.implementgate"): ("speckit.implement", "gate"),
}


def _scalar(value: str) -> str:
    return value.strip().strip("'\"")


def set_hook_flags(text: str, decide) -> Tuple[str, List[Dict[str, Any]]]:
    """Set `enabled:` on hook entries of .specify/extensions.yml, preserving the rest of the file.

    decide(extension, event, command) -> True / False to set, or None to leave the entry alone.
    """
    lines = text.split("\n")
    out: List[str] = []
    found: List[Dict[str, Any]] = []
    in_hooks = False
    event: Optional[str] = None
    i = 0
    while i < len(lines):
        line = lines[i]
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if stripped and indent == 0 and not stripped.startswith("#"):
            in_hooks = stripped == "hooks:"
            event = None
            out.append(line)
            i += 1
            continue
        item = re.match(r"^(\s*)-\s+(.*)$", line)
        if in_hooks and item is None:
            ev = re.match(r"^\s+([A-Za-z0-9_]+):\s*$", line)
            if ev:
                event = ev.group(1)
            out.append(line)
            i += 1
            continue
        if not (in_hooks and item and event):
            out.append(line)
            i += 1
            continue
        item_indent = len(item.group(1))
        block = [line]
        j = i + 1
        while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip(" ")) > item_indent):
            block.append(lines[j])
            j += 1
        fields: Dict[str, Tuple[int, str]] = {}
        for k, bline in enumerate(block):
            body = bline.strip()[2:] if k == 0 else bline.strip()
            m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", body)
            if m and (k == 0 or len(bline) - len(bline.lstrip(" ")) == item_indent + 2):
                fields[m.group(1)] = (k, m.group(2))
        ext = _scalar(fields.get("extension", (0, ""))[1])
        cmd = _scalar(fields.get("command", (0, ""))[1])
        want = decide(ext, event, cmd)
        if want is not None:
            current = _scalar(fields["enabled"][1]).lower() not in ("false", "no", "off") if "enabled" in fields else True
            value = "true" if want else "false"
            if "enabled" in fields:
                k = fields["enabled"][0]
                if k == 0:
                    block[0] = re.sub(r"enabled:\s*\S+", f"enabled: {value}", block[0])
                else:
                    prefix = block[k][: len(block[k]) - len(block[k].lstrip(" "))]
                    block[k] = f"{prefix}enabled: {value}"
            else:
                block.insert(1, " " * (item_indent + 2) + f"enabled: {value}")
            found.append({"extension": ext, "event": event, "command": cmd, "was": current, "now": want})
        out.extend(block)
        i = j
    return "\n".join(out), found


def scope_in_pipeline(cfg: Config) -> bool:
    for command in COMMANDS:
        for step in ("a", "b"):
            if any(e["gate"] == "scope" for e in cfg.step_entries(command, step)):
                return True
    return False


def run_configure(root: Path, cfg: Config, dry_run: bool) -> Tuple[str, Dict[str, Any]]:
    eff, note = effective_integration(root, cfg)
    uses_scope = scope_in_pipeline(cfg)

    def decide(ext: str, event: str, cmd: str) -> Optional[bool]:
        if ext == "archiguard":
            key = (event, cmd)
            if key not in HOOKS:
                return None
            command, kind = HOOKS[key]
            has_a = bool(cfg.step_entries(command, "a"))
            has_b = bool(cfg.step_entries(command, "b"))
            if eff != "hooks":
                return False
            return (has_a or has_b) if kind == "entry" else has_b
        if ext == "scopeguard" and uses_scope:
            return False  # archiGuard runs the scope gate itself; scopeGuard's own hooks would run it twice
        return None

    ext_yml = root / EXTENSIONS_YML
    found: List[Dict[str, Any]] = []
    if ext_yml.is_file():
        original = read_text(ext_yml)
        updated, found = set_hook_flags(original, decide)
        changed = [f for f in found if f["was"] != f["now"]]
        if changed and not dry_run:
            try:
                import yaml  # type: ignore

                yaml.safe_load(updated)
            except ImportError:
                pass
            except Exception as exc:  # noqa: BLE001 - any parser error means: do not write
                raise ArchiGuardError(f"refusing to write {EXTENSIONS_YML}: the result would not parse ({exc})")
            write_text(ext_yml, updated.replace("\n", line_ending(ext_yml)))
    else:
        changed = []

    lines = [
        f"archiGuard {__version__} | configure{' (dry run)' if dry_run else ''}",
        f"config: {', '.join(rel_path(Path(s), root) if not s.startswith('env ') else s for s in cfg.sources) or 'built-in defaults'}",
        "",
        f"  integration   : {cfg['integration']}" + (f" -> running as '{eff}'" if eff != cfg["integration"] else ""),
        f"  mode          : {cfg['mode']}",
        f"  ceiling       : {cfg.ceiling} iteration(s) per step ({cfg.policy['source']})",
    ]
    for command in COMMANDS:
        a = cfg.step_entries(command, "a")
        b = cfg.step_entries(command, "b")
        if not a and not b:
            lines.append(f"  {short_command(command):<13} : no gates plugged")
            continue
        fmt = lambda es: ", ".join(f"{e['gate']}[{' '.join(e['run'])}]" + (f" ({e['mode']})" if e.get("mode") else "")
                                   + (" no-repair" if e.get("repair") is False else "") for e in es) or "-"
        lines.append(f"  {short_command(command):<13} : step A {fmt(a)}")
        lines.append(f"  {'':<13}   step B {fmt(b)} | budget {cfg.budget(command)}")
    loops = cfg.get("loops") or {}
    lines.append(f"  loops         : {', '.join(f'{k} {v}' for k, v in loops.items()) or '-'}")
    lines.append("")
    if eff == "inline":
        lines.append("  The gates run as steps A and B inside /speckit.plan, /speckit.tasks and /speckit.implement.")
    else:
        lines.append("  The gates run as separate archiGuard commands from Spec Kit's hooks.")
    if note:
        lines.append(f"  NOTE: {note}. Install it: specify preset add --from <archiguard-preset.zip>")
    if found:
        lines.append("")
        lines.append("  Hooks in .specify/extensions.yml:")
        for f in found:
            change = "" if f["was"] == f["now"] else f"   (was {'on' if f['was'] else 'off'})"
            lines.append(f"    {f['extension']:<11} {f['event']:<17} {f['command']:<34} {'on' if f['now'] else 'off'}{change}")
        lines.append(f"  {len(changed)} hook setting(s) {'would change' if dry_run else 'changed'}.")
    elif not ext_yml.is_file():
        lines.append(f"  NOTE: {EXTENSIONS_YML.as_posix()} not found - is the archiguard extension installed here?")

    # scopeGuard
    readiness: Dict[str, Any] = {}
    if uses_scope:
        reg = (cfg.gate_registry().get("scope") or {})
        ext = reg.get("extension") or "scopeguard"
        sg_yml = root / ".specify" / "extensions" / ext / "extension.yml"
        lines.append("")
        if sg_yml.is_file():
            from . import yamlio

            version = str((yamlio.load_file(sg_yml).get("extension") or {}).get("version"))
            lines.append(f"  scope gate    : {ext} {version} (required {reg.get('version') or 'any'}); its own hooks are switched off")
            readiness["scopeguard"] = version
            if ext == "scopeguard" and version_satisfies(version, ">=0.4.0"):
                sg_cfg = root / ".specify" / "extensions" / ext / "scopeguard-config.yml"
                integration = None
                if sg_cfg.is_file():
                    try:
                        integration = (yamlio.load_file(sg_cfg) or {}).get("integration")
                    except ArchiGuardError:
                        integration = None
                if integration != "embedded":
                    lines.append("  NOTE          : set 'integration: embedded' in .specify/extensions/scopeguard/scopeguard-config.yml, "
                                 "so scopeGuard's own configure keeps its hooks off as well")
                readiness["scopeguard_integration"] = integration
        else:
            lines.append(f"  scope gate    : MISSING - install the {ext} extension (the scope gate exits 2 until then)")
            readiness["scopeguard"] = None
        if (root / ".specify" / "presets" / "scopeguard-templates").is_dir():
            lines.append("  WARNING       : the scopeguard-templates preset is installed - it wraps /speckit.plan and /speckit.tasks a "
                         "second time. Remove it: specify preset remove scopeguard-templates")
            readiness["scopeguard_preset"] = True

    # policy readiness
    lines.append("")
    lines.append("  Policy:")
    st = cfg["standards"]
    rb_path = cfg.path("standards", "path")
    lock_path = cfg.path("standards", "lock")
    if not st.get("rulebook"):
        lines.append("    rulebook      : not configured (standards.rulebook) - A3.1 / A3.3 / A4.4 exit 2")
    else:
        lines.append(f"    rulebook      : {st['rulebook']} at {rel_path(rb_path, root) if rb_path else '-'}"
                     + ("" if rb_path and rb_path.is_dir() else "  (MISSING - check out the standards repository)"))
    if lock_path and lock_path.is_file():
        try:
            lock = standards.read_lock(lock_path)
            stale = standards.lock_is_current(lock, cfg)
            lines.append(f"    lock          : {rel_path(lock_path, root)} - {len(lock.get('rules') or [])} rule(s)"
                         + (f"  (STALE: {stale})" if stale else ""))
        except ArchiGuardError as exc:
            lines.append(f"    lock          : {exc}")
    else:
        lines.append(f"    lock          : missing - run 'archiguard resolve' and commit {rel_path(lock_path, root) if lock_path else 'the lock'}")
    dm_path = cfg.path("domain", "map")
    pin = cfg["domain"].get("pin")
    lines.append(f"    domain map    : {rel_path(dm_path, root) if dm_path else '-'}"
                 + ("" if dm_path and dm_path.is_file() else "  (MISSING - A0 exits 2)")
                 + (f", pinned at {pin}" if pin else ", not pinned (domain.pin)"))
    ledger = Ledger.load(cfg.path("ledger", "path"))
    lines.append(f"    ledger        : {len(ledger.entries)} entr{'y' if len(ledger.entries) == 1 else 'ies'}"
                 + ("" if ledger.intact else f"  (BROKEN: {ledger.problems[0].message})"))
    settings = root / ".claude" / "settings.json"
    guard = settings.is_file() and "speckit.archiguard.editguard" in read_text(settings)
    lines.append(f"    edit guard    : {'wired into .claude/settings.json' if guard else 'not wired (Claude Code events appear after specify extension add)'}")
    for n in cfg.notes:
        lines.append(f"  NOTE: {n}")

    data = {
        "tool": "archiguard", "version": __version__, "command": "configure", "dry_run": dry_run,
        "integration": cfg["integration"], "effective_integration": eff, "note": note,
        "hooks": found, "changed": len(changed), "scope_in_pipeline": uses_scope, "readiness": readiness,
    }
    return "\n".join(lines), data

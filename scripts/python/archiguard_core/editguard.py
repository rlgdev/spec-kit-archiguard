"""A4.2 edit guard: a Claude Code PreToolUse / PostToolUse hook (wired through Spec Kit `events:`).

Edits: blocks read-only artefacts (PreToolUse) and reports rule violations of the edited file (PostToolUse).
Shell commands: blocks the archiGuard subcommands reserved for people (sign-off, re-open, ledger, resolve).

Convenience, never the guarantee: on any setup problem it stays silent and lets the edit through
(exit 0). The workflow shell gate and the CI required check are the guarantee.

Exit 2 + a message on stderr = PreToolUse: the edit is blocked; PostToolUse: the message goes back to the agent.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import standards
from .common import ArchiGuardError, GATES_DIRNAME, glob_match, read_text
from .config import load_config
from .gates.context import GateContext

CONTENT_KINDS = ("forbid_text", "forbid_import", "layers", "context_boundaries")
SHELL_TOOLS = ("Bash", "PowerShell")


def _feature_of(rel: str, root: Path) -> Optional[Path]:
    m = re.match(r"^specs/([^/]+)/", rel)
    if m and (root / "specs" / m.group(1)).is_dir():
        return root / "specs" / m.group(1)
    return None


def readonly_violation(root: Path, cfg: Any, rel: str, rules: List[Dict[str, Any]]) -> Optional[str]:
    eg = cfg["edit_guard"]
    if glob_match(rel, eg.get("always_readonly") or []):
        return (f"{rel} is policy, archiGuard configuration or gate evidence and is read-only for agents - "
                "changes go through a pull request reviewed by a person")
    feature = _feature_of(rel, root)
    if feature is not None:
        if (feature / cfg["feature"]["handover"]).is_file() and glob_match(rel, eg.get("after_handover") or []):
            return f"{rel} came from the formal handover and is read-only - specification changes go to the BA as an RFI"
        if (feature / GATES_DIRNAME / "signoff.json").is_file() and glob_match(rel, eg.get("after_signoff") or []):
            return (f"{rel} is part of the design signed off by the design authority and is read-only during Implement "
                    "- a design change goes back to Design for a new sign-off")
    for rule in rules:
        for chk in standards.checks_for(rule, ("edit",)):
            if chk.get("kind") == "readonly" and glob_match(rel, _as_list(chk.get("files"))):
                return f"{rel} is read-only under {rule['id']} {rule.get('title') or ''}".rstrip()
    return None


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _rules(ctx: GateContext) -> List[Dict[str, Any]]:
    lock = ctx.lock
    by_id = {r["id"]: r for r in lock.get("rules") or []}
    if ctx.feature_dir is not None:
        cached = ctx.feature_dir / GATES_DIRNAME / "applicable-rules.json"
        if cached.is_file():
            try:
                data = json.loads(read_text(cached))
                if data.get("lock") == standards.lock_hash(lock):
                    return [by_id[r["id"]] for r in data.get("rules") or [] if r.get("id") in by_id]
            except ValueError:
                pass
    rules, _ = ctx.applicable
    return rules


_INVOCATION = re.compile(r"archiguard(?:\.sh|\.ps1|\.py)?\b(?![-_/\\])")
_SEGMENT_END = re.compile(r"[;&|\n]|\)\s*$")


def human_only_command(command: str, human_only: List[str]) -> Optional[str]:
    """The archiGuard subcommand reserved for people that a shell command would run, if any."""
    wanted = {tuple(h.split()) for h in human_only}
    for m in _INVOCATION.finditer(command):
        rest = _SEGMENT_END.split(command[m.end():], maxsplit=1)[0]
        try:
            tokens = shlex.split(rest, posix=True)
        except ValueError:
            tokens = rest.split()
        words = [t for t in tokens if not t.startswith("-")]
        if not words:
            continue
        sub = words[0]
        if sub == "resolve" and "--check" in tokens:
            continue
        candidates = [(sub,)] + ([(sub, words[1])] if len(words) > 1 else [])
        for cand in candidates:
            if cand in wanted:
                return " ".join(cand)
    return None


def _shell_guard(payload: Dict[str, Any], root: Path, config_path: Optional[str]) -> Tuple[int, str]:
    if str(payload.get("hook_event_name") or "") != "PreToolUse":
        return 0, ""
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if "archiguard" not in command:
        return 0, ""
    try:
        cfg = load_config(root, config_path)
    except ArchiGuardError:
        return 0, ""
    eg = cfg["edit_guard"]
    if not eg.get("enabled", True):
        return 0, ""
    sub = human_only_command(command, eg.get("human_only") or [])
    if sub:
        return 2, (f"archiGuard edit guard (blocked): 'archiguard {sub}' records a decision of a person (a sign-off, an "
                   "approval, a waiver or the standards lock). Ask the user to run it; an agent never runs it.")
    return 0, ""


def run(stdin_text: str, root: Path, config_path: Optional[str] = None) -> Tuple[int, str]:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except ValueError:
        return 0, ""
    if str(payload.get("tool_name") or "") in SHELL_TOOLS:
        return _shell_guard(payload, root, config_path)
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or payload.get("file_path")
    if not file_path:
        return 0, ""
    path = Path(str(file_path))
    if not path.is_absolute():
        path = Path(str(payload.get("cwd") or root)) / path
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return 0, ""
    event = str(payload.get("hook_event_name") or "")
    try:
        cfg = load_config(root, config_path)
        if not cfg["edit_guard"].get("enabled", True):
            return 0, ""
        feature_dir = _feature_of(rel, root)
        if feature_dir is None:
            from .common import resolve_feature_dir
            try:
                feature_dir = resolve_feature_dir(root)
            except ArchiGuardError:
                feature_dir = None
        ctx = GateContext(root, cfg, feature_dir, write=False)
        try:
            rules = _rules(ctx)
        except ArchiGuardError:
            rules = []
        problem = readonly_violation(root, cfg, rel, rules)
        if problem:
            verb = "blocked" if event == "PreToolUse" else "revert this edit"
            return 2, f"archiGuard edit guard ({verb}): {problem}."
        if event == "PreToolUse" or not path.is_file():
            return 0, ""
        messages: List[str] = []
        evaluator = ctx.evaluator
        for rule in rules:
            for chk in standards.checks_for(rule, ("edit",)):
                if chk.get("kind") not in CONTENT_KINDS:
                    continue
                for f in evaluator.run(rule, chk, only_files=[rel]):
                    messages.append(f"- {f.rule}: {f.message}" + (f" ({f.where})" if f.where else "")
                                    + (f" -> {f.fix_hint}" if f.fix_hint else ""))
        if messages:
            return 2, ("archiGuard edit guard: this edit breaks architecture rules - fix it now:\n" + "\n".join(messages))
        return 0, ""
    except ArchiGuardError:
        return 0, ""  # fail open: the workflow gate and CI are the guarantee


def main_from_stdin(root: Path, config_path: Optional[str] = None) -> int:
    data = sys.stdin.read() if not sys.stdin.isatty() else ""
    code, message = run(data, root, config_path)
    if message:
        print(message, file=sys.stderr)
    return code

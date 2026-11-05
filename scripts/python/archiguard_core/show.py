"""archiguard show: the setup in force and the skills of the rulebook it binds, read-only.

The first part is what `configure` reports (integration, mode, the gates plugged into each command, budgets, the
hooks, the policy files), without writing anything. The second part lists the skills: every skill of the
rulebook with a rule in the standards lock (the lock is what the gates and the agent read), with its SKILL.md,
its rules and why each rule is selected; then the skills of the rulebook the lock leaves out, the excluded rules,
and whether the lock still equals what 'archiguard resolve' would write.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import standards, yamlio
from .common import ArchiGuardError, read_text, rel_path, today
from .config import Config
from .configure import run_configure
from .ledger import Ledger

_FRONT_MATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)


def skill_description(path: Path) -> Optional[str]:
    """The `description:` of a SKILL.md front matter, on one line; None when there is none."""
    try:
        m = _FRONT_MATTER.match(read_text(path))
        data = yamlio.loads(m.group(1), str(path)) if m else None
    except ArchiGuardError:
        return None
    if isinstance(data, dict) and data.get("description"):
        return " ".join(str(data["description"]).split())
    return None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _preview_lock(cfg: Config) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """What 'archiguard resolve' would write now, in memory; (None, reason) when it cannot resolve."""
    from .commands import _domain_map_optional

    try:
        ledger = Ledger.load(cfg.path("ledger", "path"))
        return standards.resolve(cfg, ledger, _domain_map_optional(cfg), today(ci=cfg.ci)), None
    except ArchiGuardError as exc:
        return None, str(exc)


def _conditions(rule: Dict[str, Any], stacks: List[str]) -> List[str]:
    aw = rule.get("applies_when") or {}
    out = []
    rstacks = [str(s) for s in aw.get("stack") or []]
    if rstacks:
        out.append(f"stack {', '.join(rstacks)}" + ("" if set(rstacks) & set(stacks) else " - not detected here"))
    rctx = [str(c) for c in aw.get("contexts") or []]
    if rctx:
        out.append(f"context {', '.join(rctx)}")
    return out


def skills_report(root: Path, cfg: Config, verbose: bool = False) -> Tuple[List[str], Dict[str, Any]]:
    st = cfg["standards"]
    rb_path = cfg.path("standards", "path")
    lock_path = cfg.path("standards", "lock")
    notes: List[str] = []

    rulebook: Optional[standards.Rulebook] = None
    if rb_path is not None and rb_path.is_dir():
        try:
            rulebook = standards.load_rulebook(rb_path)
        except ArchiGuardError as exc:
            notes.append(f"the rulebook cannot be read: {exc}")
    elif st.get("rulebook"):
        notes.append(f"the rulebook is not checked out at {rel_path(rb_path, root) if rb_path else '-'} - "
                     "the skills' SKILL.md files cannot be read")

    lock: Optional[Dict[str, Any]] = None
    stale: Optional[str] = None
    lock_error: Optional[str] = None
    if lock_path is not None and lock_path.is_file():
        try:
            lock = standards.read_lock(lock_path)
            stale = standards.lock_is_current(lock, cfg)
        except ArchiGuardError as exc:
            lock_error = str(exc)
            notes.append(lock_error)

    markers = (lock or {}).get("stacks") or (rulebook.stacks if rulebook else standards.DEFAULT_STACK_MARKERS)
    stacks = standards.detect_stacks(root, markers, cfg["stack"])

    # the rules of every skill in the rulebook, to tell a partly selected skill and the skills left out
    rulebook_rules: Dict[str, List[str]] = {}
    if rulebook is not None:
        for rid, rule in sorted(rulebook.rules.items()):
            rulebook_rules.setdefault(rule["skill"], []).append(rid)

    in_force: Dict[str, Dict[str, Any]] = {}
    for rule in (lock or {}).get("rules") or []:
        skill = str(rule.get("skill") or "-")
        entry = in_force.setdefault(skill, {"skill": skill, "skill_md": None, "skill_md_exists": None,
                                            "description": None, "rules_in_rulebook": None, "rules_not_in_force": None,
                                            "rules": []})
        if rule.get("skill_path") and entry["skill_md"] is None and rb_path is not None:
            md = rb_path / str(rule["skill_path"])
            entry["skill_md"] = rel_path(md, root)
            if rulebook is not None:
                entry["skill_md_exists"] = md.is_file()
                entry["description"] = skill_description(md) if md.is_file() else None
        entry["rules"].append({
            "id": rule.get("id"), "title": rule.get("title"), "level": rule.get("level"),
            "targets": list(rule.get("targets") or []), "check": rule.get("check"),
            "sources": list(rule.get("sources") or []), "applies_when": rule.get("applies_when") or {},
            "conditions": _conditions(rule, stacks), "text": rule.get("text"),
            "kinds": [f"{c.get('target')}:{c.get('kind')}" for c in rule.get("checks") or [] if isinstance(c, dict)],
        })
    for skill, entry in in_force.items():
        if rulebook is not None:
            entry["rules_in_rulebook"] = len(rulebook_rules.get(skill, []))
            selected = {r["id"] for r in entry["rules"]}
            entry["rules_not_in_force"] = [rid for rid in rulebook_rules.get(skill, []) if rid not in selected]

    excluded = (lock or {}).get("excluded") or []
    excluded_ids = {str(e.get("rule")) for e in excluded}
    not_in_force = [
        {"skill": skill, "rules": len(rids), "excluded": [rid for rid in rids if rid in excluded_ids],
         "description": skill_description(rulebook.path / "skills" / skill / "SKILL.md")}
        for skill, rids in sorted(rulebook_rules.items()) if skill not in in_force
    ] if rulebook is not None else []

    preview, preview_error = _preview_lock(cfg) if st.get("rulebook") and rulebook is not None else (None, None)
    drift: Optional[List[str]] = None
    if lock is not None and preview is not None:
        drift = standards.diff_locks(lock, preview)

    # ---- text -------------------------------------------------------------- #
    lines = ["", "  Skills:"]
    stack_source = "detected" if cfg["stack"] == "auto" else "configured"
    lines.append(f"    stacks        : {', '.join(stacks) or 'none'} ({stack_source})")
    would_select = sorted({r["skill"] for r in preview["rules"]}) if lock is None and preview is not None else None
    if lock is None and not st.get("rulebook"):
        lines.append("    in force      : none - no rulebook is bound (standards.rulebook); bind one, then run "
                     "'archiguard resolve' and commit the lock")
    elif lock is None and lock_error:
        lines.append("    in force      : none - the standards lock cannot be read (see the NOTE below); "
                     "'archiguard resolve' writes it again")
    elif lock is None:
        lines.append("    in force      : none - the gates and the agent read the skills from the standards lock, "
                     "and there is none: run 'archiguard resolve' and commit it")
    else:
        rb = lock.get("rulebook") or {}
        cfg_lock = lock.get("config") or {}
        origin = [f"{rb.get('name')}@{rb.get('tag')}"]
        if cfg_lock.get("profile"):
            origin.append(f"profile {cfg_lock['profile']}")
        packs = sorted({p for ps in ((lock.get("domain_map") or {}).get("packs") or {}).values() for p in ps})
        if packs:
            origin.append(f"{'pack' if len(packs) == 1 else 'packs'} {', '.join(packs)}")
        if cfg_lock.get("include"):
            origin.append(f"include {', '.join(cfg_lock['include'])}")
        total = sum(len(e["rules"]) for e in in_force.values())
        lines.append(f"    in force      : {_plural(len(in_force), 'skill')}, {_plural(total, 'rule')} from "
                     f"{rel_path(lock_path, root)} ({'; '.join(origin)})")
        if stale:
            lines.append(f"    STALE         : {stale}; the gates refuse this lock until then")
        shares = {}
        for skill, entry in in_force.items():
            count, of = len(entry["rules"]), entry["rules_in_rulebook"]
            shares[skill] = f"{count} of {_plural(of, 'rule')}" if of is not None and of != count else _plural(count, "rule")
        width = max([len(v) for v in shares.values()] + [8])
        for skill in sorted(in_force):
            entry = in_force[skill]
            where = entry["skill_md"] or "no SKILL.md"
            if entry["skill_md_exists"] is False:
                where += "  (MISSING in the checkout - the agent is told to read it)"
            lines.append("")
            lines.append(f"    {skill:<22} {shares[skill]:<{width}}  {where}")
            if entry["description"]:
                lines.append(f"      {entry['description']}")
            for r in entry["rules"]:
                detail = [", ".join(r["targets"]) or "plan",
                          "declared check" if r["check"] == "declared" else "agent judgement",
                          "via " + ", ".join(r["sources"])] + r["conditions"]
                lines.append(f"      {str(r['id']):<10} {str(r['level']):<6} {r['title']}  [{' · '.join(detail)}]")
                if verbose:
                    if r["text"]:
                        lines.append(f"{'':<24}{' '.join(str(r['text']).split())}")
                    if r["kinds"]:
                        lines.append(f"{'':<24}checks: {', '.join(r['kinds'])}")
            if entry.get("rules_not_in_force"):
                lines.append("      not selected: " + ", ".join(
                    rid + (" (excluded)" if rid in excluded_ids else "") for rid in entry["rules_not_in_force"]))
    if rulebook is not None and lock is None:
        lines.append("")
        if would_select is not None:
            lines.append(f"    available     : {_plural(len(not_in_force), 'skill')} in {rulebook.name or 'the rulebook'}; "
                         f"'archiguard resolve' would put {_plural(len(preview['rules']), 'rule')} of the "
                         f"{len(would_select)} marked * in force")
        else:
            lines.append(f"    available     : {_plural(len(not_in_force), 'skill')} in {rulebook.name or 'the rulebook'}; "
                         f"'archiguard resolve' cannot run: {preview_error or 'standards.rulebook is not set'}")
        for s in not_in_force:
            mark = "*" if would_select and s["skill"] in would_select else " "
            lines.append(f"    {mark} {s['skill']:<20} {_plural(s['rules'], 'rule'):<10} {s['description'] or ''}".rstrip())
    elif rulebook is not None:
        lines.append("")
        if not_in_force:
            lines.append(f"    not in force  : {_plural(len(not_in_force), 'skill')} of {rulebook.name or 'the rulebook'} "
                         "with no rule in the lock (not selected by the profile, a pack or include, or excluded)")
            for s in not_in_force:
                why = f"[excluded: {', '.join(s['excluded'])}] " if s["excluded"] else ""
                lines.append(f"      {s['skill']:<20} {_plural(s['rules'], 'rule'):<10} {why}{s['description'] or ''}".rstrip())
        else:
            lines.append(f"    not in force  : none - every skill of {rulebook.name or 'the rulebook'} has a rule in force")
    if excluded:
        lines.append("    excluded      : " + "; ".join(
            f"{e.get('rule')} ({e.get('level')})" + (f" waiver {e['waiver']}" if e.get("waiver") else "")
            + (f" until {e['expires']}" if e.get("expires") and e.get("expires") != "None" else "") for e in excluded))
    if lock is not None:
        if drift is None:
            if preview_error:
                reason = preview_error
            elif rulebook is None:
                reason = "the rulebook cannot be read" if rb_path is not None and rb_path.is_dir() else "the rulebook is not checked out"
            else:
                reason = "standards.rulebook is not set"
            lines.append(f"    rulebook drift: not checked - {reason}")
        elif drift:
            lines.append(f"    rulebook drift: {', '.join(drift)} - run 'archiguard resolve', review the change and "
                         "commit the lock (CI fails until then)")
        else:
            lines.append("    rulebook drift: none - the lock equals what 'archiguard resolve' would write now")
    for n in notes:
        lines.append(f"    NOTE: {n}")

    data = {
        "lock": rel_path(lock_path, root) if lock is not None and lock_path is not None else None,
        "stale": stale,
        "rulebook": (f"{(lock.get('rulebook') or {}).get('name')}@{(lock.get('rulebook') or {}).get('tag')}"
                     if lock is not None else st.get("rulebook")),
        "stacks": stacks,
        "in_force": [in_force[s] for s in sorted(in_force)],
        "not_in_force": not_in_force,
        "excluded": excluded,
        "drift": drift,
        "would_select": would_select,
        "notes": notes,
    }
    return lines, data


def run_show(root: Path, cfg: Config, verbose: bool = False) -> Tuple[str, Dict[str, Any]]:
    text, data = run_configure(root, cfg, dry_run=True, show=True)
    lines, skills = skills_report(root, cfg, verbose)
    data["skills"] = skills
    return text + "\n" + "\n".join(lines), data

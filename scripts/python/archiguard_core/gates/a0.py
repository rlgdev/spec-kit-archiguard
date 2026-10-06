"""A0 - domain guard."""

from __future__ import annotations

import json
import re
from typing import List, Optional

from ..common import (
    ArchiGuardError,
    column_index,
    find_section,
    is_placeholder,
    read_text,
    rel_path,
    strip_html_comments,
    tables_in,
    write_json,
)
from ..verdict import ADVISORY, CheckResult, Finding
from .context import GateContext


def check_a0_1(ctx: GateContext, res: CheckResult) -> None:
    """Pin check: the feature declares domain-map@<version>; released; equals the repository pin; not moved."""
    h = ctx.require_handover()
    dm = ctx.require_domain_map()
    pin = ctx.cfg["domain"].get("pin")
    if pin is None or str(pin).strip() == "":
        raise ArchiGuardError("domain.pin is not set in archiguard-config.yml - the domain map version must be pinned")
    pin = str(pin)
    declared = h.map_version
    where = rel_path(h.path, ctx.root)
    if not declared:
        res.add(Finding(rule="A0.1", where=where,
                        message="the feature does not declare the domain map version it was specified against (domain.map_version)",
                        fix_hint="the formal handover must stamp domain.map_version from the context map (MAP) of the specification"))
    released, why = dm.released()
    if not released:
        res.add(Finding(rule="A0.1", where=rel_path(dm.path, ctx.root),
                        message=f"domain map {dm.version}: {why} - only a released domain map can be pinned",
                        fix_hint="the lead architect releases the domain master design"))
    if dm.version != pin:
        res.add(Finding(rule="A0.1", where=rel_path(dm.path, ctx.root),
                        message=f"the domain map is version {dm.version}, the repository pins {pin}",
                        fix_hint="check out the pinned domain map, or move the pin through a reviewed change"))
    if declared and declared != pin:
        res.add(Finding(rule="A0.1", where=where,
                        message=f"the feature was specified against domain-map@{declared}, the repository pins {pin}",
                        fix_hint="re-run the handover against the pinned domain map (RFI to the BA), or move the pin"))
    signed = ((ctx.signoff or {}).get("pins") or {}).get("domain_map")
    last_green = ctx.gates_dir / ".state" / "A0.1-last-green.json"
    if signed and signed != dm.version:
        res.add(Finding(rule="A0.1", where=rel_path(dm.path, ctx.root),
                        message=f"the domain map moved from {signed} to {dm.version} after the design authority sign-off",
                        fix_hint="re-open Design (archiguard reopen), re-run the gates against the new map and sign again"))
    elif not signed and last_green.is_file():
        try:
            old = json.loads(read_text(last_green)).get("domain_map")
        except ValueError:
            old = None
        if old and old != dm.version:
            res.add(Finding(rule="A0.1", severity=ADVISORY, where=rel_path(dm.path, ctx.root),
                            message=f"the domain map moved from {old} to {dm.version} since the last green A0.1; "
                                    f"re-evaluated against {dm.version}"))
    res.data["domain_map"] = {"version": dm.version, "pin": pin, "declared": declared}
    if ctx.write and not res.blocking:
        write_json(last_green, {"domain_map": dm.version})


def check_a0_2(ctx: GateContext, res: CheckResult) -> None:
    """Home context: exactly one, it exists in the map, every SC / AC / BR in scope inherits it."""
    h = ctx.require_handover()
    dm = ctx.require_domain_map()
    where = rel_path(h.path, ctx.root)
    home, problems = h.home_context()
    for p in problems:
        res.add(Finding(rule="A0.2", where=where, message=p,
                        fix_hint="a tagging error goes to the BA as an RFI; a real domain change to the lead architect"))
    if home is None:
        return
    if home not in dm.contexts:
        res.add(Finding(rule="A0.2", where=where,
                        message=f"home context '{home}' does not exist in domain map {dm.version}",
                        fix_hint=f"contexts in the map: {', '.join(sorted(dm.contexts))}"))
        return
    for item, ctx_name in h.items.items():
        if not re.match(r"^(SC|AC|BR)-\d+$", item):
            continue
        value = ctx_name.get("context") if isinstance(ctx_name, dict) else ctx_name
        if value and str(value) != home:
            res.add(Finding(rule="A0.2", where=where,
                            message=f"{item} is tagged with context '{value}' but the feature's home context is '{home}'",
                            fix_hint="every scenario, criterion and rule inherits the Use Case's home context"))
    res.data["home_context"] = home


def check_a0_3(ctx: GateContext, res: CheckResult) -> None:
    """Entity ownership: each data node is owned by the home context or reached through an allowed relation."""
    h = ctx.require_handover()
    dm = ctx.require_domain_map()
    where = rel_path(h.path, ctx.root)
    home, problems = h.home_context()
    if home is None or home not in dm.contexts:
        res.add(Finding(rule="A0.3", where=where, message="no valid home context - entity ownership cannot be judged (see A0.2)"))
        return
    for node, info in sorted(h.data_nodes.items()):
        entity = str(info.get("entity") or "") if isinstance(info, dict) else str(info)
        owner = info.get("context") if isinstance(info, dict) else None
        owner = str(owner) if owner else (dm.owner_of_entity(entity) if entity else None)
        if owner is None:
            res.add(Finding(rule="A0.3", where=where,
                            message=f"{node} {entity or '(no entity name)'}: no context in domain map {dm.version} owns this entity",
                            fix_hint="the domain model must own every entity (RFI to the BA / domain change to the lead architect)"))
            continue
        if owner not in dm.contexts:
            res.add(Finding(rule="A0.3", where=where, message=f"{node} {entity}: owner context '{owner}' is not in the domain map"))
            continue
        declared_owner = dm.owner_of_entity(entity) if entity else None
        if declared_owner and declared_owner != owner:
            res.add(Finding(rule="A0.3", where=where,
                            message=f"{node} {entity}: tagged with context '{owner}' but the domain map says '{declared_owner}' owns it"))
            continue
        if owner != home and dm.allows(home, owner) is None:
            res.add(Finding(rule="A0.3", where=where,
                            message=f"{node} {entity} is owned by '{owner}' and '{home}' has no relation to it in the domain map",
                            fix_hint=f"reach {entity} through an allowed relation {home} -> {owner}, or propose one (domain change)"))


_SUFFIXES_DEFAULT = ["Request", "Response", "Dto", "DTO", "Event", "Command", "Id", "Entity", "Model"]


def _norm(term: str) -> str:
    return re.sub(r"[^a-z0-9]", "", term.lower())


def _entity_names(ctx: GateContext) -> List[tuple]:
    names: List[tuple] = []
    dm_path = ctx.feature_file("data-model.md")
    if dm_path.is_file():
        text = strip_html_comments(read_text(dm_path))
        for no, line in enumerate(text.split("\n"), start=1):
            m = re.match(r"^###\s+(.*)$", line)
            if m:
                name = re.sub(r"[`*_]", "", m.group(1))
                name = re.sub(r"\(.*?\)", "", name)
                name = re.sub(r"^\d+[.)]\s*", "", name)
                name = re.sub(r"^(Entity|Aggregate|Value Object)\s*[:\-]\s*", "", name, flags=re.I).strip()
                name = re.sub(r"\s*(entity|aggregate)$", "", name, flags=re.I).strip()
                if name and len(name) <= 60:
                    names.append((name, f"data-model.md:{no}"))
    contracts = ctx.feature_file("contracts")
    if contracts.is_dir():
        from .. import yamlio
        for path in sorted(contracts.rglob("*")):
            if path.suffix.lower() not in (".yaml", ".yml", ".json") or not path.is_file():
                continue
            try:
                raw = read_text(path)
                doc = json.loads(raw) if path.suffix.lower() == ".json" else yamlio.loads(raw, str(path))
            except (ValueError, ArchiGuardError):
                continue
            schemas = ((doc or {}).get("components") or {}).get("schemas") if isinstance(doc, dict) else None
            if isinstance(schemas, dict):
                for name in schemas:
                    names.append((str(name), rel_path(path, ctx.feature_dir)))
    return names


def check_a0_4(ctx: GateContext, res: CheckResult) -> None:
    """Vocabulary: key entity and contract names are glossary terms of the home context (or declared synonyms)."""
    h = ctx.require_handover()
    dm = ctx.require_domain_map()
    home, _ = h.home_context()
    if home is None or home not in dm.contexts:
        raise ArchiGuardError("A0.4 needs a valid home context (run A0.2 first)")
    vocab = {_norm(t) for t in dm.vocabulary(home)}
    suffixes = ctx.cfg.option("A0.4", "strip_suffixes", _SUFFIXES_DEFAULT) or []
    for name, where in _entity_names(ctx):
        candidates = {_norm(name)}
        base = name
        for suffix in suffixes:
            if base.endswith(suffix) and len(base) > len(suffix):
                base = base[: -len(suffix)]
                candidates.add(_norm(base))
        for c in list(candidates):
            if c.endswith("s") and len(c) > 3:
                candidates.add(c[:-1])
        if not candidates & vocab:
            res.add(Finding(rule="A0.4", where=where,
                            message=f"'{name}' is not a term of context '{home}' (glossary, owned entities, synonyms) or of a related context",
                            fix_hint=f"use the ubiquitous language of '{home}': {', '.join(sorted(dm.contexts[home].glossary)[:12])}"))


_NONE_WORDS = {"none", "n/a", "na"}


def _plan_mentions(text: str, name: str) -> Optional[int]:
    rx = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(name) + r"(?![A-Za-z0-9_-])", re.I)
    for no, line in enumerate(text.split("\n"), start=1):
        if rx.search(line):
            return no
    return None


def check_a0_5(ctx: GateContext, res: CheckResult) -> None:
    """Relations in the plan: every integration point names a target context and an allowed relation type."""
    h = ctx.require_handover()
    dm = ctx.require_domain_map()
    home, _ = h.home_context()
    if home is None or home not in dm.contexts:
        raise ArchiGuardError("A0.5 needs a valid home context (run A0.2 first)")
    plan = strip_html_comments(ctx.require_file("plan.md"))
    title = ctx.cfg.option("A0.5", "section", "Integration Points")
    sec = find_section(plan, re.escape(title))
    if sec is None:
        res.add(Finding(rule="A0.5", where="plan.md",
                        message=f"plan.md has no '## {title}' section",
                        fix_hint=f"add '## {title}' with a table | Integration point | Target context | Relation | Via | "
                                 "(one row per integration; a single row 'none' when the feature has none)"))
        return
    tables = tables_in(sec.lines, sec.start + 1)
    declared = set()
    if not tables:
        body = " ".join(l.strip() for l in sec.lines if l.strip())
        if not re.search(r"\bnone\b", body, re.I):
            res.add(Finding(rule="A0.5", where=f"plan.md:{sec.start}",
                            message=f"'{title}' has no table", fix_hint="add the table, or write 'None' when there are no integrations"))
    for table in tables:
        if not table.rows:
            res.add(Finding(rule="A0.5", where=f"plan.md:{table.line}",
                            message=f"the '{title}' table is empty",
                            fix_hint="add one row per integration with another context, or a single row | none | - | - | -"))
            continue
        c_target = column_index(table.header, "target", "context")
        c_rel = column_index(table.header, "relation", "type")
        c_point = column_index(table.header, "integration", "point", "interface")
        if c_target is None or c_rel is None:
            res.add(Finding(rule="A0.5", where=f"plan.md:{table.line}",
                            message="the integration table needs 'Target context' and 'Relation' columns"))
            continue
        for line, cells in table.rows:
            def cell(i):
                return cells[i].strip() if i is not None and i < len(cells) else ""
            point, target, rel = cell(c_point), cell(c_target), cell(c_rel)
            if point.lower() in _NONE_WORDS or target.lower() in _NONE_WORDS or (is_placeholder(point) and is_placeholder(target)):
                continue
            if is_placeholder(target):
                res.add(Finding(rule="A0.5", where=f"plan.md:{line}", message=f"integration '{point}' names no target context"))
                continue
            if target not in dm.contexts:
                res.add(Finding(rule="A0.5", where=f"plan.md:{line}",
                                message=f"integration '{point}': '{target}' is not a context of the domain map",
                                fix_hint=f"contexts: {', '.join(sorted(dm.contexts))}"))
                continue
            declared.add(target)
            if target == home:
                continue
            relations = dm.relations_between(home, target)
            types = sorted({r.type for r in relations if r.type != "separate-ways"})
            if not types:
                res.add(Finding(rule="A0.5", where=f"plan.md:{line}",
                                message=f"integration '{point}': the domain map has no relation between '{home}' and '{target}'",
                                fix_hint="remove the integration or propose the relation to the lead architect (domain change)"))
            elif is_placeholder(rel) or rel not in types:
                res.add(Finding(rule="A0.5", where=f"plan.md:{line}",
                                message=f"integration '{point}': relation '{rel or '-'}' is not allowed; the map allows {', '.join(types)} between '{home}' and '{target}'",
                                fix_hint=f"name the relation type from the domain map: {', '.join(types)}"))
    # advisory: other contexts mentioned in the plan but not declared as integrations
    for name in sorted(dm.contexts):
        if name == home or name in declared or len(name) < 4:
            continue
        line = _plan_mentions(plan, name)
        if line is not None:
            res.add(Finding(rule="A0.5", severity=ADVISORY, where=f"plan.md:{line}",
                            message=f"plan.md mentions context '{name}' but '{title}' does not declare an integration with it"))


CHECKS = {
    "A0.1": check_a0_1,
    "A0.2": check_a0_2,
    "A0.3": check_a0_3,
    "A0.4": check_a0_4,
    "A0.5": check_a0_5,
}

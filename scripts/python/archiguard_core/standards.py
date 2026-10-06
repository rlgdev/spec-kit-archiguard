"""Architecture standards as skills: the rulebook, profiles, packs, the lock and the applicable rules.

Rulebook layout (a pinned checkout of the standards repository, e.g. a git submodule):

    rulebook.yml                 name, version (= tag), optional stack markers and N/A reasons
    skills/<skill>/SKILL.md      the guidance the agent reads
    skills/<skill>/rules.yml     ARCH-### rules declared as data (checks with target + kind)
    profiles/<name>.yml          a named rule set per stack, owned centrally
    packs/<name>.yml             rules a domain-map context pulls in (contexts.<c>.packs)
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import yamlio
from .common import (
    DEFAULT_SCAN_EXCLUDES,
    ArchiGuardError,
    canonical_json,
    git,
    glob_match,
    read_text,
    sha256_json,
    sha256_text,
    walk_files,
)

RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
LEVELS = ("must", "should")
TARGETS = ("plan", "contract", "tasks", "edit", "code", "runtime")
TARGET_GATE = {"plan": "A3.3", "contract": "A3.3", "tasks": "A3.5", "edit": "A4.2", "code": "A4.4", "runtime": "A7"}

KIND_TARGETS: Dict[str, Tuple[str, ...]] = {
    "require_file": ("plan", "contract", "tasks", "code"),
    "require_text": ("plan", "contract", "tasks", "code"),
    "forbid_text": ("plan", "contract", "tasks", "code", "edit"),
    "require_section": ("plan", "contract", "tasks"),
    "require_task": ("tasks",),
    "forbid_import": ("code", "edit"),
    "layers": ("code", "edit"),
    "context_boundaries": ("code", "edit"),
    "contract_routes": ("code",),
    "readonly": ("edit",),
    "command": ("plan", "contract", "tasks", "code"),
}

DEFAULT_STACK_MARKERS: Dict[str, List[str]] = {
    "java": ["pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"],
    "node": ["package.json"],
    "python": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"],
    "dotnet": ["*.csproj", "*.sln", "*.fsproj"],
    "go": ["go.mod"],
    "cobol": ["**/*.cbl", "**/*.cob", "**/*.CBL", "**/*.COB"],
}

DEFAULT_NA_REASONS = [
    "no-persistence", "no-external-interface", "no-ui", "no-messaging", "no-batch",
    "read-only", "no-personal-data", "no-new-component", "out-of-context",
]

LOCK_VERSION = 1


@dataclass
class Rulebook:
    path: Path
    name: str
    version: str
    stacks: Dict[str, List[str]]
    na_reasons: List[str]
    rules: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    packs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    problems: List[str] = field(default_factory=list)

    def own_repository(self) -> bool:
        """True when the rulebook is its own git checkout (submodule or clone), not a folder of the project."""
        code, out = git(self.path, "rev-parse", "--show-toplevel")
        if code != 0:
            return False
        try:
            return Path(out.strip()).resolve() == self.path.resolve()
        except OSError:
            return False

    def commit(self) -> Optional[str]:
        if not self.own_repository():
            return None
        code, out = git(self.path, "rev-parse", "HEAD")
        return out.strip() if code == 0 else None

    def tags_at_head(self) -> List[str]:
        if not self.own_repository():
            return []
        code, out = git(self.path, "tag", "--points-at", "HEAD")
        return [t.strip() for t in out.split("\n") if t.strip()] if code == 0 else []


# --------------------------------------------------------------------------- #
# Loading and validation (also: archiguard validate-standards)                  #
# --------------------------------------------------------------------------- #


def load_rulebook(path: Path) -> Rulebook:
    if not path.is_dir():
        raise ArchiGuardError(
            f"rulebook not found at {path} - check out the standards repository at the pinned tag "
            "(standards.path in archiguard-config.yml)"
        )
    meta_path = path / "rulebook.yml"
    if not meta_path.is_file():
        raise ArchiGuardError(f"{meta_path} not found - is {path} a standards repository?")
    meta = yamlio.load_file(meta_path)
    stacks = copy.deepcopy(DEFAULT_STACK_MARKERS)
    for name, markers in (meta.get("stacks") or {}).items():
        stacks[str(name)] = [str(m) for m in (markers or [])]
    rb = Rulebook(
        path=path,
        name=str(meta.get("name") or ""),
        version=str(meta.get("version") or ""),
        stacks=stacks,
        na_reasons=[str(r) for r in (meta.get("not_applicable_reasons") or DEFAULT_NA_REASONS)],
    )
    if not rb.name:
        rb.problems.append("rulebook.yml: name is missing")
    if not rb.version:
        rb.problems.append("rulebook.yml: version is missing")

    skills_dir = path / "skills"
    rule_files = sorted(p for p in skills_dir.rglob("*") if p.is_file() and (p.name == "rules.yml" or p.name.endswith(".rules.yml"))) if skills_dir.is_dir() else []
    for rf in rule_files:
        skill_dir = rf.parent
        skill = skill_dir.relative_to(skills_dir).as_posix()
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            rb.problems.append(f"{rf.relative_to(path).as_posix()}: no SKILL.md next to the rules")
        data = yamlio.load_file(rf)
        rules = data.get("rules") or []
        if not isinstance(rules, list):
            rb.problems.append(f"{rf.relative_to(path).as_posix()}: 'rules' must be a list")
            continue
        for raw in rules:
            if not isinstance(raw, dict):
                rb.problems.append(f"{rf.relative_to(path).as_posix()}: every rule must be a mapping")
                continue
            rid = str(raw.get("id") or "")
            rule = copy.deepcopy(raw)
            rule["id"] = rid
            rule["skill"] = skill
            rule["skill_path"] = skill_md.relative_to(path).as_posix() if skill_md.is_file() else None
            rule["_file"] = rf.relative_to(path).as_posix()
            rule["_skill_text"] = read_text(skill_md) if skill_md.is_file() else ""
            if rid in rb.rules:
                rb.problems.append(f"{rule['_file']}: duplicate rule id {rid} (also in {rb.rules[rid]['_file']})")
                continue
            rb.rules[rid] = rule
            rb.problems.extend(f"{rule['_file']}: {rid or '<no id>'}: {p}" for p in validate_rule(rule))

    for kind, store in (("profiles", rb.profiles), ("packs", rb.packs)):
        d = path / kind
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.y*ml")):
            data = yamlio.load_file(f)
            name = str(data.get("profile" if kind == "profiles" else "pack") or data.get("name") or f.stem)
            data["_file"] = f.relative_to(path).as_posix()
            if name in store:
                rb.problems.append(f"{data['_file']}: duplicate {kind[:-1]} {name}")
            store[name] = data
    for kind, store in (("profile", rb.profiles), ("pack", rb.packs)):
        for name, data in store.items():
            for rid in _str_list(data.get("rules")):
                if rid not in rb.rules:
                    rb.problems.append(f"{data['_file']}: {kind} {name} lists unknown rule {rid}")
            for skill in _str_list(data.get("skills")):
                if not any(r["skill"] == skill for r in rb.rules.values()):
                    rb.problems.append(f"{data['_file']}: {kind} {name} lists skill {skill} that declares no rules")
            for parent in _str_list(data.get("extends")):
                if parent not in store:
                    rb.problems.append(f"{data['_file']}: {kind} {name} extends unknown {kind} {parent}")
    return rb


def _str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def rule_targets(rule: Dict[str, Any]) -> List[str]:
    targets = _str_list(rule.get("targets") or rule.get("target"))
    for chk in rule.get("checks") or []:
        if isinstance(chk, dict) and chk.get("target") and str(chk["target"]) not in targets:
            targets.append(str(chk["target"]))
    return targets or ["plan"]


def validate_rule(rule: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    rid = rule.get("id") or ""
    if not RULE_ID_RE.match(rid):
        errors.append("id must look like ARCH-101")
    if not rule.get("title"):
        errors.append("title is missing")
    if rule.get("level") not in LEVELS:
        errors.append(f"level must be one of {', '.join(LEVELS)} (got {rule.get('level')!r})")
    for t in _str_list(rule.get("targets") or rule.get("target")):
        if t not in TARGETS:
            errors.append(f"target {t!r} must be one of {', '.join(TARGETS)}")
    aw = rule.get("applies_when") or {}
    if not isinstance(aw, dict):
        errors.append("applies_when must be a mapping with stack / contexts")
    else:
        unknown = set(aw) - {"stack", "contexts"}
        if unknown:
            errors.append(f"applies_when: unknown key(s) {sorted(unknown)}")
    checks = rule.get("checks") or []
    if not isinstance(checks, list):
        errors.append("checks must be a list")
        return errors
    for idx, chk in enumerate(checks, start=1):
        errors.extend(f"check {idx}: {e}" for e in validate_check(chk))
    return errors


def validate_check(chk: Any) -> List[str]:
    if not isinstance(chk, dict):
        return ["must be a mapping with target and kind"]
    errors: List[str] = []
    target, kind = chk.get("target"), chk.get("kind")
    if target not in TARGETS:
        errors.append(f"target {target!r} must be one of {', '.join(TARGETS)}")
    if target == "runtime":
        return errors  # runtime checks are the Architecture Assessor's (A7); not run by archiGuard
    if kind not in KIND_TARGETS:
        errors.append(f"kind {kind!r} must be one of {', '.join(sorted(KIND_TARGETS))}")
        return errors
    if target in TARGETS and target not in KIND_TARGETS[kind]:
        errors.append(f"kind {kind} cannot run on target {target} (allowed: {', '.join(KIND_TARGETS[kind])})")

    def _regex(key: str, required: bool = True) -> None:
        val = chk.get(key)
        if val is None:
            if required:
                errors.append(f"{kind} needs '{key}'")
            return
        for v in _str_list(val):
            try:
                re.compile(v)
            except re.error as exc:
                errors.append(f"{key} {v!r} is not a valid regular expression: {exc}")

    def _list(key: str, required: bool = True) -> None:
        val = chk.get(key)
        if val is None:
            if required:
                errors.append(f"{kind} needs '{key}' (a list)")
            return
        if not isinstance(val, (list, str)):
            errors.append(f"{key} must be a list")

    if kind in ("require_file", "readonly"):
        _list("files")
    elif kind in ("require_text", "forbid_text"):
        _list("files")
        _regex("pattern")
        if chk.get("mode") not in (None, "any", "each"):
            errors.append("mode must be 'any' or 'each'")
    elif kind == "require_section":
        _regex("heading")
    elif kind == "require_task":
        _regex("pattern", required=False)
    elif kind == "forbid_import":
        _list("files", required=False)
        _list("imports")
        _regex("imports")
    elif kind == "layers":
        layers = chk.get("layers")
        if not isinstance(layers, list) or not layers:
            errors.append("layers needs a non-empty 'layers' list of {name, files, modules}")
        else:
            names = set()
            for layer in layers:
                if not isinstance(layer, dict) or not layer.get("name"):
                    errors.append("every layer needs a 'name'")
                    continue
                names.add(str(layer["name"]))
                for v in _str_list(layer.get("modules")):
                    try:
                        re.compile(v)
                    except re.error as exc:
                        errors.append(f"layer {layer['name']}: module pattern {v!r}: {exc}")
            if chk.get("scope") not in (None, "all", "context"):
                errors.append("layers scope must be 'all' or 'context'")
            allow = chk.get("allow") or {}
            if not isinstance(allow, dict):
                errors.append("allow must map a layer to the layers it may depend on")
            else:
                for src, dsts in allow.items():
                    for name in [str(src)] + _str_list(dsts):
                        if name not in names:
                            errors.append(f"allow names unknown layer {name}")
    elif kind == "contract_routes":
        _list("sources")
    elif kind == "command":
        run = chk.get("run")
        if not run or not isinstance(run, (str, list)):
            errors.append("command needs 'run' (an argv list, or a string with shell: true)")
        if isinstance(run, str) and not chk.get("shell"):
            errors.append("a string 'run' needs shell: true (or use an argv list)")
    return errors


# --------------------------------------------------------------------------- #
# Stack detection                                                               #
# --------------------------------------------------------------------------- #


def detect_stacks(root: Path, markers: Dict[str, List[str]], configured: Any = "auto") -> List[str]:
    if configured != "auto":
        return sorted(set(str(s) for s in configured))
    shallow: List[str] = []
    deep_needed = any("**" in m or "/" in m for ms in markers.values() for m in ms)
    for current_depth_path in _shallow_files(root, depth=2):
        shallow.append(current_depth_path)
    deep: Optional[List[str]] = None
    found: Set[str] = set()
    for stack, ms in markers.items():
        for marker in ms:
            if "**" in marker or "/" in marker:
                if deep is None and deep_needed:
                    deep = list(walk_files(root))
                if deep and any(glob_match(f, [marker]) for f in deep):
                    found.add(stack)
                    break
            else:
                if any(glob_match(f.rsplit("/", 1)[-1], [marker]) for f in shallow):
                    found.add(stack)
                    break
    return sorted(found)


def _shallow_files(root: Path, depth: int) -> List[str]:
    out: List[str] = []
    excluded = set(DEFAULT_SCAN_EXCLUDES)

    def _walk(d: Path, rel: str, level: int) -> None:
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for e in entries:
            r = f"{rel}/{e.name}" if rel else e.name
            if e.is_file():
                out.append(r)
            elif e.is_dir() and level < depth and e.name not in excluded:
                _walk(e, r, level + 1)

    _walk(root, "", 0)
    return out


# --------------------------------------------------------------------------- #
# Resolve -> standards.lock.yml                                                 #
# --------------------------------------------------------------------------- #


def rule_hash(rule: Dict[str, Any]) -> str:
    declared = {k: v for k, v in rule.items() if not k.startswith("_") and k not in ("skill_path",)}
    return "sha256:" + sha256_text(canonical_json(declared) + "\n" + rule.get("_skill_text", ""))


def _expand(store: Dict[str, Dict[str, Any]], name: str, rb: Rulebook, kind: str, seen: Optional[Set[str]] = None) -> List[str]:
    seen = seen or set()
    if name in seen:
        raise ArchiGuardError(f"{kind} {name} extends itself (cycle)")
    seen.add(name)
    data = store.get(name)
    if data is None:
        raise ArchiGuardError(f"{kind} {name!r} is not defined in the rulebook ({kind}s/{name}.yml)")
    ids: List[str] = []
    for parent in _str_list(data.get("extends")):
        ids.extend(_expand(store, parent, rb, kind, seen))
    for skill in _str_list(data.get("skills")):
        ids.extend(sorted(rid for rid, r in rb.rules.items() if r["skill"] == skill))
    ids.extend(_str_list(data.get("rules")))
    for rid in _str_list(data.get("exclude")):
        while rid in ids:
            ids.remove(rid)
    out: List[str] = []
    for rid in ids:
        if rid not in out:
            out.append(rid)
    return out


def resolve(cfg: Any, ledger: Any, domain_map: Any, today: Any) -> Dict[str, Any]:
    """Resolve the project's standards into lock data (deterministic, no timestamps)."""
    from . import __version__

    st = cfg["standards"]
    if not st.get("rulebook"):
        raise ArchiGuardError("standards.rulebook is not set in archiguard-config.yml (e.g. acme-standards@v2026.10.1)")
    name, _, tag = str(st["rulebook"]).partition("@")
    path = cfg.path("standards", "path")
    rb = load_rulebook(path)
    if rb.problems:
        raise ArchiGuardError(
            f"the rulebook at {path} is not valid ({len(rb.problems)} problem(s)); first: {rb.problems[0]} "
            "- run 'archiguard validate-standards' for the full list"
        )
    if rb.name != name:
        raise ArchiGuardError(f"rulebook at {path} is '{rb.name}', the config pins '{name}'")
    tags = rb.tags_at_head()
    if rb.version != tag and tag not in tags:
        raise ArchiGuardError(
            f"rulebook at {path} is version {rb.version or '?'} (tags at HEAD: {', '.join(tags) or 'none'}); "
            f"the config pins {tag} - check out the pinned tag"
        )

    selected: Dict[str, List[str]] = {}

    def _add(rid: str, source: str) -> None:
        if rid not in rb.rules:
            raise ArchiGuardError(f"{source} names unknown rule {rid}")
        selected.setdefault(rid, [])
        if source not in selected[rid]:
            selected[rid].append(source)

    if st.get("profile"):
        for rid in _expand(rb.profiles, str(st["profile"]), rb, "profile"):
            _add(rid, f"profile:{st['profile']}")
    for rid in st.get("include") or []:
        _add(rid, "include")

    pack_contexts: Dict[str, List[str]] = {}
    packs_by_context: Dict[str, List[str]] = {}
    if domain_map is not None:
        for cname, ctx in sorted(domain_map.contexts.items()):
            if not ctx.packs:
                continue
            packs_by_context[cname] = list(ctx.packs)
            for pack in ctx.packs:
                for rid in _expand(rb.packs, pack, rb, "pack"):
                    _add(rid, f"pack:{pack}")
                    pack_contexts.setdefault(rid, [])
                    if cname not in pack_contexts[rid]:
                        pack_contexts[rid].append(cname)

    excluded = []
    for ex in st.get("exclude") or []:
        rid = ex["rule"]
        if rid not in rb.rules:
            raise ArchiGuardError(f"standards.exclude names unknown rule {rid}")
        rule = rb.rules[rid]
        entry: Dict[str, Any] = {"rule": rid, "level": rule.get("level")}
        if rule.get("level") == "must":
            if not ex.get("waiver"):
                raise ArchiGuardError(f"excluding the must rule {rid} needs a ledger waiver (standards.exclude: {{rule: {rid}, waiver: ADR-…}})")
            problem = ledger.check_entry(ex["waiver"], today, rid)
            if problem:
                raise ArchiGuardError(f"excluding {rid}: {problem}")
            entry["waiver"] = ex["waiver"]
            entry["expires"] = str((ledger.get(ex["waiver"]) or {}).get("expires"))
        elif ex.get("waiver"):
            entry["waiver"] = ex["waiver"]
        excluded.append(entry)
        selected.pop(rid, None)

    rules_out = []
    for rid in sorted(selected):
        rule = rb.rules[rid]
        aw = rule.get("applies_when") or {}
        own_contexts = _str_list(aw.get("contexts"))
        sources = selected[rid]
        only_packs = all(s.startswith("pack:") for s in sources)
        contexts = own_contexts
        if only_packs:
            pcs = pack_contexts.get(rid, [])
            contexts = [c for c in pcs if not own_contexts or c in own_contexts] if own_contexts else pcs
        checks = [c for c in (rule.get("checks") or []) if isinstance(c, dict)]
        executable = [c for c in checks if c.get("target") != "runtime"]
        rules_out.append({
            "id": rid,
            "title": rule.get("title"),
            "level": rule.get("level"),
            "skill": rule["skill"],
            "skill_path": rule.get("skill_path"),
            "targets": rule_targets(rule),
            "check": "declared" if executable else "judgement",
            "applies_when": {"stack": _str_list(aw.get("stack")), "contexts": sorted(contexts)},
            "sources": sources,
            "text": rule.get("text"),
            "checks": checks,
            "hash": rule_hash(rule),
        })

    lock = {
        "lock_version": LOCK_VERSION,
        "archiguard": __version__,
        "rulebook": {"name": rb.name, "tag": tag, "version": rb.version, "commit": rb.commit(),
                     "path": str(st.get("path"))},
        "config": {
            "rulebook": st["rulebook"],
            "profile": st.get("profile"),
            "include": list(st.get("include") or []),
            "exclude": [{"rule": e["rule"], "waiver": e.get("waiver")} for e in st.get("exclude") or []],
        },
        "domain_map": {
            "version": domain_map.version if domain_map is not None else None,
            "packs": packs_by_context,
        },
        "stacks": rb.stacks,
        "not_applicable_reasons": rb.na_reasons,
        "excluded": excluded,
        "rules": rules_out,
    }
    return lock


def lock_hash(lock: Dict[str, Any]) -> str:
    return "sha256:" + sha256_json(lock)


def read_lock(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.is_file():
        raise ArchiGuardError(
            f"standards lock not found ({path}) - run 'archiguard resolve' and commit standards.lock.yml"
        )
    data = yamlio.load_file(path)
    if data.get("lock_version") != LOCK_VERSION:
        raise ArchiGuardError(f"{path}: unsupported lock_version {data.get('lock_version')!r}")
    return data


def write_lock(path: Path, lock: Dict[str, Any]) -> None:
    header = (
        "# standards.lock.yml - generated by 'archiguard resolve'. Do not edit by hand.\n"
        "# Commit it: the agent, every checker and CI read the rules from here; CI re-resolves and fails on drift.\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(header + yamlio.dumps(lock))


def lock_is_current(lock: Dict[str, Any], cfg: Any) -> Optional[str]:
    """Cheap staleness check without the rulebook: the config the lock was resolved from must match."""
    st = cfg["standards"]
    want = {
        "rulebook": st.get("rulebook"),
        "profile": st.get("profile"),
        "include": list(st.get("include") or []),
        "exclude": [{"rule": e["rule"], "waiver": e.get("waiver")} for e in st.get("exclude") or []],
    }
    have = lock.get("config") or {}
    if canonical_json(want) != canonical_json(have):
        return "the standards section of archiguard-config.yml changed since the lock was resolved - run 'archiguard resolve'"
    return None


def diff_locks(old: Dict[str, Any], new: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for key in ("rulebook", "config", "domain_map", "excluded", "not_applicable_reasons", "stacks"):
        if canonical_json(old.get(key)) != canonical_json(new.get(key)):
            out.append(f"{key} changed")
    old_rules = {r["id"]: r for r in old.get("rules") or []}
    new_rules = {r["id"]: r for r in new.get("rules") or []}
    for rid in sorted(set(old_rules) | set(new_rules)):
        if rid not in old_rules:
            out.append(f"{rid} added")
        elif rid not in new_rules:
            out.append(f"{rid} removed")
        elif canonical_json(old_rules[rid]) != canonical_json(new_rules[rid]):
            out.append(f"{rid} changed")
    return out


def applicable_rules(lock: Dict[str, Any], stacks: Sequence[str], home_context: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """(rules that apply to this feature, rules filtered out with the reason)."""
    out, skipped = [], []
    for rule in lock.get("rules") or []:
        aw = rule.get("applies_when") or {}
        rstacks = aw.get("stack") or []
        if rstacks and not set(rstacks) & set(stacks):
            skipped.append({"rule": rule["id"], "reason": f"stack {', '.join(rstacks)} not in this repository ({', '.join(stacks) or 'none detected'})"})
            continue
        rctx = aw.get("contexts") or []
        if rctx and home_context not in rctx:
            skipped.append({"rule": rule["id"], "reason": f"applies to context(s) {', '.join(rctx)}; home context is {home_context or 'unknown'}"})
            continue
        out.append(rule)
    return out, skipped


def checks_for(rule: Dict[str, Any], targets: Sequence[str]) -> List[Dict[str, Any]]:
    return [c for c in rule.get("checks") or [] if c.get("target") in targets]

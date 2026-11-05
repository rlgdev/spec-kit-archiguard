"""Loop feedback to the domain master design (loop step 0): evidence after coding, never a gate.

After coding, the feedback compares what the feature did - the files changed on its branch - with the domain map
and writes ``gates/loop-feedback.json`` (authoritative) and ``gates/loop-feedback.md`` (the view): code no context
maps, new build units, a topology the map does not declare, cross-context changes, dependencies the map does not
allow, terms outside the glossary and gaps in the map. Every item carries a short suggestion for the next
iteration, the person it is for and the artefact the fix belongs in (docs/loop-feedback.md).

It is evidence, not a gate: it never changes an exit code, a verdict, the iteration state or an escalation, and a
failure to compute it is recorded in the file and printed as one line. It only reads - git, globs, the domain map,
the handover record, the lock, the ledger and the plan, through archiGuard's read-only analyses - and never runs a
gate check, a build or a test.
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import os
import posixpath
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import __version__
from .codeanalysis import EXT_LANG, extract_imports, language_of, resolve_relative
from .common import (
    DEFAULT_SCAN_EXCLUDES,
    GATES_DIRNAME,
    ArchiGuardError,
    canonical_json,
    git,
    glob_match,
    read_text,
    rel_path,
    sha256_file,
    sha256_text,
    strip_html_comments,
    write_json,
    write_text,
)
from .config import FEEDBACK_KINDS

FEEDBACK_JSON = "loop-feedback.json"
FEEDBACK_MD = "loop-feedback.md"
SCHEMA = 1
IMPACTS = ("high", "medium", "low")
VOLATILE = ("computed_at", "computed_by", "commit")     # never a reason to rewrite the file (write-if-changed)
MAX_OCCURRENCES = 25
MAX_RESOLVED = 50
UNMAPPED = "(unmapped)"
NO_UNIT = "(none)"
LEDGER_ID = re.compile(r"\b(?:ADR|CLDD|SECD|DATD|WVR|WAIVER)-\d+\b")

COMPUTED_BY = {
    "implement-b": "after implement step B",
    "handover-4-5": "at handover 4 -> 5",
    "report": "with the compliance report",
    "cli": "by archiguard feedback",
    "ci": "in CI",
}
LEAD = {"role": "lead architect"}
TECH_LEAD = {"role": "tech lead"}


# --------------------------------------------------------------------------- #
# Small helpers                                                                 #
# --------------------------------------------------------------------------- #


def item_id(kind: str, subject: str, digits: int = 8) -> str:
    """LF- + the first hex digits of sha256("<kind>\\n<subject>"): feature-independent, stable across runs."""
    return "LF-" + sha256_text(f"{kind}\n{subject}")[:digits]


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _norm(term: str) -> str:
    return re.sub(r"[^a-z0-9]", "", term.lower())


def _owner(dm: Any, context: str) -> Dict[str, Any]:
    c = dm.contexts.get(context)
    out: Dict[str, Any] = {"role": "domain owner", "context": context}
    if c is not None and c.owner:
        out["name"] = str(c.owner)
    return out


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _agree(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


def _join(items: Sequence[str], empty: str = "-") -> str:
    items = list(items)
    return ", ".join(items) if items else empty


def _literal_depth(glob: str) -> int:
    """Number of leading path segments of a glob without a wildcard (src/main/java/com/acme/orders/** -> 6)."""
    depth = 0
    for part in glob.replace("\\", "/").strip("/").split("/"):
        if not part or any(ch in part for ch in "*?[{"):
            break
        depth += 1
    return depth


def _group_depth(dm: Any, fb: Dict[str, Any]) -> int:
    if fb["group_depth"] != "auto":
        return int(fb["group_depth"])
    depths = [d for c in dm.contexts.values() for d in (_literal_depth(g) for g in c.code) if d > 0]
    if not depths:
        return 2
    counts = Counter(depths)
    best = max(counts.values())
    return min(d for d, n in counts.items() if n == best)


def _module_prefix(spec: str, resolved: Optional[str], file_rel: str) -> str:
    """The package / namespace an import names (the import without its last segment)."""
    if resolved is not None:
        return posixpath.dirname(resolved) or "."
    lang = language_of(file_rel)
    if lang in ("csharp", "go", "cobol"):
        return spec
    if spec.endswith(".*"):
        return spec[:-2]
    if lang == "js" or "/" in spec:
        return posixpath.dirname(spec) or spec
    return spec.rsplit(".", 1)[0] if "." in spec else spec


# --------------------------------------------------------------------------- #
# What the feature changed                                                      #
# --------------------------------------------------------------------------- #


class _GitFacts:
    """The files changed and added on the branch (against git.base), plus uncommitted and untracked ones."""

    def __init__(self, ctx: Any):
        from .gates import a4

        self.base_name = str((ctx.cfg["git"] or {}).get("base") or "main")
        self.base: Optional[str] = None
        self.changed: List[str] = []
        self.added: Set[str] = set()
        self.reason: Optional[str] = None
        code, _ = git(ctx.root, "rev-parse", "--is-inside-work-tree")
        if code != 0:
            self.reason = "no git repository"
            return
        self.base = a4.base_ref(ctx)
        if self.base is None:
            self.reason = f"base branch '{self.base_name}' not found - set git.base or fetch it"
            return
        self.changed = a4.changed_files(ctx) or []
        code, out = git(ctx.root, "diff", "--name-only", "--diff-filter=A", f"{self.base}...HEAD")
        if code == 0:
            self.added.update(l.strip() for l in out.split("\n") if l.strip())
        code, out = git(ctx.root, "status", "--porcelain", "--untracked-files=all")
        if code == 0:
            for line in out.split("\n"):
                if len(line) <= 3:
                    continue
                status, path = line[:2], line[3:].strip()
                if " -> " in path:
                    path = path.split(" -> ", 1)[1]
                if status == "??" or status[0] == "A":
                    self.added.add(path.strip('"'))

    @property
    def ok(self) -> bool:
        return self.reason is None


def _excluded(path: str, fb: Dict[str, Any], extra: Sequence[str]) -> bool:
    parts = path.split("/")
    if any(p in DEFAULT_SCAN_EXCLUDES for p in parts[:-1]):
        return True
    return glob_match(path, fb["ignore"]) or bool(extra and glob_match(path, extra))


def _is_code(path: str, fb: Dict[str, Any], extra: Sequence[str]) -> bool:
    if _excluded(path, fb, extra):
        return False
    if fb["code"] == "auto":
        return Path(path).suffix in EXT_LANG
    return glob_match(path, fb["code"])


class _Units:
    """Build / deployment units: the nearest directory holding a unit marker (pom.xml, package.json, ...)."""

    def __init__(self, root: Path, markers: Sequence[str], added: Set[str], base_known: bool):
        self.root = root
        self.markers = list(markers)
        self.added = added
        self.base_known = base_known
        self._listing: Dict[str, List[str]] = {}

    def markers_in(self, directory: str) -> List[str]:
        if directory not in self._listing:
            path = self.root if directory in ("", ".") else self.root / directory
            try:
                names = sorted(n for n in os.listdir(path) if (path / n).is_file())
            except OSError:
                names = []
            self._listing[directory] = [n for n in names if any(fnmatch.fnmatchcase(n, m) for m in self.markers)]
        return self._listing[directory]

    def unit_of(self, path: str) -> Optional[str]:
        directory = posixpath.dirname(path)
        while True:
            if self.markers_in(directory):
                return directory or "."
            if directory in ("", "."):
                return None
            directory = posixpath.dirname(directory)

    def is_new(self, unit_root: str) -> Optional[bool]:
        if not self.base_known:
            return None
        directory = "" if unit_root == "." else unit_root
        names = self.markers_in(directory)
        if not names:
            return None
        return all((f"{directory}/{n}" if directory else n) in self.added for n in names)

    def nearest_existing(self, unit_root: str) -> Optional[str]:
        directory = "" if unit_root == "." else unit_root
        while directory not in ("", "."):
            directory = posixpath.dirname(directory)
            if self.markers_in(directory) and self.is_new(directory or ".") is False:
                return directory or "."
        return None


def repository_name(root: Path, fb: Dict[str, Any]) -> str:
    if fb["repository"] != "auto":
        return str(fb["repository"])
    code, out = git(root, "remote", "get-url", "origin")
    if code == 0 and out.strip():
        name = re.split(r"[/:]", out.strip().rstrip("/"))[-1]
        if name.endswith(".git"):
            name = name[:-4]
        if name:
            return name
    return root.resolve().name


# --------------------------------------------------------------------------- #
# The computation                                                               #
# --------------------------------------------------------------------------- #


class _Builder:
    def __init__(self, ctx: Any, computed_by: str):
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.fb = ctx.cfg["feedback"]
        self.kinds = set(self.fb["kinds"])
        self.computed_by = computed_by
        self.items: Dict[str, Dict[str, Any]] = {}
        self.skipped: List[Dict[str, str]] = []
        self.dm: Any = None
        self.home: Optional[str] = None
        self.version = "-"
        self.repo = ""
        self.facts: Optional[_GitFacts] = None
        self.code_files: List[str] = []
        self.mapping: Dict[str, Optional[str]] = {}
        self.units: Optional[_Units] = None
        self.topology: Dict[str, Any] = {"answer": "none", "units": []}
        self.import_targets: Set[str] = set()

    # ---------------------------------------------------------------- items
    def add(self, kind: str, subject: str, *, title: str, observation: str, suggestion: str,
            for_: List[Dict[str, Any]], target: str, impact: str, occurrences: Iterable[str] = (),
            evidence: Optional[List[Dict[str, Any]]] = None, waiver: Optional[Dict[str, Any]] = None) -> None:
        if kind not in self.kinds:
            return
        key = f"{kind}\n{subject}"
        if key in self.items:   # the same subject from a second source: merge the occurrences
            item = self.items[key]
            item["_occ"].update(occurrences)
            for ev in evidence or []:
                if ev not in item["evidence"]:
                    item["evidence"].append(ev)
            return
        self.items[key] = {
            "id": item_id(kind, subject), "kind": kind, "subject": subject, "title": title[:100],
            "observation": observation, "suggestion": suggestion, "for": for_, "target": target,
            "impact": impact, "waiver": waiver, "_occ": set(occurrences), "evidence": list(evidence or []),
            "first_seen": None,
        }

    def skip(self, kind: str, reason: str) -> None:
        entry = {"kind": kind, "reason": reason}
        if kind in self.kinds and entry not in self.skipped:
            self.skipped.append(entry)

    # ---------------------------------------------------------------- inputs
    def load(self) -> Optional[str]:
        """Load the map and the home context; the reason when the feedback cannot be evaluated at all."""
        ctx = self.ctx
        if ctx.feature_dir is None:
            return "no feature directory"
        dm = ctx.domain_map
        if dm is None:
            path = self.cfg.path("domain", "map")
            return f"no domain map ({rel_path(path, ctx.root) if path else 'domain.map is not set'})"
        problems = dm.problems()
        if problems:
            return f"the domain map is not valid: {problems[0]}"
        self.dm = dm
        self.version = dm.version or "-"
        handover = ctx.handover
        if handover is None:
            return f"no handover record ({self.cfg['feature']['handover']}) - the home context is unknown"
        home, problems = handover.home_context()
        if home is None or home not in dm.contexts:
            return f"no valid home context ({problems[0] if problems else f'{home} is not in the domain map'})"
        self.home = home
        self.repo = repository_name(ctx.root, self.fb)
        return None

    def read_git(self) -> None:
        self.facts = _GitFacts(self.ctx)
        if not self.facts.ok:
            for kind in ("unmapped-code", "cross-context", "new-unit", "topology"):
                self.skip(kind, self.facts.reason or "no git")
            self.skip("domain-change", f"imports not scanned: {self.facts.reason}")
            self.topology = {"answer": "unknown", "reason": self.facts.reason, "units": []}
            return
        extra = self.cfg.option("A4.4", "exclude", []) or []
        self.code_files = [f for f in self.facts.changed if _is_code(f, self.fb, extra)]
        self.mapping = {f: self.dm.context_of_path(f) for f in self.code_files}
        self.units = _Units(self.ctx.root, self.fb["unit_markers"], self.facts.added, self.facts.base is not None)

    # -------------------------------------------------------------- topology
    def _declared(self, unit_root: str) -> List[str]:
        return sorted(d.name for d in self.dm.deployables.values()
                      if d.repo in (None, self.repo) and d.root == unit_root)

    def new_unit_roots(self) -> List[str]:
        if self.units is None or self.facts is None:
            return []
        extra = self.cfg.option("A4.4", "exclude", []) or []
        roots = set()
        for path in self.facts.added:
            name = posixpath.basename(path)
            if not any(fnmatch.fnmatchcase(name, m) for m in self.fb["unit_markers"]):
                continue
            if _excluded(path, self.fb, extra) or not (self.ctx.root / path).is_file():
                continue
            unit = posixpath.dirname(path) or "."
            if self.units.is_new(unit):
                roots.add(unit)
        return sorted(roots)

    def build_topology(self) -> None:
        if self.units is None:
            return
        units: Dict[str, Dict[str, Any]] = {}
        for f in self.code_files:
            root = self.units.unit_of(f) or NO_UNIT
            u = units.setdefault(root, {"root": root, "files": 0, "contexts": set()})
            u["files"] += 1
            u["contexts"].add(self.mapping.get(f) or UNMAPPED)
        for root in self.new_unit_roots():
            units.setdefault(root, {"root": root, "files": 0, "contexts": set()})
        rows = []
        for root, u in units.items():
            if root == NO_UNIT:
                marker, new, declared = None, None, []
            else:
                names = self.units.markers_in("" if root == "." else root)
                marker, new, declared = (names[0] if names else None), self.units.is_new(root), self._declared(root)
            rows.append({"root": root, "marker": marker, "new": new, "contexts": sorted(u["contexts"]),
                         "files": u["files"], "declared": declared})
        rows.sort(key=lambda r: (r["root"] == NO_UNIT, bool(r["new"]), r["root"]))
        with_code = [r for r in rows if r["files"]]
        known = [r for r in with_code if r["root"] != NO_UNIT and r["new"] is not None]
        if not with_code:
            answer = "none"
        elif not known:
            answer = "unknown"
        else:
            has_new = any(r["new"] for r in known)
            has_old = any(not r["new"] for r in known)
            answer = "mixed" if has_new and has_old else ("new" if has_new else "existing")
        self.topology = {"answer": answer, "units": rows}
        if answer == "unknown":
            self.topology["reason"] = "no unit marker found above the changed code"

    # ----------------------------------------------------------------- kinds
    def kind_new_unit(self) -> None:
        if self.units is None:
            return
        for root in self.new_unit_roots():
            if self._declared(root):
                continue
            directory = "" if root == "." else root
            markers = [f"{directory}/{n}" if directory else n for n in self.units.markers_in(directory)]
            nearest = self.units.nearest_existing(root)
            move = f"the existing unit '{nearest}'" if nearest else "an existing unit"
            self.add("new-unit", f"{self.repo}:{root}",
                     title=f"New build unit {root} is not in the domain master design",
                     observation=f"This branch adds {_join(markers)}; no deployable of domain map {self.version} "
                                 f"names {self.repo}:{root}.",
                     suggestion=f"Decide in the domain master design whether {root} is a new deployable "
                                f"(deployables.<name> with contexts.<context>.deployable), or move its code into {move}.",
                     for_=[LEAD], target="domain-map: deployables, contexts.<context>.deployable", impact="high",
                     occurrences=markers, evidence=[{"path": m, "change": "added"} for m in markers])

    def kind_unmapped_code(self) -> None:
        if self.units is None:
            return
        if not any(c.code for c in self.dm.contexts.values()):
            return   # replaced by the map-gap item map:no-code-paths
        depth = _group_depth(self.dm, self.fb)
        new_roots = sorted(self.new_unit_roots(), key=len, reverse=True)
        groups: Dict[str, List[str]] = {}
        for f in self.code_files:
            if self.mapping.get(f):
                continue
            group = next((r for r in new_roots if r != "." and (f + "/").startswith(r + "/")), None)
            if group is None:
                parts = (posixpath.dirname(f) or ".").split("/")
                group = "/".join(parts[:depth]) if parts != ["."] else "."
            groups.setdefault(group, []).append(f)
        for group, files in sorted(groups.items()):
            glob = f"{group}/**" if group != "." else files[0]
            self.add("unmapped-code", group,
                     title=f"Code in {group} is mapped to no context",
                     observation=f"{_plural(len(files), 'changed code file')} under {group} "
                                 f"{_agree(len(files), 'matches', 'match')} no context's code "
                                 f"paths in domain map {self.version}, so the context-boundary fitness function "
                                 "(A4.4) cannot check them.",
                     suggestion=f"Map {glob} to a context in the next domain map version (contexts.{self.home}.code "
                                f"if it belongs to {self.home}), or declare a new context for it.",
                     for_=[LEAD], target="domain-map: contexts.<context>.code", impact="high", occurrences=files)

    def kind_cross_context(self) -> None:
        by_ctx: Dict[str, List[str]] = {}
        for f in self.code_files:
            c = self.mapping.get(f)
            if c and c != self.home:
                by_ctx.setdefault(c, []).append(f)
        for other, files in sorted(by_ctx.items()):
            types = sorted({r.type for r in self.dm.relations_between(self.home, other) if r.type != "separate-ways"})
            owner = self.dm.contexts[other].owner
            n = _plural(len(files), "file")
            if types:
                suggestion = (f"{n} of {other} changed by this {self.home} feature under the {'/'.join(types)} relation: "
                              f"plan the change as a {other} backlog item owned by {owner or 'its domain owner'}, or "
                              "record a partnership / shared kernel if the two contexts evolve together.")
            else:
                suggestion = (f"The map has no relation {self.home} -> {other}: propose one in the next domain map "
                              f"version, or split the change into a {other} feature.")
            self.add("cross-context", f"{self.home}->{other}",
                     title=f"The {self.home} feature changed code of {other}",
                     observation=f"{_plural(len(files), 'changed code file')} {_agree(len(files), 'belongs', 'belong')} "
                                 f"to context '{other}' (owner: "
                                 f"{owner or 'not named'}); the feature's home context is '{self.home}'.",
                     suggestion=suggestion, for_=[_owner(self.dm, other), LEAD], target="domain-map: relations",
                     impact="medium" if types else "high", occurrences=files)

    def kind_topology(self) -> None:
        if self.units is None or not self.code_files:
            return
        home = self.home
        rows = [r for r in self.topology["units"] if r["files"]]
        names = self.dm.contexts[home].deployable
        located = [self.dm.deployables[n] for n in names if n in self.dm.deployables]
        here = [d for d in located if d.repo in (None, self.repo)]
        new_items = set(self.new_unit_roots())
        unit_list = _join([f"'{r['root']}'" for r in rows if r["root"] != NO_UNIT])
        if not names:
            self.add("topology", f"{home}:undeclared",
                     title=f"The deployment unit of {home} is not declared",
                     observation=f"Context '{home}' declares no deployable in domain map {self.version}; this feature "
                                 f"changed code in the unit(s) {unit_list}.",
                     suggestion=f"Declare the deployment unit(s) of {home} in the domain map (contexts.{home}.deployable, "
                                "deployables.<name>), so the next feature can tell a new service from an existing one.",
                     for_=[LEAD], target=f"domain-map: contexts.{home}.deployable, deployables", impact="medium",
                     occurrences=[r["root"] for r in rows if r["root"] != NO_UNIT])
        elif located and not here:
            repos = _join(sorted({d.repo or "-" for d in located}))
            self.add("topology", f"{home}:{self.repo}",
                     title=f"{home} code changed outside the repository it is deployed from",
                     observation=f"The domain master design deploys '{home}' from {repos}; this feature changed {home} "
                                 f"code in {self.repo}.",
                     suggestion=f"{home} code changed in {self.repo}, but the domain master design deploys {home} from "
                                f"{repos}: declare this repository as a deployable of {home}, or move the change there.",
                     for_=[LEAD], target=f"domain-map: contexts.{home}.deployable, deployables", impact="medium",
                     occurrences=[f for f in self.code_files if self.mapping.get(f) == home])
        elif here:
            roots = sorted({d.root for d in here})
            for r in rows:
                if home not in r["contexts"] or r["root"] == NO_UNIT or r["root"] in roots or r["root"] in new_items:
                    continue
                self.add("topology", f"{home}:{self.repo}:{r['root']}",
                         title=f"{home} code changed in {r['root']}, which is not one of its deployables",
                         observation=f"'{home}' is deployed from {_join([repr(x) for x in roots])}; this feature "
                                     f"changed {_plural(r['files'], 'code file')} of the unit '{r['root']}'.",
                         suggestion=f"Add {r['root']} as a deployable of {home}, or move the code into {_join(roots)}.",
                         for_=[LEAD], target=f"domain-map: contexts.{home}.deployable, deployables", impact="medium",
                         occurrences=[f for f in self.code_files if self.mapping.get(f) == home])
        if self.dm.has_deployables and not any(d.repo in (None, self.repo) for d in self.dm.deployables.values()):
            self.add("topology", f"repo:{self.repo}",
                     title=f"Repository {self.repo} is not a deployable in the domain master design",
                     observation=f"No deployable of domain map {self.version} names the repository {self.repo}.",
                     suggestion="This repository is not a deployable in the domain master design (a new service?): "
                                "declare it, or name the deployable it belongs to.",
                     for_=[LEAD], target="domain-map: deployables", impact="medium", occurrences=[self.repo])

    def kind_vocabulary(self) -> None:
        from .gates import a0

        try:
            terms = a0.unknown_terms(self.ctx, self.dm, self.home)
        except ArchiGuardError as exc:
            self.skip("vocabulary", str(exc))
            return
        owner = _owner(self.dm, self.home)
        for name, where in terms:
            self.add("vocabulary", f"{self.home}:{_norm(name)}",
                     title=f"'{name}' is not a term of {self.home}",
                     observation=f"The data model or a contract uses '{name}', which is not in the glossary, the owned "
                                 f"entities or the synonyms of '{self.home}' (or of a related context) in domain map "
                                 f"{self.version}.",
                     suggestion=f"Add {name} to the glossary of {self.home} (or as a synonym of an existing term) in the "
                                "next domain map version, or rename it in the data model and contracts.",
                     for_=[owner, {"role": "BA"}], target=f"domain-map: contexts.{self.home}.glossary", impact="low",
                     occurrences=[where], evidence=[{"path": f"{self.ctx.feature}/{where.split(':')[0]}"}])

    def _domain_rules(self) -> List[str]:
        if self.fb["domain_rules"] != "auto":
            return list(self.fb["domain_rules"])
        try:
            lock = self.ctx.lock
        except ArchiGuardError:
            return []
        return sorted(str(r.get("id")) for r in lock.get("rules") or []
                      if any((c or {}).get("kind") == "context_boundaries" for c in r.get("checks") or []))

    def _waiver(self, rules: Sequence[str]) -> Optional[Dict[str, Any]]:
        for rid in rules:
            try:
                entry = self.ctx.waiver(rid)
            except ArchiGuardError:
                return None
            if entry:
                return {"id": entry.get("id"), "rule": rid, "expires": str(entry.get("expires") or "") or None}
        return None

    def kind_domain_change(self) -> None:
        rules = self._domain_rules()
        waiver = self._waiver(rules)
        # (a) imports of the changed code that the map does not allow
        if self.facts is not None and self.facts.ok:
            relation: Dict[Tuple[str, str], List[str]] = {}
            published: Dict[Tuple[str, str], List[str]] = {}
            evaluator = self.ctx.evaluator
            for f in self.code_files:
                src = self.mapping.get(f)
                if not src:
                    continue
                for spec, line in extract_imports(f, evaluator.text(self.ctx.root, f)):
                    resolved = resolve_relative(spec, f)
                    dst = self.dm.context_of_path(resolved) if resolved else self.dm.context_of_module(spec)
                    if dst is None or dst == src:
                        continue
                    self.import_targets.add(dst)
                    where = f"{f}:{line} import {spec}"
                    if self.dm.allows(src, dst) is None:
                        relation.setdefault((src, dst), []).append(where)
                    elif not self.dm.is_published(dst, None if resolved else spec, resolved):
                        published.setdefault((dst, _module_prefix(spec, resolved, f)), []).append(where)
            for (src, dst), wheres in sorted(relation.items()):
                base = (f"propose the relation {src} -> {dst} (and its type) in the next domain map version, "
                        "or remove the dependency")
                self.add("domain-change", f"relation:{src}->{dst}",
                         title=f"{src} depends on {dst} without a relation in the map",
                         observation=f"{_plural(len(wheres), 'import')} from {src} code reach context '{dst}', but "
                                     f"domain map {self.version} has no relation {src} -> {dst}.",
                         suggestion=self._with_waiver(base, waiver), for_=self._for(waiver),
                         target="domain-map: relations (or the code)", impact="high" if waiver else "medium",
                         occurrences=wheres, waiver=waiver)
            for (dst, prefix), wheres in sorted(published.items()):
                offers = _join(self.dm.contexts[dst].published, "nothing")
                base = f"publish {prefix} in contexts.{dst}.published, or use what {dst} publishes ({offers})"
                self.add("domain-change", f"published:{dst}:{prefix}",
                         title=f"{prefix} is used outside {dst} but not published",
                         observation=f"{_plural(len(wheres), 'import')} from other contexts use {prefix}, which "
                                     f"context '{dst}' does not publish (published: {offers}).",
                         suggestion=self._with_waiver(base, waiver), for_=self._for(waiver),
                         target=f"domain-map: contexts.{dst}.published (or the code)",
                         impact="high" if waiver else "medium", occurrences=wheres, waiver=waiver)
        # (b) deviations of domain rules recorded in the plan
        self._deviations(set(rules))
        # (d) waivers of domain rules the fitness runner applied for this feature: debt with an expiry date
        self._applied_waivers(set(rules))
        # (c) entity ownership (the A0.3 logic, read-only; it matters in mode: report)
        handover = self.ctx.handover
        for node, info in sorted((handover.data_nodes if handover else {}).items()):
            entity = str(info.get("entity") or "") if isinstance(info, dict) else str(info)
            if not entity:
                continue
            tagged = info.get("context") if isinstance(info, dict) else None
            owner = str(tagged) if tagged else self.dm.owner_of_entity(entity)
            if owner is None:
                why, how = (f"no context of domain map {self.version} owns {entity}",
                            f"Give {entity} an owning context in the next domain map version.")
            elif owner in self.dm.contexts and owner != self.home and self.dm.allows(self.home, owner) is None:
                why, how = (f"{entity} is owned by '{owner}' and '{self.home}' has no relation to it",
                            f"Reach {entity} through an allowed relation {self.home} -> {owner}, or propose one in "
                            "the next domain map version.")
            else:
                continue
            self.add("domain-change", f"entity:{entity}",
                     title=f"Entity {entity} has no owner the feature may reach",
                     observation=f"{node}: {why}.", suggestion=how, for_=[LEAD, {"role": "BA"}],
                     target="domain-map: contexts.<context>.owns_entities, relations", impact="medium",
                     occurrences=[node], evidence=[{"path": f"{self.ctx.feature}/{self.cfg['feature']['handover']}"}])

    def _applied_waivers(self, rules: Set[str]) -> None:
        if not rules or self.ctx.feature_dir is None:
            return
        path = self.ctx.gates_dir / "A4" / "A4.4.json"
        if not path.is_file():
            return
        try:
            verdict = json.loads(read_text(path))
        except (ValueError, ArchiGuardError):
            return
        attached = {(i.get("waiver") or {}).get("id") for i in self.items.values()}
        for w in verdict.get("waived") or []:
            rid, wid = w.get("rule"), w.get("waiver")
            if rid not in rules or not wid or wid in attached:
                continue
            attached.add(wid)
            expires = str(w.get("expires") or "") or None
            until = f" until {expires}" if expires else ""
            self.add("domain-change", f"waiver:{wid}",
                     title=f"The feature relies on waiver {wid} for {rid}",
                     observation=f"The fitness runner (A4.4) passed {rid} only because the ledger waiver {wid} is in "
                                 f"force{until}.",
                     suggestion=f"Waived by {wid}{until}: refactor the code to meet {rid}, or change the domain map so "
                                "the dependency is allowed (a relation or a published interface), before then.",
                     for_=[LEAD, TECH_LEAD], target="code (or domain-map: relations, contexts.<context>.published)",
                     impact="high", occurrences=[f"{rid} {wid}"],
                     evidence=[{"path": rel_path(path, self.ctx.root)}],
                     waiver={"id": wid, "rule": rid, "expires": expires})

    def _with_waiver(self, text: str, waiver: Optional[Dict[str, Any]]) -> str:
        if not waiver:
            return text[0].upper() + text[1:] + "."
        until = f" until {waiver['expires']}" if waiver.get("expires") else ""
        return f"Waived by {waiver['id']}{until}: {text} before then."

    def _for(self, waiver: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [LEAD, TECH_LEAD] if waiver else [LEAD]

    def _deviations(self, rules: Set[str]) -> None:
        if not rules or self.ctx.feature_dir is None:
            return
        plan_path = self.ctx.feature_file("plan.md")
        if not plan_path.is_file():
            return
        from .gates import a3

        section = self.cfg.option("A3.3", "section", "Architecture Conformance")
        _, rows, _ = a3._conformance_rows(strip_html_comments(read_text(plan_path)), section)
        for rid, entries in sorted(rows.items()):
            if rid not in rules:
                continue
            for line, status, ref, reason in entries:
                if a3.normalise_status(status) != a3.STATUS_DEVIATION:
                    continue
                cited = LEDGER_ID.findall(f"{reason} {ref}")
                adr = cited[0] if cited else None
                entry = self.ctx.ledger.get(adr) if adr else None
                waiver = {"id": adr, "rule": rid, "expires": str((entry or {}).get("expires") or "") or None} if adr else None
                self.add("domain-change", f"rule:{rid}:{self.home}",
                         title=f"{rid} is met by deviation in {self.home}",
                         observation=f"plan.md:{line} records a deviation from {rid}" + (f" ({adr})." if adr else "."),
                         suggestion=f"{rid} is met by deviation ({adr or 'no ADR cited'}): decide in the domain master "
                                    "design whether the map or the rule changes, so the deviation can end.",
                         for_=[LEAD, TECH_LEAD], target="domain-map (or the rulebook)", impact="high",
                         occurrences=[f"plan.md:{line}"], evidence=[{"path": f"{self.ctx.feature}/plan.md", "line": line}],
                         waiver=waiver)
                break

    def kind_map_gap(self) -> None:
        dm = self.dm
        if not any(c.code for c in dm.contexts.values()):
            self.add("map-gap", "map:no-code-paths",
                     title="No context declares its code paths",
                     observation=f"No context of domain map {self.version} declares code paths, so neither A4.4 nor "
                                 "the loop feedback can attribute code to contexts.",
                     suggestion="Declare the code paths of every context (contexts.<context>.code) in the next domain "
                                "map version.",
                     for_=[LEAD], target="domain-map: contexts.<context>.code", impact="medium")
            no_code = False
        else:
            no_code = True
        scope = {self.home} | set(dm.related_contexts(self.home)) | self.import_targets
        scope |= {c for c in self.mapping.values() if c}
        for name in sorted(c for c in scope if c in dm.contexts):
            c = dm.contexts[name]
            if no_code and not c.code:
                self.add("map-gap", f"{name}:no-code",
                         title=f"Context {name} declares no code paths",
                         observation=f"Context '{name}' has no code paths in domain map {self.version}, so A4.4 cannot "
                                     "attribute its files" + (f" (it declares the modules {_join(c.modules)})." if c.modules else "."),
                         suggestion=f"Declare the code paths of {name} (contexts.{name}.code) so the context-boundary "
                                    "fitness function covers it.",
                         for_=[LEAD], target=f"domain-map: contexts.{name}.code", impact="low")
            if not c.owner:
                self.add("map-gap", f"{name}:no-owner",
                         title=f"Context {name} has no domain owner",
                         observation=f"Context '{name}' names no owner in domain map {self.version}.",
                         suggestion=f"Name the domain owner of {name}, so its feedback has an addressee.",
                         for_=[LEAD], target=f"domain-map: contexts.{name}.owner", impact="low")
            if dm.has_deployables:
                for dname in c.deployable:
                    if dname not in dm.deployables:
                        self.add("map-gap", f"deployable:{dname}:undefined",
                                 title=f"Deployable {dname} is not defined",
                                 observation=f"Context '{name}' names the deployable {dname}, which deployables: does "
                                             "not define.",
                                 suggestion=f"Add {dname} to deployables: with its repo and root.",
                                 for_=[LEAD], target="domain-map: deployables", impact="low")
        for problem in dm.topology_problems:
            self.add("map-gap", "map:deployables",
                     title="The deployables section cannot be read",
                     observation=f"Domain map {self.version}: {problem}.",
                     suggestion="Write deployables: as a mapping of name to {repo, root, kind}.",
                     for_=[LEAD], target="domain-map: deployables", impact="low")

    # --------------------------------------------------------------- result
    def items_list(self) -> Tuple[List[Dict[str, Any]], int]:
        order = {k: i for i, k in enumerate(FEEDBACK_KINDS)}
        rank = {k: i for i, k in enumerate(IMPACTS)}
        items = sorted(self.items.values(), key=lambda i: (rank[i["impact"]], order[i["kind"]], i["subject"]))
        seen: Dict[str, int] = {}
        for item in items:
            occ = sorted(item.pop("_occ"))
            item["occurrences"] = {"count": len(occ), "items": occ[:MAX_OCCURRENCES]}
            seen[item["id"]] = seen.get(item["id"], 0) + 1
        if any(n > 1 for n in seen.values()):   # a collision of the short ids: extend them
            for item in items:
                if seen[item["id"]] > 1:
                    item["id"] = item_id(item["kind"], item["subject"], 12)
        cap = int(self.fb["max_items"])
        return items[:cap], max(0, len(items) - cap)

    def run(self) -> Dict[str, Any]:
        reason = self.load()
        if reason is not None:
            return self.record("not-evaluated", reason=reason)
        self.read_git()
        self.build_topology()
        self.kind_new_unit()
        self.kind_unmapped_code()
        self.kind_cross_context()
        self.kind_domain_change()      # before topology / map-gap: it collects the import targets
        self.kind_topology()
        self.kind_vocabulary()
        self.kind_map_gap()
        return self.record("partial" if self.skipped else "evaluated")

    def record(self, status: str, reason: Optional[str] = None) -> Dict[str, Any]:
        ctx = self.ctx
        items, truncated = self.items_list() if status != "not-evaluated" else ([], 0)
        commit = None
        try:
            commit = ctx.head()[0]
        except ArchiGuardError:
            pass
        try:
            pins = ctx.pins()
        except ArchiGuardError:
            pins = {}
        by_impact = Counter(i["impact"] for i in items)
        data: Dict[str, Any] = {
            "tool": "archiguard",
            "kind": "loop-feedback",
            "schema": SCHEMA,
            "guardrail_version": __version__,
            "feature": ctx.feature,
            "status": status,
            "computed_at": _now(),
            "computed_by": self.computed_by,
            "commit": commit,
            "base": self.facts.base if self.facts and self.facts.base else self.cfg["git"].get("base"),
            "repository": self.repo or None,
            "pins": pins,
            "home_context": self.home,
            "topology": self.topology,
            "summary": {"items": len(items), **{k: by_impact.get(k, 0) for k in IMPACTS},
                        "by_kind": dict(sorted(Counter(i["kind"] for i in items).items(),
                                               key=lambda kv: FEEDBACK_KINDS.index(kv[0])))},
            "items": items,
            "resolved": [],
            "skipped": self.skipped,
            "truncated": truncated,
        }
        if reason:
            data["reason"] = reason
        return data


def compute(ctx: Any, computed_by: str) -> Dict[str, Any]:
    """The loop feedback of the feature. Never raises: a failure is a not-evaluated record (FR-004)."""
    builder = _Builder(ctx, computed_by)
    try:
        return builder.run()
    except Exception as exc:  # noqa: BLE001 - the feedback must never stop a command (D1)
        builder.items = {}
        return builder.record("not-evaluated", reason=f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# Files                                                                         #
# --------------------------------------------------------------------------- #


def json_path(feature_dir: Path) -> Path:
    return feature_dir / GATES_DIRNAME / FEEDBACK_JSON


def md_path(feature_dir: Path) -> Path:
    return feature_dir / GATES_DIRNAME / FEEDBACK_MD


def load(feature_dir: Optional[Path]) -> Optional[Dict[str, Any]]:
    if feature_dir is None:
        return None
    path = json_path(feature_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(read_text(path))
    except (ValueError, ArchiGuardError):
        return None
    return data if isinstance(data, dict) and data.get("kind") == "loop-feedback" else None


def _stable(data: Dict[str, Any]) -> str:
    return canonical_json({k: v for k, v in data.items() if k not in VOLATILE})


def merge(data: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Carry first_seen over and keep resolved[]: the ids an earlier run raised that are no longer raised."""
    if not previous:
        for item in data["items"]:
            item["first_seen"] = data["computed_at"]
        return data
    before = {i.get("id"): i for i in previous.get("items") or [] if isinstance(i, dict)}
    current = {i["id"] for i in data["items"]}
    for item in data["items"]:
        old = before.get(item["id"])
        item["first_seen"] = (old or {}).get("first_seen") or data["computed_at"]
    resolved = [r for r in previous.get("resolved") or [] if isinstance(r, dict) and r.get("id") not in current]
    comparable = ("evaluated", "partial")
    if data["status"] in comparable and previous.get("status") in comparable:
        skipped = {s.get("kind") for s in data.get("skipped") or []}
        enabled = set(FEEDBACK_KINDS)
        for iid, old in before.items():
            if iid in current or old.get("kind") in skipped or old.get("kind") not in enabled:
                continue
            if any(r.get("id") == iid for r in resolved):
                continue
            resolved.append({"id": iid, "kind": old.get("kind"), "subject": old.get("subject"),
                             "resolved_at": data["computed_at"], "resolved_by": data["computed_by"]})
    data["resolved"] = resolved[-MAX_RESOLVED:]
    return data


def save(ctx: Any, data: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], bool]:
    """Write the files when anything but computed_at / computed_by / commit changed (write-if-changed)."""
    jpath, mpath = json_path(ctx.feature_dir), md_path(ctx.feature_dir)
    if previous is not None and _stable(previous) == _stable(data):
        if not mpath.is_file():
            write_text(mpath, render_markdown(previous, ctx.feature))
        return previous, False
    write_json(jpath, data)
    write_text(mpath, render_markdown(data, ctx.feature))
    return data, True


def produce(root: Path, cfg: Any, feature_dir: Optional[Path], computed_by: str, *, write: bool = True,
            ctx: Any = None) -> Optional[Dict[str, Any]]:
    """Compute, merge with the previous file and (when allowed) save. None when the feedback is switched off."""
    if not cfg["feedback"]["enabled"] or feature_dir is None:
        return None
    if ctx is None:
        from .gates.context import GateContext

        ctx = GateContext(root, cfg, feature_dir, write=write)
    try:
        previous = load(feature_dir)
        data = merge(compute(ctx, computed_by), previous)
        if write and ctx.write:
            data, _ = save(ctx, data, previous)
        return data
    except Exception as exc:  # noqa: BLE001 - never stop a command (D1)
        return {"tool": "archiguard", "kind": "loop-feedback", "status": "not-evaluated",
                "reason": f"{type(exc).__name__}: {exc}", "items": [], "topology": {"answer": "unknown", "units": []},
                "summary": {"items": 0, "high": 0, "medium": 0, "low": 0, "by_kind": {}}, "feature": ctx.feature}


def manifest_entry(data: Optional[Dict[str, Any]], feature_dir: Path, root: Path) -> Optional[Dict[str, Any]]:
    """The 'feedback' key of the test-handover manifest (handover-4-5.json)."""
    if data is None:
        return None
    path = json_path(feature_dir)
    summary = data.get("summary") or {}
    return {"file": rel_path(path, root), "sha256": sha256_file(path), "status": data.get("status"),
            "answer": (data.get("topology") or {}).get("answer"), "items": summary.get("items", 0),
            "by_impact": {k: summary.get(k, 0) for k in IMPACTS}}


# --------------------------------------------------------------------------- #
# Rendering                                                                     #
# --------------------------------------------------------------------------- #


def _ctx_label(contexts: Sequence[str], home: Optional[str]) -> str:
    out = []
    for c in contexts:
        if c == UNMAPPED:
            out.append("no context")
        elif c == home:
            out.append(f"{c} (home)")
        else:
            out.append(c)
    return ", ".join(out) or "-"


def topology_line(data: Dict[str, Any]) -> str:
    topo = data.get("topology") or {}
    answer = topo.get("answer") or "unknown"
    rows = [r for r in topo.get("units") or [] if r.get("files")]
    if answer == "none":
        return "none - no code changed on this branch"
    if answer == "unknown":
        return f"unknown - {topo.get('reason') or 'no unit marker found above the changed code'}"
    parts = []
    for r in rows:
        if r["root"] == NO_UNIT:
            parts.append(f"code outside any unit ({_ctx_label(r['contexts'], None)})")
            continue
        label = "NEW unit" if r.get("new") else "existing unit"
        parts.append(f"{label} '{r['root']}' ({_ctx_label(r['contexts'], None)})")
    return f"{answer} - " + " + ".join(parts)


def topology_sentence(data: Dict[str, Any]) -> str:
    topo = data.get("topology") or {}
    answer = topo.get("answer") or "unknown"
    rows = [r for r in topo.get("units") or [] if r.get("files") and r["root"] != NO_UNIT]
    if answer == "none":
        return "**Answer: none.** No code changed on this branch."
    if answer == "unknown":
        return f"**Answer: unknown.** {topo.get('reason') or 'No unit marker was found above the changed code'}."
    old = [f"`{r['root']}`" for r in rows if not r.get("new")]
    new = [r for r in rows if r.get("new")]
    bits = []
    if old:
        bits.append(f"extends the existing unit{'s' if len(old) > 1 else ''} {', '.join(old)}")
    if new:
        described = []
        for r in new:
            unmapped = UNMAPPED in r["contexts"] and len(r["contexts"]) == 1
            note = (" (declared as " + ", ".join(r["declared"]) + ")") if r.get("declared") else \
                   (", which no context of the domain master design maps" if unmapped else
                    ", which the domain master design does not declare")
            described.append(f"`{r['root']}`{note}")
        bits.append(f"creates the new unit{'s' if len(new) > 1 else ''} {'; '.join(described)}")
    text = f"**Answer: {answer}.** The feature " + " and ".join(bits) + "."
    home = data.get("home_context")
    if home and any(i.get("subject") == f"{home}:undeclared" for i in data.get("items") or []):
        text += f" The domain master design declares no deployable for {home}."
    return text


def _short(text: str, limit: int = 150) -> str:
    indent = text[: len(text) - len(text.lstrip())]
    body = text.strip().replace("\n", " ")
    limit -= len(indent)
    return indent + (body if len(body) <= limit else body[: limit - 1].rstrip() + "…")


def render_block(data: Optional[Dict[str, Any]], feature_dir_rel: Optional[str] = None, *,
                 print_items: int = 3, saved: bool = True) -> str:
    """The FEEDBACK block printed after the gate result (at most print_items + 3 lines)."""
    if data is None:
        return ""
    if data.get("status") == "not-evaluated":
        return f"FEEDBACK: not evaluated - {data.get('reason') or 'unknown reason'}"
    items = data.get("items") or []
    topo = topology_line(data)
    if not items:
        return f"FEEDBACK for the domain master design: nothing to report (topology: {topo})"
    s = data.get("summary") or {}
    lines = [f"FEEDBACK for the domain master design (not blocking, for the next iteration): "
             f"{len(items)} item(s) - {s.get('high', 0)} high, {s.get('medium', 0)} medium, {s.get('low', 0)} low",
             f"  topology: {topo}"]
    for item in items[:print_items]:
        lines.append(_short(f"  [{item['impact']}]", 12).ljust(11) + _short(
            f"{item['id']} {item['kind']:<14} {item['subject']} - {item['suggestion']}", 200))
    rest = len(items) - min(len(items), print_items)
    if rest:
        where = f"{feature_dir_rel}/{GATES_DIRNAME}/{FEEDBACK_MD}" if (saved and feature_dir_rel) else "archiguard feedback"
        lines.append(f"  ... {rest} more: {where}")
    elif saved and feature_dir_rel:
        lines.append(f"  details: {feature_dir_rel}/{GATES_DIRNAME}/{FEEDBACK_MD}")
    return "\n".join(lines)


def summary_line(data: Optional[Dict[str, Any]]) -> Optional[str]:
    """One line for the configure / report headers."""
    if data is None:
        return None
    if data.get("status") == "not-evaluated":
        return f"not evaluated - {data.get('reason')}"
    s = data.get("summary") or {}
    return (f"{s.get('items', 0)} item(s) - {s.get('high', 0)} high, {s.get('medium', 0)} medium, {s.get('low', 0)} low"
            f" · topology {(data.get('topology') or {}).get('answer')}")


def _cell(text: Any) -> str:
    return " ".join(str(text if text is not None else "").split()).replace("|", "\\|")


def _for_label(entries: Sequence[Dict[str, Any]]) -> str:
    out = []
    for e in entries or []:
        if e.get("name"):
            out.append(str(e["name"]))
        elif e.get("context"):
            out.append(f"{e['context']} {e.get('role')}")
        else:
            out.append(str(e.get("role")))
    return ", ".join(out)


def item_table(items: Sequence[Dict[str, Any]]) -> List[str]:
    lines = ["| Id | Impact | Kind | Subject | Suggestion for the next iteration | For |", "|---|---|---|---|---|---|"]
    for i in items:
        lines.append(f"| {i['id']} | {i['impact']} | {i['kind']} | {_cell(i['subject'])} | {_cell(i['suggestion'])} | "
                     f"{_cell(_for_label(i.get('for') or []))} |")
    return lines


def unit_table(data: Dict[str, Any]) -> List[str]:
    rows = (data.get("topology") or {}).get("units") or []
    if not rows:
        return []
    home = data.get("home_context")
    lines = ["| Unit | New on this branch | Contexts of the changed code | Code files | Declared deployable |",
             "|---|---|---|---|---|"]
    for r in rows:
        unit = "outside any unit" if r["root"] == NO_UNIT else f"`{r['root']}`" + (f" ({r['marker']})" if r.get("marker") else "")
        new = {True: "**yes**", False: "no", None: "unknown"}[r.get("new")]
        lines.append(f"| {unit} | {new} | {_cell(_ctx_label(r.get('contexts') or [], home))} | {r.get('files', 0)} | "
                     f"{_cell(', '.join(r.get('declared') or []) or 'none')} |")
    return lines


def section_lines(data: Optional[Dict[str, Any]], *, heading: str = "##") -> List[str]:
    """The topology and the items - the body of loop-feedback.md and of the compliance report section."""
    if data is None:
        return ["Not computed yet (it is computed after implement step B, at handover 4 -> 5 and by report --save)."]
    if data.get("status") == "not-evaluated":
        return [f"Not evaluated: {data.get('reason')}."]
    lines = [f"{heading}# Topology: new service or existing one?", "", topology_sentence(data), ""]
    table = unit_table(data)
    if table:
        lines += table + [""]
    items = data.get("items") or []
    s = data.get("summary") or {}
    lines.append(f"{heading}# Items ({len(items)}: {s.get('high', 0)} high, {s.get('medium', 0)} medium, {s.get('low', 0)} low)")
    lines.append("")
    lines += (item_table(items) if items else ["None: the domain master design describes what this feature did."])
    if data.get("truncated"):
        lines += ["", f"{data['truncated']} more item(s) not listed (feedback.max_items)."]
    if data.get("skipped"):
        lines += ["", "Not evaluated: " + "; ".join(f"{s.get('kind')} ({s.get('reason')})" for s in data["skipped"]) + "."]
    return lines


def render_markdown(data: Dict[str, Any], feature: str) -> str:
    pins = data.get("pins") or {}
    commit = (data.get("commit") or "-")[:7]
    lines = [
        f"# Loop feedback - {feature}",
        "",
        "Not blocking: what this feature did that the domain master design does not describe, for the next iteration.",
        f"archiGuard {data.get('guardrail_version') or __version__} · {COMPUTED_BY.get(str(data.get('computed_by')), data.get('computed_by'))}"
        f" · commit {commit} · domain map {pins.get('domain_map') or '-'} · repository {data.get('repository') or '-'}",
        "",
    ]
    lines += section_lines(data, heading="#")
    lines += ["", "## Each item in detail", ""]
    for i in data.get("items") or []:
        lines.append(f"- **{i['id']}** ({i['impact']}, {i['kind']}) **{_cell(i['title'])}** - {_cell(i['observation'])} "
                     f"Suggestion: {_cell(i['suggestion'])} Target: {_cell(i['target'])}. For: {_cell(_for_label(i.get('for') or []))}."
                     + (f" Occurrences ({i['occurrences']['count']}): " + ", ".join(f"`{_cell(o)}`" for o in i["occurrences"]["items"][:5])
                        + (" ..." if i["occurrences"]["count"] > 5 else "") if i.get("occurrences", {}).get("count") else ""))
    if not data.get("items"):
        lines.append("None.")
    resolved = data.get("resolved") or []
    lines += ["", "## Resolved during this feature", ""]
    lines += [f"- {r.get('id')} {r.get('kind')} {_cell(r.get('subject'))} - resolved {str(r.get('resolved_at') or '')[:16]}"
              for r in resolved] or ["None."]
    return "\n".join(lines).rstrip() + "\n"

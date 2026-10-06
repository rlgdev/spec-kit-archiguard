"""The domain map (policy) and the feature's handover record."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import yamlio
from .common import ArchiGuardError, glob_match, normalize_id

RELATION_TYPES = (
    "customer-supplier", "conformist", "anticorruption-layer", "open-host-service",
    "published-language", "shared-kernel", "partnership", "separate-ways",
)
SYMMETRIC = ("shared-kernel", "partnership")


@dataclass
class Context:
    name: str
    domain: Optional[str]
    owner: Optional[str]
    glossary: List[str]
    synonyms: Dict[str, str]
    owns_entities: List[str]
    publishes: List[str]
    code: List[str]          # path globs of the code that belongs to the context
    modules: List[str]       # import prefixes (packages / namespaces) of the context
    published: List[str]     # import prefixes or path globs other contexts may use
    packs: List[str]         # rulebook packs this context pulls in


@dataclass
class Relation:
    source: str              # downstream / consumer ("from")
    target: str              # upstream / provider ("to")
    type: str
    via: List[str] = field(default_factory=list)


class DomainMap:
    def __init__(self, path: Path, data: Dict[str, Any]):
        self.path = path
        self.data = data
        self.version = str(data.get("domain_map_version")) if data.get("domain_map_version") is not None else None
        self.status = str(data.get("status")) if data.get("status") is not None else None
        types = data.get("relation_types") or list(RELATION_TYPES)
        self.relation_types = [str(t) for t in types]
        self.contexts: Dict[str, Context] = {}
        raw_contexts = data.get("contexts") or {}
        if not isinstance(raw_contexts, dict):
            raise ArchiGuardError(f"{path}: contexts must be a mapping of context name to its definition")
        for name, c in raw_contexts.items():
            c = c or {}
            if not isinstance(c, dict):
                raise ArchiGuardError(f"{path}: context {name} must be a mapping")
            syn = c.get("synonyms") or {}
            if isinstance(syn, list):
                syn = {str(s): "" for s in syn}
            self.contexts[str(name)] = Context(
                name=str(name),
                domain=c.get("domain"),
                owner=c.get("owner"),
                glossary=[str(x) for x in (c.get("glossary") or [])],
                synonyms={str(k): str(v) for k, v in syn.items()},
                owns_entities=[str(x) for x in (c.get("owns_entities") or [])],
                publishes=[str(x) for x in (c.get("publishes") or [])],
                code=[str(x) for x in (c.get("code") or [])],
                modules=[str(x) for x in (c.get("modules") or [])],
                published=[str(x) for x in (c.get("published") or [])],
                packs=[str(x) for x in (c.get("packs") or [])],
            )
        self.relations: List[Relation] = []
        for r in data.get("relations") or []:
            if not isinstance(r, dict):
                raise ArchiGuardError(f"{path}: every relation must be a mapping with from, to, type")
            src, dst, rtype = r.get("from"), r.get("to"), r.get("type")
            if not src or not dst or not rtype:
                raise ArchiGuardError(f"{path}: relation {r} needs from, to and type")
            self.relations.append(Relation(str(src), str(dst), str(rtype), [str(v) for v in (r.get("via") or [])]))

    # ---------------------------------------------------------------- checks
    def problems(self) -> List[str]:
        out = []
        if not self.version:
            out.append("domain_map_version is missing")
        for r in self.relations:
            for end in (r.source, r.target):
                if end not in self.contexts:
                    out.append(f"relation {r.source} -> {r.target}: unknown context {end}")
            if r.type not in self.relation_types:
                out.append(f"relation {r.source} -> {r.target}: unknown type {r.type}")
        owners: Dict[str, str] = {}
        for c in self.contexts.values():
            for e in c.owns_entities:
                if e in owners and owners[e] != c.name:
                    out.append(f"entity {e} is owned by both {owners[e]} and {c.name}")
                owners[e] = c.name
        return out

    def released(self) -> Tuple[bool, str]:
        if self.status is not None and self.status != "released":
            return False, f"status is '{self.status}', not 'released'"
        if self.version and "-" in self.version:
            return False, f"version {self.version} is a pre-release"
        return True, ""

    def owner_of_entity(self, entity: str) -> Optional[str]:
        norm = _norm(entity)
        for c in self.contexts.values():
            if any(_norm(e) == norm for e in c.owns_entities):
                return c.name
        return None

    def relations_between(self, a: str, b: str) -> List[Relation]:
        return [r for r in self.relations if (r.source == a and r.target == b) or (r.source == b and r.target == a)]

    def allows(self, consumer: str, provider: str) -> Optional[Relation]:
        """The relation that lets `consumer` depend on `provider` (directional, symmetric types both ways)."""
        for r in self.relations:
            if r.type == "separate-ways":
                continue
            if r.source == consumer and r.target == provider:
                return r
            if r.type in SYMMETRIC and r.source == provider and r.target == consumer:
                return r
        return None

    def related_contexts(self, ctx: str) -> List[str]:
        out = []
        for r in self.relations:
            if r.type == "separate-ways":
                continue
            if r.source == ctx:
                out.append(r.target)
            elif r.target == ctx:
                out.append(r.source)
        return sorted(set(out))

    def context_of_path(self, rel_path: str) -> Optional[str]:
        for c in self.contexts.values():
            if c.code and glob_match(rel_path, c.code):
                return c.name
        return None

    def context_of_module(self, module: str) -> Optional[str]:
        best: Tuple[int, Optional[str]] = (0, None)
        for c in self.contexts.values():
            for prefix in c.modules:
                if _module_has_prefix(module, prefix) and len(prefix) > best[0]:
                    best = (len(prefix), c.name)
        return best[1]

    def is_published(self, ctx: str, module: Optional[str], path: Optional[str]) -> bool:
        c = self.contexts.get(ctx)
        if c is None or not c.published:
            return True
        for entry in c.published:
            if ("/" in entry or "*" in entry) and path is not None and glob_match(path, [entry]):
                return True
            if module is not None and "/" not in entry and "*" not in entry and _module_has_prefix(module, entry):
                return True
        return False

    def vocabulary(self, ctx: str) -> List[str]:
        """Terms the home context may use: its glossary, synonyms, owned entities, and those of related contexts."""
        terms: List[str] = []
        for name in [ctx] + self.related_contexts(ctx):
            c = self.contexts.get(name)
            if c is None:
                continue
            terms.extend(c.glossary)
            terms.extend(c.owns_entities)
            if name == ctx:
                terms.extend(c.synonyms.keys())
        return terms


def _module_has_prefix(module: str, prefix: str) -> bool:
    if module == prefix:
        return True
    for sep in (".", "/", "::", "\\"):
        if module.startswith(prefix + sep):
            return True
    return False


def _norm(term: str) -> str:
    return re.sub(r"[^a-z0-9]", "", term.lower())


def load_domain_map(path: Optional[Path]) -> DomainMap:
    if path is None:
        raise ArchiGuardError("no domain map configured (domain.map in archiguard-config.yml)")
    if not path.is_file():
        raise ArchiGuardError(
            f"domain map not found: {path} - publish the domain master design as domain-map.yaml "
            "(template: templates/domain-map-template.yaml in the archiGuard extension)"
        )
    data = yamlio.load_file(path)
    return DomainMap(path, data)


# --------------------------------------------------------------------------- #
# Handover record (written by the formal handover to Spec Kit)                 #
# --------------------------------------------------------------------------- #


@dataclass
class Handover:
    path: Path
    data: Dict[str, Any]

    @property
    def source(self) -> Dict[str, Any]:
        return self.data.get("source") or {}

    @property
    def spec_version(self) -> Optional[str]:
        v = self.source.get("version")
        return str(v) if v is not None else None

    @property
    def spec_sha256(self) -> Optional[str]:
        v = self.source.get("sha256")
        return str(v).lower() if v else None

    @property
    def domain(self) -> Dict[str, Any]:
        return self.data.get("domain") or {}

    @property
    def map_version(self) -> Optional[str]:
        v = self.domain.get("map_version")
        return str(v) if v is not None else None

    @property
    def use_cases(self) -> Dict[str, Any]:
        uc = self.data.get("use_cases") or {}
        return {normalize_id(str(k)): v for k, v in uc.items()} if isinstance(uc, dict) else {}

    @property
    def items(self) -> Dict[str, Any]:
        it = self.data.get("items") or {}
        return {normalize_id(str(k)): v for k, v in it.items()} if isinstance(it, dict) else {}

    @property
    def data_nodes(self) -> Dict[str, Dict[str, Any]]:
        d = self.data.get("data") or {}
        out: Dict[str, Dict[str, Any]] = {}
        if isinstance(d, dict):
            for k, v in d.items():
                out[normalize_id(str(k))] = v if isinstance(v, dict) else {"entity": v}
        return out

    @property
    def scope(self) -> List[str]:
        return [normalize_id(str(s)) for s in (self.data.get("scope") or [])]

    def home_context(self) -> Tuple[Optional[str], List[str]]:
        """(home context, problems) - one context for all the feature's Use Cases."""
        problems: List[str] = []
        contexts = []
        for uc, ctx in self.use_cases.items():
            if isinstance(ctx, list):
                if len(ctx) != 1:
                    problems.append(f"{uc} names {len(ctx)} home contexts ({', '.join(map(str, ctx)) or 'none'}); exactly one is required")
                    continue
                ctx = ctx[0]
            if isinstance(ctx, dict):
                ctx = ctx.get("context")
            if not ctx:
                problems.append(f"{uc} has no home context")
                continue
            contexts.append(str(ctx))
        declared = self.domain.get("home_context")
        distinct = sorted(set(contexts))
        if not self.use_cases:
            problems.append("the handover names no Use Case with its home context (use_cases:)")
        if len(distinct) > 1:
            problems.append(f"the feature's Use Cases belong to several home contexts: {', '.join(distinct)}")
        home = distinct[0] if len(distinct) == 1 else (str(declared) if declared and not distinct else None)
        if declared and distinct and str(declared) not in distinct:
            problems.append(f"domain.home_context is {declared} but the Use Cases belong to {', '.join(distinct)}")
        return home, problems


def load_handover(feature_dir: Path, filename: str) -> Optional[Handover]:
    path = feature_dir / filename
    if not path.is_file():
        return None
    data = yamlio.load_file(path)
    return Handover(path, data)

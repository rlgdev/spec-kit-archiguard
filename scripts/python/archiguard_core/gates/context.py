"""Everything a check needs about the project and the feature, loaded lazily."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import standards
from ..codeanalysis import Evaluator
from ..common import (
    GATES_DIRNAME,
    ArchiGuardError,
    git_head,
    normalize_id,
    read_text,
    rel_path,
    sha256_file,
    today,
)
from ..domain import DomainMap, Handover, load_domain_map, load_handover
from ..ledger import Ledger

_MISSING = object()


class GateContext:
    def __init__(self, root: Path, cfg: Any, feature_dir: Optional[Path], *, ci: bool = False,
                 write: bool = True, iteration: Optional[int] = None, max_iterations: Optional[int] = None):
        self.root = root
        self.cfg = cfg
        self.feature_dir = feature_dir
        self.ci = ci
        self.write = write and not ci
        self.iteration = iteration
        self.max_iterations = max_iterations
        self._cache: Dict[str, Any] = {}

    # ------------------------------------------------------------- helpers
    def _memo(self, key: str, fn):
        if key not in self._cache:
            try:
                self._cache[key] = fn()
            except ArchiGuardError as exc:
                self._cache[key] = exc
        value = self._cache[key]
        if isinstance(value, ArchiGuardError):
            raise value
        return value

    @property
    def feature(self) -> str:
        return rel_path(self.feature_dir, self.root) if self.feature_dir else "-"

    @property
    def gates_dir(self) -> Path:
        if self.feature_dir is None:
            raise ArchiGuardError("no feature directory")
        return self.feature_dir / GATES_DIRNAME

    def feature_file(self, name: str) -> Path:
        if self.feature_dir is None:
            raise ArchiGuardError("no feature directory")
        return self.feature_dir / name

    def require_file(self, name: str) -> str:
        path = self.feature_file(name)
        if not path.is_file():
            raise ArchiGuardError(f"{rel_path(path, self.root)} does not exist")
        return read_text(path)

    def today(self):
        return today(ci=self.ci)

    # ------------------------------------------------------------ artefacts
    @property
    def spec_text(self) -> str:
        return self._memo("spec", lambda: self.require_file("spec.md"))

    def label(self, item: str) -> str:
        """An id as the specification writes it (AC-001), for the canonical form the checks compare (AC-1)."""
        def _build() -> Dict[str, str]:
            labels: Dict[str, str] = {}
            sources = []
            if self.feature_dir is not None:
                for name in ("spec.md", self.cfg["feature"]["handover"]):
                    path = self.feature_dir / name
                    if path.is_file():
                        sources.append(read_text(path))
            for text in sources:
                for m in re.finditer(r"(?<![A-Za-z0-9_-])([A-Za-z]{1,6}-\d+)(?![A-Za-z0-9_])", text):
                    labels.setdefault(normalize_id(m.group(1)), m.group(1))
            return labels
        return self._memo("id_labels", _build).get(item, item)

    @property
    def handover(self) -> Optional[Handover]:
        return self._memo("handover", lambda: load_handover(self.feature_dir, self.cfg["feature"]["handover"]) if self.feature_dir else None)

    def require_handover(self) -> Handover:
        h = self.handover
        if h is None:
            raise ArchiGuardError(
                f"no handover record {self.cfg['feature']['handover']} in {self.feature} - A0 needs the formal "
                "handover from the BA specification tool to Spec Kit (template: templates/handover-template.yml)"
            )
        return h

    @property
    def domain_map(self) -> Optional[DomainMap]:
        def _load():
            path = self.cfg.path("domain", "map")
            if path is None or not path.is_file():
                return None
            return load_domain_map(path)
        return self._memo("domain_map", _load)

    def require_domain_map(self) -> DomainMap:
        dm = self.domain_map
        if dm is None:
            load_domain_map(self.cfg.path("domain", "map"))  # raises with the explanation
        problems = dm.problems()
        if problems:
            raise ArchiGuardError(f"the domain map {dm.path} is not valid: {problems[0]}")
        return dm

    @property
    def lock(self) -> Dict[str, Any]:
        def _load():
            lock = standards.read_lock(self.cfg.path("standards", "lock"))
            stale = standards.lock_is_current(lock, self.cfg)
            if stale:
                raise ArchiGuardError(stale)
            return lock
        return self._memo("lock", _load)

    @property
    def ledger(self) -> Ledger:
        return self._memo("ledger", lambda: Ledger.load(self.cfg.path("ledger", "path")))

    @property
    def stacks(self) -> List[str]:
        def _detect():
            try:
                markers = self.lock.get("stacks") or standards.DEFAULT_STACK_MARKERS
            except ArchiGuardError:
                markers = standards.DEFAULT_STACK_MARKERS
            return standards.detect_stacks(self.root, markers, self.cfg["stack"])
        return self._memo("stacks", _detect)

    @property
    def home_context(self) -> Optional[str]:
        h = self.handover
        if h is None:
            return None
        return h.home_context()[0]

    @property
    def applicable(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
        return self._memo("applicable", lambda: standards.applicable_rules(self.lock, self.stacks, self.home_context))

    @property
    def evaluator(self) -> Evaluator:
        def _make():
            excludes = self.cfg.option("A4.4", "exclude", []) or []
            return Evaluator(self.root, self.feature_dir, domain_map_loader=lambda: self.domain_map,
                             extra_excludes=excludes)
        return self._memo("evaluator", _make)

    @property
    def signoff(self) -> Optional[Dict[str, Any]]:
        def _load():
            if self.feature_dir is None:
                return None
            path = self.gates_dir / "signoff.json"
            if not path.is_file():
                return None
            try:
                return json.loads(read_text(path))
            except ValueError:
                raise ArchiGuardError(f"{rel_path(path, self.root)} is not valid JSON")
        return self._memo("signoff", _load)

    def waiver(self, rule: str) -> Optional[Dict[str, Any]]:
        return self.ledger.waiver_for(rule, self.today(), feature=self.feature, context=self.home_context)

    # ---------------------------------------------------------------- pins
    def head(self) -> Tuple[Optional[str], bool]:
        return self._memo("head", lambda: git_head(self.root))

    def spec_hash(self) -> Optional[str]:
        return sha256_file(self.feature_file("spec.md")) if self.feature_dir else None

    def pins(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"rulebook": None, "lock": None, "domain_map": None, "spec": None}
        try:
            lock = self.lock
            rb = lock.get("rulebook") or {}
            out["rulebook"] = f"{rb.get('name')}@{rb.get('tag')}"
            out["lock"] = standards.lock_hash(lock)
        except ArchiGuardError:
            pass
        try:
            dm = self.domain_map
            out["domain_map"] = dm.version if dm else None
        except ArchiGuardError:
            pass
        if self.feature_dir is not None and self.feature_file("spec.md").is_file():
            version = None
            try:
                version = self.handover.spec_version if self.handover else None
            except ArchiGuardError:
                version = None
            out["spec"] = f"{version or '-'}#{self.spec_hash()}"
        return out

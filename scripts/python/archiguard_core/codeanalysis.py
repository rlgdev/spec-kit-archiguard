"""Deterministic evaluation of the check kinds declared in the rulebook (graph-free provider).

Imports are extracted per language with plain parsing; no build, no network, no model.
"""

from __future__ import annotations

import json
import posixpath
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import yamlio
from .common import (
    DEFAULT_SCAN_EXCLUDES,
    ArchiGuardError,
    find_section,
    glob_match,
    parse_tasks,
    read_text,
    walk_files,
)
from .verdict import BLOCKING, Finding

MAX_FINDINGS_PER_CHECK = 25

LANGUAGES: Dict[str, Tuple[str, ...]] = {
    "java": (".java", ".kt", ".kts", ".scala", ".groovy"),
    "js": (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"),
    "python": (".py",),
    "csharp": (".cs",),
    "go": (".go",),
    "cobol": (".cbl", ".cob", ".cpy", ".CBL", ".COB", ".CPY"),
}
EXT_LANG = {ext: lang for lang, exts in LANGUAGES.items() for ext in exts}

_JAVA_IMPORT = re.compile(r"^[ \t]*import\s+(?:static\s+)?([A-Za-z_][\w.]*(?:\.\*)?)\s*;?", re.M)
_JS_IMPORT = re.compile(
    r"""(?:\bimport\s+(?:type\s+)?(?:[\w*{}\s,$]+?\s+from\s+)?|\bexport\s+(?:type\s+)?[\w*{}\s,$]+?\s+from\s+|\brequire\(\s*|\bimport\(\s*)['"]([^'"\n]+)['"]""",
    re.M,
)
_PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+([\w.]+(?:[ \t]*,[ \t]*[\w.]+)*)|^[ \t]*from\s+(\.*[\w.]*)\s+import\b", re.M)
_CS_USING = re.compile(r"^[ \t]*(?:global\s+)?using\s+(?:static\s+)?(?:\w+\s*=\s*)?([A-Za-z_][\w.]*)\s*;", re.M)
_GO_SINGLE = re.compile(r'^[ \t]*import\s+(?:\w+\s+)?"([^"]+)"', re.M)
_GO_BLOCK = re.compile(r"^[ \t]*import\s*\((.*?)\)", re.M | re.S)
_COBOL = re.compile(r"\b(?:COPY\s+['\"]?([\w-]+)|CALL\s+['\"]([\w-]+)['\"])", re.I)


def language_of(path: str) -> Optional[str]:
    return EXT_LANG.get(Path(path).suffix)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def extract_imports(path: str, text: str) -> List[Tuple[str, int]]:
    """(import specifier, line) pairs."""
    lang = language_of(path)
    out: List[Tuple[str, int]] = []
    if lang == "java":
        for m in _JAVA_IMPORT.finditer(text):
            out.append((m.group(1), _line_of(text, m.start())))
    elif lang == "js":
        for m in _JS_IMPORT.finditer(text):
            out.append((m.group(1), _line_of(text, m.start())))
    elif lang == "python":
        for m in _PY_IMPORT.finditer(text):
            if m.group(1):
                for part in m.group(1).split(","):
                    out.append((part.strip(), _line_of(text, m.start())))
            elif m.group(2) is not None:
                out.append((m.group(2), _line_of(text, m.start())))
    elif lang == "csharp":
        for m in _CS_USING.finditer(text):
            out.append((m.group(1), _line_of(text, m.start())))
    elif lang == "go":
        for m in _GO_SINGLE.finditer(text):
            out.append((m.group(1), _line_of(text, m.start())))
        for m in _GO_BLOCK.finditer(text):
            base = _line_of(text, m.start())
            for k, line in enumerate(m.group(1).split("\n")):
                mm = re.search(r'"([^"]+)"', line)
                if mm:
                    out.append((mm.group(1), base + k))
    elif lang == "cobol":
        for m in _COBOL.finditer(text):
            out.append(((m.group(1) or m.group(2)).upper(), _line_of(text, m.start())))
    return out


def resolve_relative(spec: str, file_rel: str) -> Optional[str]:
    """Repository path a relative import points at (JS './x', Python '.x'), or None for module imports."""
    if spec.startswith("./") or spec.startswith("../"):
        return posixpath.normpath(posixpath.join(posixpath.dirname(file_rel), spec))
    if spec.startswith(".") and language_of(file_rel) == "python":
        dots = len(spec) - len(spec.lstrip("."))
        rest = spec.lstrip(".").replace(".", "/")
        base = posixpath.dirname(file_rel)
        for _ in range(dots - 1):
            base = posixpath.dirname(base)
        return posixpath.normpath(posixpath.join(base, rest)) if rest else base
    return None


class Evaluator:
    """Runs declared checks against the feature directory or the repository."""

    def __init__(self, root: Path, feature_dir: Optional[Path], *, domain_map_loader: Callable[[], Any],
                 extra_excludes: Sequence[str] = ()):
        self.root = root
        self.feature_dir = feature_dir
        self._domain_map_loader = domain_map_loader
        self._extra_excludes = list(extra_excludes)
        self._repo_files: Optional[List[str]] = None
        self._texts: Dict[str, str] = {}

    # ----------------------------------------------------------------- files
    def repo_files(self) -> List[str]:
        if self._repo_files is None:
            self._repo_files = list(walk_files(self.root, DEFAULT_SCAN_EXCLUDES, self._extra_excludes))
        return self._repo_files

    def feature_files(self) -> List[str]:
        if self.feature_dir is None or not self.feature_dir.is_dir():
            return []
        return list(walk_files(self.feature_dir, (".git", "gates", "__pycache__")))

    def text(self, base: Path, rel: str) -> str:
        key = str(base / rel)
        if key not in self._texts:
            try:
                self._texts[key] = read_text(base / rel)
            except ArchiGuardError:
                self._texts[key] = ""
        return self._texts[key]

    def base_for(self, check: Dict[str, Any]) -> Tuple[Path, List[str]]:
        where = check.get("root")
        if where is None:
            where = "repo" if check.get("target") in ("code", "edit") else "feature"
        if where == "feature":
            if self.feature_dir is None:
                raise ArchiGuardError("this check needs a feature directory")
            return self.feature_dir, self.feature_files()
        return self.root, self.repo_files()

    # ------------------------------------------------------------------ run
    def run(self, rule: Dict[str, Any], check: Dict[str, Any], only_files: Optional[Sequence[str]] = None) -> List[Finding]:
        kind = check.get("kind")
        fn = getattr(self, f"_k_{kind}", None)
        if fn is None:
            raise ArchiGuardError(f"rule {rule.get('id')}: unknown check kind {kind!r}")
        findings: List[Finding] = fn(rule, check, only_files)
        if len(findings) > MAX_FINDINGS_PER_CHECK:
            extra = len(findings) - MAX_FINDINGS_PER_CHECK
            findings = findings[:MAX_FINDINGS_PER_CHECK]
            findings.append(Finding(rule=rule["id"], message=f"... and {extra} more finding(s) of the same check",
                                    severity=findings[0].severity))
        return findings

    def _finding(self, rule: Dict[str, Any], check: Dict[str, Any], message: str, where: Optional[str] = None,
                 fix: Optional[str] = None) -> Finding:
        severity = BLOCKING if rule.get("level") == "must" else "advisory"
        msg = check.get("message")
        text = f"{msg} - {message}" if msg else message
        return Finding(rule=rule["id"], message=text, severity=severity, where=where,
                       fix_hint=check.get("fix_hint") or fix,
                       excerpt=(rule.get("text") or None))

    def _scoped(self, files: List[str], check: Dict[str, Any], only_files: Optional[Sequence[str]],
                default: Sequence[str] = ()) -> List[str]:
        patterns = check.get("files")
        if isinstance(patterns, str):
            patterns = [patterns]
        patterns = list(patterns or default)
        chosen = [f for f in files if (not patterns or glob_match(f, patterns))]
        excepts = check.get("except_files") or []
        if isinstance(excepts, str):
            excepts = [excepts]
        if excepts:
            chosen = [f for f in chosen if not glob_match(f, excepts)]
        if only_files is not None:
            allowed = set(only_files)
            chosen = [f for f in chosen if f in allowed]
        return chosen

    # ----------------------------------------------------------- the kinds
    def _k_require_file(self, rule, check, only_files):
        base, files = self.base_for(check)
        if self._scoped(files, check, None):
            return []
        return [self._finding(rule, check, f"no file matches {', '.join(_as_list(check['files']))}",
                              where=_label(base, self.root),
                              fix=f"create the file the rule requires ({', '.join(_as_list(check['files']))})")]

    def _k_require_text(self, rule, check, only_files):
        base, files = self.base_for(check)
        chosen = self._scoped(files, check, None)
        rx = re.compile(check["pattern"])
        if not chosen:
            return [self._finding(rule, check, f"no file matches {', '.join(_as_list(check['files']))}",
                                  where=_label(base, self.root))]
        hits = [f for f in chosen if rx.search(self.text(base, f))]
        if check.get("mode") == "each":
            return [self._finding(rule, check, f"/{check['pattern']}/ not found", where=_where(base, self.root, f))
                    for f in chosen if f not in hits]
        if not hits:
            return [self._finding(rule, check, f"/{check['pattern']}/ not found in {', '.join(chosen[:5])}"
                                  + (" ..." if len(chosen) > 5 else ""), where=_label(base, self.root))]
        return []

    def _k_forbid_text(self, rule, check, only_files):
        base, files = self.base_for(check)
        rx = re.compile(check["pattern"], re.M)
        out = []
        for f in self._scoped(files, check, only_files):
            text = self.text(base, f)
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                snippet = m.group(0).strip()[:80]
                out.append(self._finding(rule, check, f"forbidden text '{snippet}'", where=_where(base, self.root, f, line),
                                         fix="remove or replace the forbidden construct"))
        return out

    def _k_require_section(self, rule, check, only_files):
        if self.feature_dir is None:
            raise ArchiGuardError("require_section needs a feature directory")
        default = "tasks.md" if check.get("target") == "tasks" else "plan.md"
        name = check.get("file") or default
        path = self.feature_dir / name
        if not path.is_file():
            return [self._finding(rule, check, f"{name} does not exist", where=name)]
        if find_section(read_text(path), check["heading"]) is None:
            return [self._finding(rule, check, f"{name} has no section matching /{check['heading']}/", where=name,
                                  fix=f"add the section the rule requires to {name}")]
        return []

    def _k_require_task(self, rule, check, only_files):
        if self.feature_dir is None:
            raise ArchiGuardError("require_task needs a feature directory")
        path = self.feature_dir / "tasks.md"
        if not path.is_file():
            return [self._finding(rule, check, "tasks.md does not exist", where="tasks.md")]
        pattern = check.get("pattern") or rf"\b{re.escape(rule['id'])}\b"
        rx = re.compile(pattern)
        if any(rx.search(t.text) for t in parse_tasks(read_text(path))):
            return []
        return [self._finding(rule, check, f"no task in tasks.md matches /{pattern}/", where="tasks.md",
                              fix=f"add a task that implements or verifies {rule['id']} and names it")]

    def _imports(self, base: Path, files: List[str]) -> Iterable[Tuple[str, str, int]]:
        for f in files:
            if language_of(f) is None:
                continue
            for spec, line in extract_imports(f, self.text(base, f)):
                yield f, spec, line

    def _k_forbid_import(self, rule, check, only_files):
        base, files = self.base_for(check)
        patterns = [re.compile(p) for p in _as_list(check["imports"])]
        out = []
        for f, spec, line in self._imports(base, self._scoped(files, check, only_files)):
            target = resolve_relative(spec, f) or spec
            if any(p.search(spec) or p.search(target) for p in patterns):
                out.append(self._finding(rule, check, f"forbidden import '{spec}'", where=_where(base, self.root, f, line),
                                         fix="depend on an allowed module instead"))
        return out

    def _k_layers(self, rule, check, only_files):
        base, files = self.base_for(check)
        layers = check["layers"]
        allow = {str(k): set(_as_list(v)) for k, v in (check.get("allow") or {}).items()}

        def layer_of_file(path: str) -> Optional[str]:
            for layer in layers:
                if layer.get("files") and glob_match(path, _as_list(layer["files"])):
                    return str(layer["name"])
            return None

        def layer_of_import(spec: str, resolved: Optional[str]) -> Optional[str]:
            for layer in layers:
                if resolved is not None and layer.get("files") and (
                    glob_match(resolved, _as_list(layer["files"])) or
                    any(glob_match(resolved + ext, _as_list(layer["files"])) for ext in (".ts", ".js", ".py", ".tsx", ".jsx"))
                ):
                    return str(layer["name"])
                if any(re.search(p, spec) for p in _as_list(layer.get("modules"))):
                    return str(layer["name"])
            return None

        same_context = check.get("scope") == "context"
        dm = self._domain_map_loader() if same_context else None
        if same_context and dm is None:
            raise ArchiGuardError("layers with scope: context needs the domain map (domain.map)")
        out = []
        for f, spec, line in self._imports(base, self._scoped(files, check, only_files)):
            src = layer_of_file(f)
            if src is None:
                continue
            resolved = resolve_relative(spec, f)
            if same_context:
                own = dm.context_of_path(f)
                other = dm.context_of_path(resolved) if resolved else dm.context_of_module(spec)
                if own is None or other != own:
                    continue  # dependencies between contexts are the context-boundary rule's business
            dst = layer_of_import(spec, resolved)
            if dst is None or dst == src:
                continue
            if dst not in allow.get(src, set()):
                out.append(self._finding(
                    rule, check, f"layer '{src}' must not depend on layer '{dst}' (import '{spec}')",
                    where=_where(base, self.root, f, line),
                    fix=f"'{src}' may depend on: {', '.join(sorted(allow.get(src, set()))) or 'no other layer'}",
                ))
        return out

    def _k_context_boundaries(self, rule, check, only_files):
        dm = self._domain_map_loader()
        if dm is None:
            raise ArchiGuardError("context_boundaries needs the domain map (domain.map)")
        if not any(c.code for c in dm.contexts.values()):
            raise ArchiGuardError("context_boundaries: no context in the domain map declares its 'code' paths")
        base, files = self.base_for(check)
        out = []
        for f, spec, line in self._imports(base, self._scoped(files, check, only_files)):
            src = dm.context_of_path(f)
            if src is None:
                continue
            resolved = resolve_relative(spec, f)
            dst = dm.context_of_path(resolved) if resolved else dm.context_of_module(spec)
            if dst is None or dst == src:
                continue
            relation = dm.allows(src, dst)
            if relation is None:
                out.append(self._finding(
                    rule, check, f"context '{src}' depends on context '{dst}' (import '{spec}') but the domain map has no relation {src} -> {dst}",
                    where=_where(base, self.root, f, line),
                    fix="go through an allowed relation, or propose the relation to the lead architect (domain change)",
                ))
            elif check.get("published_only", True) and not dm.is_published(dst, None if resolved else spec, resolved):
                out.append(self._finding(
                    rule, check, f"'{spec}' is not part of the published interface of context '{dst}'",
                    where=_where(base, self.root, f, line),
                    fix=f"use what '{dst}' publishes: {', '.join(dm.contexts[dst].published)}",
                ))
        return out

    def _k_contract_routes(self, rule, check, only_files):
        if self.feature_dir is None:
            raise ArchiGuardError("contract_routes needs a feature directory")
        patterns = _as_list(check.get("contracts") or ["contracts/**/*.{yaml,yml,json}"])
        contract_files = [f for f in walk_files(self.feature_dir, (".git", "gates")) if glob_match(f, patterns)]
        sources = [f for f in self.repo_files() if glob_match(f, _as_list(check["sources"]))]
        corpus = [(f, self.text(self.root, f)) for f in sources]
        out = []
        for cf in contract_files:
            try:
                raw = read_text(self.feature_dir / cf)
                doc = json.loads(raw) if cf.endswith(".json") else yamlio.loads(raw, cf)
            except (ValueError, ArchiGuardError):
                continue
            paths = (doc or {}).get("paths") if isinstance(doc, dict) else None
            if not isinstance(paths, dict):
                continue
            for route in paths:
                rx = _route_regex(str(route))
                if not any(rx.search(text) for _, text in corpus):
                    out.append(self._finding(
                        rule, check, f"route {route} from {cf} is not implemented in {', '.join(_as_list(check['sources']))}",
                        where=_label(self.feature_dir / cf, self.root),
                        fix=f"implement {route} or correct the contract (contract changes need the design authority)",
                    ))
        return out

    def _k_readonly(self, rule, check, only_files):
        return []  # enforced by the edit guard on PreToolUse; A4.1 compares design hashes with the sign-off

    def _k_command(self, rule, check, only_files):
        run = check["run"]
        timeout = int(check.get("timeout") or 600)
        try:
            if check.get("shell"):
                proc = subprocess.run(str(run), shell=True, cwd=str(self.root), capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
            else:
                argv = [str(a) for a in (run if isinstance(run, list) else shlex.split(str(run)))]
                proc = subprocess.run(argv, cwd=str(self.root), capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return [self._finding(rule, check, f"command timed out after {timeout}s: {run}")]
        except OSError as exc:
            raise ArchiGuardError(f"rule {rule['id']}: cannot run {run}: {exc}")
        if proc.returncode == 0:
            return []
        tail = "\n".join((proc.stdout + proc.stderr).strip().split("\n")[-15:])
        finding = self._finding(rule, check, f"command failed (exit {proc.returncode}): {run}")
        finding.excerpt = tail or finding.excerpt
        return [finding]


def _route_regex(route: str) -> "re.Pattern[str]":
    parts = re.split(r"(\{[^}]+\})", route)
    out = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            out.append(r"(?:\{[^}/]*\}|:\w+|<[^>/]*>|\$\{[^}]*\}|\[[^\]/]*\]|\*)")
        else:
            out.append(re.escape(part))
    return re.compile("".join(out) + r"(?![\w-])")


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _label(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _where(base: Path, root: Path, rel: str, line: Optional[int] = None) -> str:
    label = _label(base / rel, root)
    return f"{label}:{line}" if line else label

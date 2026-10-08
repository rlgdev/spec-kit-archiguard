"""Shared helpers: errors, exit codes, paths, hashing, globbing, git and Markdown parsing."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# Exit codes (the gate contract)                                                #
# --------------------------------------------------------------------------- #

EXIT_PASS = 0       # pass, or only waived / advisory findings
EXIT_FAIL = 1       # at least one blocking violation the maker can repair
EXIT_ERROR = 2      # cannot evaluate: missing input, unpinned policy, parse error (fail-closed)
EXIT_ESCALATE = 3   # escalated: still red at the budget, or a finding no agent may repair

SPECIFY_DIR = Path(".specify")
EXTENSION_ID = "archiguard"
EXTENSION_REL = SPECIFY_DIR / "extensions" / EXTENSION_ID
CONFIG_REL = EXTENSION_REL / "archiguard-config.yml"
LOCAL_CONFIG_RELS = (EXTENSION_REL / "local-config.yml", EXTENSION_REL / "archiguard-config.local.yml")
EXTENSIONS_YML = SPECIFY_DIR / "extensions.yml"
PRESET_ID = "archiguard-templates"
PRESET_REL = SPECIFY_DIR / "presets" / PRESET_ID
WRAPPED_COMMANDS = ("speckit.plan", "speckit.tasks", "speckit.implement")
GATES_DIRNAME = "gates"          # per-feature evidence directory: specs/<feature>/gates/

# Root of the installed extension (or of the repository during development):
# .../scripts/python/archiguard_core/common.py -> parents[3]
ENGINE_ROOT = Path(__file__).resolve().parents[3]


class ArchiGuardError(Exception):
    """Setup, policy or usage problem: the gate cannot evaluate (exit code 2)."""


# --------------------------------------------------------------------------- #
# Environment                                                                   #
# --------------------------------------------------------------------------- #


def env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def is_ci_environment() -> bool:
    """True on a CI runner (GitHub Actions, Bitbucket Pipelines, GitLab, Jenkins set CI)."""
    return env_true("CI") or env_true("ARCHIGUARD_CI")


def today(ci: bool = False) -> _dt.date:
    """Today's date. ARCHIGUARD_TODAY (YYYY-MM-DD) is honoured on workstations only, never in CI."""
    override = os.environ.get("ARCHIGUARD_TODAY", "").strip()
    if override and not ci and not is_ci_environment():
        try:
            return _dt.date.fromisoformat(override)
        except ValueError:
            raise ArchiGuardError(f"ARCHIGUARD_TODAY must be YYYY-MM-DD, got {override!r}")
    return _dt.date.today()


def parse_date(value: Any) -> Optional[_dt.date]:
    if value is None or value == "":
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Files and hashing                                                             #
# --------------------------------------------------------------------------- #


def read_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ArchiGuardError(f"cannot read {path}: {exc}")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def line_ending(path: Path) -> str:
    """The line ending most lines of an existing file use (CRLF or LF; LF on a tie). A rewrite of a file another tool
    owns (Spec Kit writes .specify/extensions.yml with the platform's ending) keeps it, so git shows only the edited
    lines."""
    try:
        data = path.read_bytes()
        return "\r\n" if 2 * data.count(b"\r\n") > data.count(b"\n") else "\n"
    except OSError:
        return "\n"


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> Optional[str]:
    """Hash of a text file with normalised line endings (stable across Windows checkouts)."""
    if not path.is_file():
        return None
    return sha256_text(read_text(path))


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256_json(data: Any) -> str:
    return sha256_text(canonical_json(data))


def rel_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# --------------------------------------------------------------------------- #
# Globbing ("**" aware, brace expansion)                                        #
# --------------------------------------------------------------------------- #

DEFAULT_SCAN_EXCLUDES = (
    ".git", ".hg", ".svn", "node_modules", "target", "build", "dist", "out", ".gradle", ".mvn",
    ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", ".idea", ".vscode",
    ".specify", ".claude", ".github", "specs", "bin", "obj", "coverage", ".next", ".nuxt",
    "graphify-out", ".terraform",
)

_GLOB_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _expand_braces(pattern: str) -> List[str]:
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    out: List[str] = []
    for option in match.group(1).split(","):
        out.extend(_expand_braces(pattern[: match.start()] + option + pattern[match.end():]))
    return out


def _glob_to_regex(pattern: str) -> str:
    i, n, out = 0, len(pattern), []
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i:i + 2] == "**":
                # "**/" = zero or more directories; a trailing "**" = everything below
                if pattern[i:i + 3] == "**/":
                    out.append("(?:.*/)?")
                    i += 3
                else:
                    out.append(".*")
                    i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
                i += 1
            else:
                body = pattern[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def compile_glob(pattern: str) -> "re.Pattern[str]":
    cached = _GLOB_CACHE.get(pattern)
    if cached is not None:
        return cached
    pat = pattern.strip().replace("\\", "/")
    while pat.startswith("./"):
        pat = pat[2:]
    alternatives = [_glob_to_regex(p) for p in _expand_braces(pat)]
    compiled = re.compile("^(?:" + "|".join(alternatives) + ")$")
    _GLOB_CACHE[pattern] = compiled
    return compiled


def glob_match(path: str, patterns: Iterable[str]) -> bool:
    p = path.replace("\\", "/")
    return any(compile_glob(g).match(p) for g in patterns)


def walk_files(base: Path, excludes: Sequence[str] = DEFAULT_SCAN_EXCLUDES,
               extra_exclude_globs: Sequence[str] = ()) -> Iterator[str]:
    """Yield POSIX paths (relative to base) of regular files, skipping excluded directory names."""
    exclude_names = set(excludes)
    base = base.resolve()
    for current, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in exclude_names)
        rel_dir = Path(current).relative_to(base).as_posix()
        for name in sorted(files):
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if extra_exclude_globs and glob_match(rel, extra_exclude_globs):
                continue
            yield rel


def files_matching(base: Path, patterns: Sequence[str], excludes: Sequence[str] = DEFAULT_SCAN_EXCLUDES,
                   extra_exclude_globs: Sequence[str] = ()) -> List[str]:
    if not patterns or not base.is_dir():
        return []
    return [f for f in walk_files(base, excludes, extra_exclude_globs) if glob_match(f, patterns)]


# --------------------------------------------------------------------------- #
# git                                                                           #
# --------------------------------------------------------------------------- #


def git(root: Path, *args: str, timeout: int = 60) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout if proc.returncode == 0 else (proc.stderr or proc.stdout))


def git_head(root: Path) -> Tuple[Optional[str], bool]:
    code, out = git(root, "rev-parse", "HEAD")
    if code != 0:
        return None, False
    head = out.strip()
    code, status = git(root, "status", "--porcelain")
    return head, bool(code == 0 and status.strip())


def git_branch(root: Path) -> str:
    code, out = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if code == 0 else ""


# --------------------------------------------------------------------------- #
# Project and feature resolution                                                #
# --------------------------------------------------------------------------- #


def find_project_root(explicit: Optional[str] = None) -> Path:
    if explicit:
        root = Path(explicit).resolve()
        if not root.is_dir():
            raise ArchiGuardError(f"--root {explicit} is not a directory")
        return root
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / SPECIFY_DIR).is_dir():
            return candidate
    return here


def feature_dirs(root: Path) -> List[Path]:
    specs = root / "specs"
    if not specs.is_dir():
        return []
    return sorted(p for p in specs.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def resolve_feature_dir(root: Path, explicit: Optional[str] = None) -> Path:
    """The active feature, found the way Spec Kit finds it."""
    def _check(path: Path, source: str) -> Path:
        if not path.is_absolute():
            path = (root / path)
        path = path.resolve()
        if not path.is_dir():
            raise ArchiGuardError(f"feature directory from {source} does not exist: {path}")
        return path

    if explicit:
        p = Path(explicit)
        if not p.is_absolute() and not (root / p).exists() and (Path.cwd() / p).exists():
            p = Path.cwd() / p
        return _check(p, "--feature-dir")
    env = os.environ.get("SPECIFY_FEATURE_DIRECTORY", "").strip()
    if env:
        return _check(Path(env), "SPECIFY_FEATURE_DIRECTORY")
    pointer = root / SPECIFY_DIR / "feature.json"
    if pointer.is_file():
        try:
            data = json.loads(read_text(pointer))
            value = data.get("feature_directory") if isinstance(data, dict) else None
            if value:
                return _check(Path(value), ".specify/feature.json")
        except ValueError:
            pass
    dirs = feature_dirs(root)
    branch = git_branch(root)
    if branch:
        for d in dirs:
            if d.name == branch or branch.endswith("/" + d.name):
                return d.resolve()
        num = re.match(r"^(\d{3,})-", branch.split("/")[-1])
        if num:
            matches = [d for d in dirs if d.name.startswith(num.group(1) + "-")]
            if len(matches) == 1:
                return matches[0].resolve()
    if len(dirs) == 1:
        return dirs[0].resolve()
    if not dirs:
        raise ArchiGuardError("no feature directory found under specs/ (pass --feature-dir)")
    raise ArchiGuardError(
        "cannot tell which feature is active - pass --feature-dir specs/<feature> "
        "(or set SPECIFY_FEATURE_DIRECTORY)"
    )


# --------------------------------------------------------------------------- #
# Markdown                                                                      #
# --------------------------------------------------------------------------- #

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def strip_html_comments(text: str) -> str:
    """Remove <!-- --> comments but keep the line count (blank lines), so line numbers stay valid."""
    def _blank(match: "re.Match[str]") -> str:
        return "\n" * match.group(0).count("\n")
    return re.sub(r"<!--.*?-->", _blank, text, flags=re.S)


def heading(line: str) -> Optional[Tuple[int, str]]:
    m = _HEADING_RE.match(line)
    if not m:
        return None
    return len(m.group(1)), m.group(2).strip()


@dataclass
class Section:
    title: str
    level: int
    start: int          # 1-based line number of the heading
    end: int            # 1-based line number of the last line in the section
    lines: List[str]    # body lines (without the heading)


def sections(text: str) -> List[Section]:
    """Every heading-delimited section (fenced code is never treated as headings)."""
    lines = text.split("\n")
    heads: List[Tuple[int, int, str]] = []
    in_fence = False
    for idx, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = heading(line)
        if h:
            heads.append((idx, h[0], h[1]))
    out: List[Section] = []
    for k, (idx, level, title) in enumerate(heads):
        end = len(lines)
        for idx2, level2, _ in heads[k + 1:]:
            if level2 <= level:
                end = idx2
                break
        out.append(Section(title=title, level=level, start=idx + 1, end=end, lines=lines[idx + 1:end]))
    return out


def find_section(text: str, title_regex: str) -> Optional[Section]:
    rx = re.compile(title_regex, re.I)
    for sec in sections(text):
        if rx.search(sec.title):
            return sec
    return None


def split_row(line: str) -> List[str]:
    """Split a Markdown table row on unescaped pipes outside inline code."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, buf, in_code, i = [], [], False, 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


@dataclass
class Table:
    header: List[str]
    rows: List[Tuple[int, List[str]]]   # (1-based line number, cells)
    line: int                           # line of the header


def tables_in(lines: List[str], first_line: int = 1) -> List[Table]:
    """Tables in a list of lines; first_line = line number of lines[0]."""
    out: List[Table] = []
    i = 0
    in_fence = False
    while i < len(lines):
        if _FENCE_RE.match(lines[i]):
            in_fence = not in_fence
            i += 1
            continue
        if not in_fence and "|" in lines[i] and i + 1 < len(lines) and _SEPARATOR_RE.match(lines[i + 1]):
            header = [clean_cell(c) for c in split_row(lines[i])]
            table = Table(header=header, rows=[], line=first_line + i)
            j = i + 2
            while j < len(lines) and lines[j].strip() and "|" in lines[j] and not heading(lines[j]):
                table.rows.append((first_line + j, [clean_cell(c) for c in split_row(lines[j])]))
                j += 1
            out.append(table)
            i = j
            continue
        i += 1
    return out


def clean_cell(cell: str) -> str:
    c = cell.strip()
    c = re.sub(r"^\*\*(.*)\*\*$", r"\1", c)
    c = re.sub(r"^`(.*)`$", r"\1", c)
    return c.strip()


def column_index(header: List[str], *keywords: str) -> Optional[int]:
    for idx, name in enumerate(header):
        low = name.lower()
        if any(k in low for k in keywords):
            return idx
    return None


PLACEHOLDER_RE = re.compile(r"^\s*(<[^>]*>|\[[^\]]*\]|tbd|todo|\?+|-+|—|–|n/?a)\s*$", re.I)


def is_placeholder(value: str) -> bool:
    return not value.strip() or bool(PLACEHOLDER_RE.match(value))


@dataclass
class Task:
    line: int
    checked: bool
    text: str
    task_id: Optional[str]
    phase: str          # nearest heading above the task


_TASK_RE = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+(.*)$")
_TASK_ID_RE = re.compile(r"\bT\d{3,}\b")


def parse_tasks(text: str) -> List[Task]:
    tasks: List[Task] = []
    phase = ""
    in_fence = False
    for idx, line in enumerate(strip_html_comments(text).split("\n")):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = heading(line)
        if h:
            phase = h[1]
            continue
        m = _TASK_RE.match(line)
        if m:
            body = m.group(2).strip()
            tid = _TASK_ID_RE.search(body)
            tasks.append(Task(line=idx + 1, checked=m.group(1) in "xX", text=body,
                              task_id=tid.group(0) if tid else None, phase=phase))
    return tasks


# --------------------------------------------------------------------------- #
# Requirement IDs                                                               #
# --------------------------------------------------------------------------- #

DEFAULT_ID_PREFIXES = ("UC", "SC", "AC", "BR", "D", "FR", "NFR")


def id_regex(prefixes: Sequence[str], stories: bool = True) -> "re.Pattern[str]":
    alts = "|".join(re.escape(p) for p in sorted(set(prefixes), key=len, reverse=True))
    parts = []
    if alts:
        parts.append(rf"(?:{alts})-\d+")
    if stories:
        parts.append(r"US\d+")
    return re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(parts) + r")(?![A-Za-z0-9_])")


def normalize_id(token: str) -> str:
    m = re.match(r"^([A-Za-z]+)-?0*(\d+)$", token.strip())
    if not m:
        return token.strip().upper()
    prefix, number = m.group(1).upper(), m.group(2) or "0"
    if prefix == "US":
        return f"US{int(number)}"
    return f"{prefix}-{int(number)}"


def spec_ids(spec_text: str, prefixes: Sequence[str]) -> List[str]:
    """IDs a spec defines: '- **FR-001**:' definition lines, other bold IDs, and 'User Story N' headings."""
    text = strip_html_comments(spec_text)
    found: List[str] = []
    seen = set()
    rx = id_regex(prefixes, stories=False)
    for line in text.split("\n"):
        h = heading(line)
        if h:
            m = re.match(r"^(?:User\s+Story|US)\s*[-#:]?\s*(\d+)\b", h[1], re.I)
            if m:
                key = f"US{int(m.group(1))}"
                if key not in seen:
                    seen.add(key)
                    found.append(key)
        for m in re.finditer(r"\*\*([A-Za-z]+-\d+)\*\*", line):
            if rx.fullmatch(m.group(1)):
                key = normalize_id(m.group(1))
                if key not in seen:
                    seen.add(key)
                    found.append(key)
    return found


def ids_in(text: str, rx: "re.Pattern[str]") -> List[str]:
    out, seen = [], set()
    for m in rx.finditer(text):
        key = normalize_id(m.group(1))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


# --------------------------------------------------------------------------- #
# Versions                                                                      #
# --------------------------------------------------------------------------- #


def parse_version(text: str) -> Tuple[int, ...]:
    nums = re.findall(r"\d+", str(text).split("+")[0].split("-")[0])
    return tuple(int(n) for n in nums[:4]) if nums else (0,)


def version_satisfies(version: str, constraint: str) -> bool:
    """Minimal PEP 440-style range check: '>=0.3.0,<0.5', '==1.2.3', '~=1.4'."""
    if not constraint or not str(constraint).strip():
        return True
    v = parse_version(version)
    for clause in str(constraint).split(","):
        clause = clause.strip()
        m = re.match(r"^(>=|<=|==|!=|>|<|~=)?\s*([0-9][0-9A-Za-z.\-+]*)$", clause)
        if not m:
            raise ArchiGuardError(f"invalid version constraint {constraint!r}")
        op, target = m.group(1) or "==", parse_version(m.group(2))
        width = max(len(v), len(target))
        a = v + (0,) * (width - len(v))
        b = target + (0,) * (width - len(target))
        if op == ">=" and not a >= b:
            return False
        if op == "<=" and not a <= b:
            return False
        if op == ">" and not a > b:
            return False
        if op == "<" and not a < b:
            return False
        if op == "==" and not a == b:
            return False
        if op == "!=" and a == b:
            return False
        if op == "~=":
            if not a >= b:
                return False
            prefix = target[:-1] if len(target) > 1 else target
            if v[:len(prefix)] != prefix:
                return False
    return True

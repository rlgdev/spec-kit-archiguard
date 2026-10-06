"""Shared fixtures: a fresh copy of examples/orders in a git repository, and an in-process CLI runner."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / "scripts" / "python"
EXAMPLE = REPO / "examples" / "orders"
FEATURE = "specs/001-place-order"

if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from archiguard_core import cli  # noqa: E402

ENV_KEYS = (
    "CI", "ARCHIGUARD_CI", "ARCHIGUARD_INTEGRATION", "ARCHIGUARD_MAX_ITERATIONS", "ARCHIGUARD_MODE",
    "ARCHIGUARD_TODAY", "SPECIFY_FEATURE_DIRECTORY", "SPECIFY_FEATURE", "GITHUB_ACTIONS",
)


@pytest.fixture(autouse=True)
def _workstation_env(monkeypatch):
    """Tests run as on a workstation unless they opt into CI explicitly (CI=true is set on every runner)."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", message)


@pytest.fixture
def project(tmp_path) -> Path:
    """examples/orders without generated evidence, committed on main, checked out on the feature branch."""
    root = tmp_path / "orders"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("gates", "__pycache__"))
    git(root, "init", "-q")
    git(root, "config", "commit.gpgsign", "false")
    commit_all(root, "base")
    git(root, "branch", "-M", "main")
    git(root, "checkout", "-q", "-b", "001-place-order")
    return root


class Result:
    def __init__(self, code: int, out: str, err: str):
        self.code = code
        self.out = out
        self.err = err

    def __repr__(self) -> str:  # shown by pytest on a failed assertion
        return f"<exit {self.code}>\n--- stdout\n{self.out}\n--- stderr\n{self.err}"


@pytest.fixture
def ag(capsys):
    """Run the archiguard CLI in-process: ag(root, 'run', 'plan', 'b') -> Result."""
    def _run(root: Path, *args: str, feature: bool = True) -> Result:
        argv: List[str] = list(args)
        extra = ["--root", str(root)]
        if feature and "--feature-dir" not in argv:
            extra += ["--feature-dir", FEATURE]
        if argv and argv[0] == "loop" and "--" in argv:
            i = argv.index("--")
            argv = argv[:i] + extra + argv[i:]
        elif argv and argv[0] == "ledger":
            argv = argv[:2] + extra[:2] + argv[2:]
        else:
            argv = argv + extra
        capsys.readouterr()
        code = cli.run(argv)
        out, err = capsys.readouterr()
        return Result(code, out, err)
    return _run


def read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def edit(root: Path, rel: str, old: str, new: str) -> None:
    text = read(root, rel)
    assert old in text, f"{old!r} not in {rel}"
    write(root, rel, text.replace(old, new))


ARCH_201_ROW = ("| ARCH-201 | Layers depend downwards only (api -> application -> domain) | satisfied | "
                "Project Structure: api -> application -> domain | |")
ARCH_201_GAP = "<!-- ARCH-201 (layering) is missing on purpose: the A3.3 check-plan finds it. -->"


def repair_plan(root: Path) -> None:
    edit(root, f"{FEATURE}/plan.md", ARCH_201_GAP, ARCH_201_ROW)


def analyze_report(root: Path, critical: int = 0) -> None:
    rows = "| A1 | Terminology | LOW | plan.md | basket and cart both used | use basket |\n"
    if critical:
        rows += "| C1 | Coverage | CRITICAL | tasks.md | AC-002 has no task | add a task |\n"
    write(root, f"{FEATURE}/gates/analyze-report.md",
          "## Specification Analysis Report\n\n| ID | Category | Severity | Location(s) | Summary | Recommendation |\n"
          "|----|----------|----------|-------------|---------|----------------|\n" + rows
          + f"\n**Metrics:**\n- Critical Issues Count: {critical}\n")


def design_signed(ag, root: Path) -> None:
    """Repair the plan, run analyze, sign off and commit - the state Implement starts from."""
    repair_plan(root)
    analyze_report(root)
    commit_all(root, "T000 design for UC-001")
    r = ag(root, "signoff", "--by", "Lead architect")
    assert r.code == 0, r
    commit_all(root, "T000 design signed for UC-001")


__all__ = ["REPO", "ENGINE", "EXAMPLE", "FEATURE", "git", "commit_all", "read", "write", "edit", "repair_plan",
           "analyze_report", "design_signed", "ARCH_201_ROW", "ARCH_201_GAP"]

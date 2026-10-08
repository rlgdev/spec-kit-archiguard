"""archiguard command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .common import (
    EXIT_ERROR,
    EXIT_PASS,
    ArchiGuardError,
    find_project_root,
    resolve_feature_dir,
)
from .config import load_config, normalise_command


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="project root (default: nearest directory with .specify/)")
    common.add_argument("--config", help="config file (default: .specify/extensions/archiguard/archiguard-config.yml)")
    common.add_argument("--feature-dir", help="feature directory, e.g. specs/001-orders (default: the active feature)")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--verbose", "-v", action="store_true", help="more detail (rule text, advisory findings)")

    parser = argparse.ArgumentParser(
        prog="archiguard",
        description="archiGuard - architecture gates (A0 domain guard, A3 plan conformance, A4 fitness functions, "
                    "handover 4->5) for GitHub Spec Kit.",
    )
    parser.add_argument("--version", action="version", version=f"archiguard {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    p = sub.add_parser("run", parents=[common], help="run step A or B of a wrapped Spec Kit command (the runner owns the iteration counter)")
    p.add_argument("target", help="plan | tasks | implement (or speckit.plan, ...)")
    p.add_argument("step", choices=("a", "b", "A", "B"), help="a = after Setup, b = before the post-execution hooks")
    p.add_argument("--via", choices=("inline", "hook"), help="who calls: the wrapped command (inline) or a Spec Kit hook")

    p = sub.add_parser("verify", parents=[common], help="every gate plugged into a command, once (workflow shell gate)")
    p.add_argument("target", help="plan | tasks | implement")

    p = sub.add_parser("check", parents=[common], help="run single checks of one gate (plug-in contract invocation)")
    p.add_argument("gate", help="A0 | A3 | A4 | H | a registered gate")
    p.add_argument("checks", nargs="+", help="check ids, e.g. A3.3 A3.7")
    p.add_argument("--iteration", type=int, help="iteration number recorded in the verdicts")

    sub.add_parser("rules", parents=[common], help="A3.1: the rules that apply to the feature (writes gates/applicable-rules.json)")

    p = sub.add_parser("resolve", parents=[common], help="resolve the standards into standards.lock.yml")
    p.add_argument("--check", action="store_true", help="only compare with the committed lock (exit 1 on drift)")

    p = sub.add_parser("validate-standards", parents=[common], help="lint a rulebook (for the standards repository's CI)")
    p.add_argument("path", nargs="?", help="rulebook directory (default: standards.path)")

    p = sub.add_parser("signoff", parents=[common], help="record the design authority sign-off (refused unless the design evidence is green)")
    p.add_argument("--by", required=True, help="name of the design authority")
    p.add_argument("--role", default="design authority (tech lead)", help="role of the person signing")

    p = sub.add_parser("reopen", parents=[common], help="re-open a signed design (the sign-off moves to the history)")
    p.add_argument("--by", required=True)
    p.add_argument("--reason", required=True)

    sub.add_parser("handover", parents=[common], help="handover 4 -> 5: entry checks H1-H6 and the test-handover manifest")

    p = sub.add_parser("test", parents=[common], help="the deterministic test loop: run the tests, trace the ids in the JUnit reports")
    p.add_argument("--no-run", action="store_true", help="only read existing JUnit reports")

    p = sub.add_parser("loop", parents=[common], help="bounded loop counter for workflow loops: loop NAME -- <archiguard command>")
    p.add_argument("name", help="loop name from 'loops:' in the config")
    p.add_argument("--reset", action="store_true")
    p.add_argument("--status", action="store_true")

    p = sub.add_parser("report", parents=[common], help="architecture compliance report for the feature")
    p.add_argument("--save", action="store_true", help="write gates/architecture-compliance.md")
    p.add_argument("--out", help="also write the Markdown report to this file")

    p = sub.add_parser("ci", parents=[common], help="CI required check: lock drift, ledger, every plugged gate once")
    p.add_argument("--all", action="store_true", help="every feature under specs/ (default when no --feature-dir)")
    p.add_argument("--implement", action="store_true", help="also verify implement for features without a sign-off")
    p.add_argument("--junit", help="write a JUnit XML report")
    p.add_argument("--out", help="write a Markdown summary (e.g. the CI job summary)")

    p = sub.add_parser("ledger", help="the decision ledger: verify | list | add | revoke")
    lsub = p.add_subparsers(dest="action", metavar="ACTION")
    lsub.required = True
    lsub.add_parser("verify", parents=[common])
    lsub.add_parser("list", parents=[common])
    la = lsub.add_parser("add", parents=[common])
    la.add_argument("--id", required=True)
    la.add_argument("--type", required=True, choices=("adr", "waiver", "cldd", "secd", "datd"))
    la.add_argument("--title", required=True)
    la.add_argument("--rule", action="append", help="rule id (repeat for several)")
    la.add_argument("--owner", required=True)
    la.add_argument("--approver")
    la.add_argument("--expires", help="YYYY-MM-DD")
    la.add_argument("--evidence")
    la.add_argument("--status", default="proposed", choices=("proposed", "approved"),
                    help="approved only by the approver named in --approver (default: proposed)")
    la.add_argument("--feature", action="append", help="limit the waiver to a feature directory name")
    la.add_argument("--context", action="append", help="limit the waiver to a bounded context")
    lr = lsub.add_parser("revoke", parents=[common])
    lr.add_argument("--id", required=True)
    lr.add_argument("--by", required=True)

    p = sub.add_parser("configure", parents=[common], help="apply the config to Spec Kit's hooks and show what is in force")
    p.add_argument("--dry-run", action="store_true")

    sub.add_parser("edit-guard", parents=[common], help="A4.2 hook: reads the agent's tool payload on stdin")

    p = sub.add_parser("scaffold", parents=[common], help="write a starting file: domain-map | handover | rulebook")
    p.add_argument("what", choices=("domain-map", "handover", "rulebook"))
    p.add_argument("--out")
    p.add_argument("--force", action="store_true")

    sub.add_parser("version", parents=[common], help="print the version")
    return parser


def _feature(root: Path, args: argparse.Namespace, required: bool = True) -> Optional[Path]:
    try:
        return resolve_feature_dir(root, getattr(args, "feature_dir", None))
    except ArchiGuardError:
        if required:
            raise
        return None


def run(argv: Optional[Sequence[str]] = None) -> int:
    from . import commands
    from .configure import run_configure
    from .runner import not_run_line, render_text, run_step, stops_wrapped_command, verify

    _configure_stdout()
    argv = list(sys.argv[1:] if argv is None else argv)
    inner: List[str] = []
    if argv and argv[0] == "loop" and "--" in argv:
        idx = argv.index("--")
        argv, inner = argv[:idx], argv[idx + 1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    root: Optional[Path] = None
    try:
        if args.command == "version":
            print(f"archiguard {__version__}")
            return EXIT_PASS
        root = find_project_root(args.root)
        if args.command == "edit-guard":
            from .editguard import main_from_stdin

            return main_from_stdin(root, args.config)
        if args.command == "validate-standards" and args.path:
            return commands.cmd_validate_standards(Path(args.path).resolve(), as_json)
        cfg = load_config(root, args.config, ci=True if args.command == "ci" else None)
        if args.command == "validate-standards":
            path = cfg.path("standards", "path")
            if path is None:
                raise ArchiGuardError("standards.path is not set")
            return commands.cmd_validate_standards(path, as_json)
        if args.command == "run":
            feature = _feature(root, args)
            outcome = run_step(root, cfg, args.target, args.step.lower(), feature, via=args.via)
            print(json.dumps(outcome.combined, indent=2, ensure_ascii=False) if as_json else render_text(outcome, root, args.verbose))
            return outcome.exit_code
        if args.command == "verify":
            feature = _feature(root, args)
            outcome = verify(root, cfg, args.target, feature, ci=cfg.ci)
            print(json.dumps(outcome.combined, indent=2, ensure_ascii=False) if as_json else render_text(outcome, root, args.verbose))
            return outcome.exit_code
        if args.command == "check":
            return commands.cmd_check(root, cfg, _feature(root, args, required=False), args.gate, args.checks,
                                      args.iteration, as_json, args.verbose)
        if args.command == "rules":
            return commands.cmd_rules(root, cfg, _feature(root, args, required=False), as_json)
        if args.command == "resolve":
            return commands.cmd_resolve(root, cfg, args.check, as_json)
        if args.command == "signoff":
            return commands.cmd_signoff(root, cfg, _feature(root, args), args.by, args.role, as_json)
        if args.command == "reopen":
            return commands.cmd_reopen(root, _feature(root, args), args.by, args.reason)
        if args.command == "handover":
            return commands.cmd_handover(root, cfg, _feature(root, args), as_json, args.verbose)
        if args.command == "test":
            return commands.cmd_test(root, cfg, _feature(root, args), not args.no_run, as_json, args.verbose)
        if args.command == "loop":
            feature = _feature(root, args)
            passthrough = list(inner)
            if passthrough and "--feature-dir" not in passthrough and getattr(args, "feature_dir", None):
                passthrough += ["--feature-dir", args.feature_dir]
            if passthrough and "--root" not in passthrough:
                passthrough += ["--root", str(root)]
            return commands.cmd_loop(root, cfg, feature, args.name, args.reset, args.status, passthrough, run)
        if args.command == "report":
            return commands.cmd_report(root, cfg, _feature(root, args), args.save, as_json, args.out)
        if args.command == "ci":
            feature = _feature(root, args) if args.feature_dir else None
            return commands.cmd_ci(root, cfg, feature, args.all, args.implement, as_json, args.junit, args.out)
        if args.command == "ledger":
            return commands.cmd_ledger(root, cfg, args.action, args)
        if args.command == "configure":
            text, data = run_configure(root, cfg, args.dry_run)
            print(json.dumps(data, indent=2) if as_json else text)
            return EXIT_PASS
        if args.command == "scaffold":
            return commands.cmd_scaffold(root, cfg, args.what, args.out, _feature(root, args, required=False), args.force)
        parser.error(f"unknown command {args.command}")
    except ArchiGuardError as exc:
        if as_json:
            print(json.dumps({"tool": "archiguard", "version": __version__, "status": "error", "error": str(exc)}, indent=2))
        print(f"archiGuard: ERROR: {exc}", file=sys.stderr)
        if args.command == "run" and root is not None and not as_json and stops_wrapped_command(args.via, args.step):
            try:
                line = not_run_line(root, normalise_command(args.target))
            except ArchiGuardError:
                line = None
            if line:
                print(line)
        return EXIT_ERROR
    return EXIT_PASS


def main() -> None:
    sys.exit(run())

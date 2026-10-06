"""A4.2 edit guard (Claude Code hook payloads) and the hash-chained decision ledger."""

from __future__ import annotations

import json

from conftest import FEATURE, design_signed, edit, read, write
from archiguard_core import editguard
from archiguard_core.ledger import Ledger

LEDGER = ".specify/archiguard/ledger.jsonl"


def payload(root, rel, event="PreToolUse", tool="Edit"):
    return json.dumps({"hook_event_name": event, "tool_name": tool, "cwd": str(root),
                       "tool_input": {"file_path": str(root / rel), "old_string": "a", "new_string": "b"}})


# --------------------------------------------------------------------------- #
# edit guard                                                                    #
# --------------------------------------------------------------------------- #


def test_policy_engine_and_evidence_are_always_read_only(project):
    for rel in (".specify/standards/rulebook.yml", LEDGER, ".specify/extensions/archiguard/archiguard-config.yml",
                f"{FEATURE}/gates/plan-b.json", f"{FEATURE}/gates/A3/A3.3.json"):
        code, msg = editguard.run(payload(project, rel), project)
        assert code == 2 and "read-only" in msg, rel
    code, _ = editguard.run(payload(project, f"{FEATURE}/gates/escalation-plan-b.md"), project)
    assert code == 0   # the agent completes the escalation note


def test_handover_artefacts_are_read_only(project):
    code, msg = editguard.run(payload(project, f"{FEATURE}/spec.md"), project)
    assert code == 2 and "RFI" in msg
    code, _ = editguard.run(payload(project, f"{FEATURE}/plan.md"), project)
    assert code == 0   # the design is open until the sign-off


def test_design_is_read_only_after_the_sign_off(project, ag):
    design_signed(ag, project)
    code, msg = editguard.run(payload(project, f"{FEATURE}/plan.md"), project)
    assert code == 2 and "sign-off" in msg
    code, _ = editguard.run(payload(project, f"{FEATURE}/tasks.md"), project)
    assert code == 0
    code, msg = editguard.run(payload(project, f"{FEATURE}/plan.md", event="PostToolUse"), project)
    assert code == 2 and "revert this edit" in msg


def test_post_edit_reports_rule_violations_of_the_edited_file(project):
    rel = "src/main/java/com/acme/orders/application/PlaceOrder.java"
    code, _ = editguard.run(payload(project, rel, event="PostToolUse"), project)
    assert code == 0
    text = read(project, rel)
    write(project, rel, text.replace("package com.acme.orders.application;",
                                     'package com.acme.orders.application;\nclass K { String password = "hunter2"; }', 1))
    code, msg = editguard.run(payload(project, rel, event="PostToolUse"), project)
    assert code == 2 and "ARCH-401" in msg
    # PreToolUse never evaluates content (the edit has not happened yet)
    code, _ = editguard.run(payload(project, rel, event="PreToolUse"), project)
    assert code == 0


def test_guard_fails_open_and_ignores_foreign_paths(project, tmp_path):
    assert editguard.run("not json", project) == (0, "")
    assert editguard.run(json.dumps({"tool_input": {}}), project) == (0, "")
    outside = tmp_path / "elsewhere.txt"
    assert editguard.run(json.dumps({"hook_event_name": "PreToolUse",
                                     "tool_input": {"file_path": str(outside)}}), project) == (0, "")
    write(project, ".specify/extensions/archiguard/archiguard-config.yml", "version: [broken\n")
    assert editguard.run(payload(project, f"{FEATURE}/plan.md"), project)[0] == 0


def test_guard_can_be_switched_off(project):
    edit(project, ".specify/extensions/archiguard/archiguard-config.yml", "version: 1\n",
         "version: 1\nedit_guard:\n  enabled: false\n")
    assert editguard.run(payload(project, f"{FEATURE}/spec.md"), project) == (0, "")


def test_cli_hook_reads_stdin(project, ag, monkeypatch):
    import io
    import sys
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload(project, f"{FEATURE}/spec.md")))
    r = ag(project, "edit-guard", feature=False)
    assert r.code == 2 and "read-only" in r.err


# --------------------------------------------------------------------------- #
# ledger                                                                        #
# --------------------------------------------------------------------------- #


def test_ledger_add_verify_revoke(project, ag):
    assert ag(project, "ledger", "verify").code == 0
    r = ag(project, "ledger", "add", "--id", "WVR-0001", "--status", "approved", "--type", "waiver", "--title", "Legacy import",
           "--rule", "ARCH-301", "--owner", "Orders tech lead", "--approver", "Lead architect", "--expires", "2099-12-31")
    assert r.code == 0, r
    ledger = Ledger.load(project / LEDGER)
    assert ledger.intact and ledger.entries[-1]["seq"] == 2
    assert ledger.entries[-1]["prev"] == ledger.entries[0]["hash"]
    r = ag(project, "ledger", "revoke", "--id", "WVR-0001", "--by", "Lead architect")
    assert r.code == 0, r
    ledger = Ledger.load(project / LEDGER)
    assert ledger.get("WVR-0001")["status"] == "revoked" and len(ledger.entries) == 3
    assert "not 'approved'" in ledger.check_entry("WVR-0001", __import__("datetime").date(2026, 1, 1))
    r = ag(project, "ledger", "list")
    assert "WVR-0001" in r.out and "revoked" in r.out


def test_ledger_never_rewrites_an_entry(project, ag):
    r = ag(project, "ledger", "add", "--id", "ADR-0007", "--type", "adr", "--title", "Again",
           "--rule", "ARCH-201", "--owner", "x", "--approver", "y", "--expires", "2099-12-31")
    assert r.code == 2 and "already in the ledger" in r.err


def test_waiver_needs_owner_approver_expiry(project, ag):
    r = ag(project, "ledger", "add", "--id", "WVR-0002", "--status", "approved", "--type", "waiver", "--title", "No approver",
           "--rule", "ARCH-301", "--owner", "Orders tech lead", "--expires", "2099-12-31")
    assert r.code == 2 and "approver" in r.err


def test_tampering_breaks_the_chain(project, ag):
    path = project / LEDGER
    text = path.read_text(encoding="utf-8").replace("2027-06-30", "2099-12-31")
    path.write_text(text, encoding="utf-8")
    r = ag(project, "ledger", "verify")
    assert r.code == 1 and "was edited" in r.out
    r = ag(project, "ledger", "add", "--id", "ADR-0011", "--type", "adr", "--title", "x", "--owner", "o")
    assert r.code == 2 and "not intact" in r.err
    r = ag(project, "run", "plan", "b")
    assert "[A3.7]" in r.out and "decision ledger" in r.out


def test_expired_waiver_no_longer_waives(project, ag, monkeypatch):
    design_signed(ag, project)
    assert ag(project, "ledger", "add", "--id", "WVR-0003", "--status", "approved", "--type", "waiver", "--title", "Short",
              "--rule", "ARCH-301", "--owner", "o", "--approver", "a", "--expires", "2030-01-31").code == 0
    monkeypatch.setenv("ARCHIGUARD_TODAY", "2030-01-31")
    r = ag(project, "check", "A4", "A4.4")
    assert "- ARCH-201:" in r.out and "- ARCH-301:" not in r.out, r
    monkeypatch.setenv("ARCHIGUARD_TODAY", "2030-02-01")
    r = ag(project, "check", "A4", "A4.4")
    assert "- ARCH-301:" in r.out, r


def test_today_override_is_ignored_in_ci(monkeypatch):
    from archiguard_core.common import today
    import datetime
    monkeypatch.setenv("ARCHIGUARD_TODAY", "2030-02-01")
    assert today() == datetime.date(2030, 2, 1)
    monkeypatch.setenv("CI", "true")
    assert today() == datetime.date.today()


def shell(root, command, event="PreToolUse"):
    return json.dumps({"hook_event_name": event, "tool_name": "Bash", "cwd": str(root), "tool_input": {"command": command}})


def test_agents_cannot_run_the_commands_reserved_for_people(project):
    launcher = "bash .specify/extensions/archiguard/scripts/bash/archiguard.sh"
    for sub in ("signoff --by me", "reopen --by me --reason x", "resolve", "ledger add --id ADR-1 --type adr --title x --owner o",
                "ledger revoke --id ADR-0007 --by me"):
        code, msg = editguard.run(shell(project, f"cd {project} && {launcher} {sub}"), project)
        assert code == 2 and "decision of a person" in msg, sub
    for sub in ("run plan b", "resolve --check", "ledger list", "ledger verify", "rules", "report --save"):
        assert editguard.run(shell(project, f"{launcher} {sub}"), project) == (0, ""), sub
    assert editguard.run(shell(project, "git status"), project) == (0, "")
    assert editguard.run(shell(project, f"{launcher} signoff --by me", event="PostToolUse"), project) == (0, "")


def test_ledger_entries_are_proposed_unless_approved_by_someone(project, ag):
    r = ag(project, "ledger", "add", "--id", "ADR-0020", "--type", "adr", "--title", "x", "--rule", "ARCH-201", "--owner", "o")
    assert r.code == 0, r
    assert Ledger.load(project / LEDGER).get("ADR-0020")["status"] == "proposed"
    r = ag(project, "ledger", "add", "--id", "ADR-0021", "--type", "adr", "--title", "x", "--rule", "ARCH-201",
           "--owner", "o", "--status", "approved")
    assert r.code == 2 and "--approver" in r.err

"""Pluggable gates: the scopeGuard engine as the `scope` gate, and any gate speaking the archiGuard protocol."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ARCH_201_ROW, FEATURE, REPO, edit, read, write

CFG = ".specify/extensions/archiguard/archiguard-config.yml"

FAKE_SCOPEGUARD = r'''
import json, os, sys
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("scopeguard 0.3.0"); sys.exit(0)
check = args[0]
open(os.path.join(os.path.dirname(__file__), "calls.log"), "a").write(" ".join(args) + "\n")
if check == "inventory":
    print("SCOPE CONTRACT\n  US1 Place an order"); sys.exit(0)
mode = os.environ.get("FAKE_SG", "violation")
if mode == "error":
    print(json.dumps({"verdict": "error", "error": "spec.md not found"})); sys.exit(2)
items = [{"id": "US1", "title": "Place an order", "verdict": "pass"}]
if mode == "violation":
    items.append({"id": "BR-002", "title": "Request the payment", "verdict": "violation",
                  "detail": "missing from plan.md 'Scope Coverage'", "location": "plan.md",
                  "spec_excerpt": "- **BR-002**: The system shall request the payment"})
if mode == "deferred":
    items.append({"id": "BR-002", "title": "Request the payment", "verdict": "waived",
                  "detail": "deferred: payments not ready"})
print(json.dumps({"verdict": "violation" if mode == "violation" else "pass", "gates": [{
    "gate": check, "summary": "x", "fix_target": "plan.md \"## Scope Coverage\"",
    "fix_skeleton": ["| BR-002 | Request the payment | covered | <where> | |"],
    "items": items, "findings": []}]}))
sys.exit(1 if mode == "violation" else 0)
'''


def install_fake_scopeguard(root: Path, version: str = "0.3.0") -> Path:
    ext = root / ".specify" / "extensions" / "scopeguard"
    write(root, ".specify/extensions/scopeguard/extension.yml",
          f'schema_version: "1.0"\nextension:\n  id: scopeguard\n  version: "{version}"\n')
    write(root, ".specify/extensions/scopeguard/scripts/python/scopeguard.py", FAKE_SCOPEGUARD)
    return ext


def plug_scope(root: Path) -> None:
    edit(root, CFG, "        - { gate: A0, run: [A0.5] }", "        - { gate: scope, run: [plan] }\n        - { gate: A0, run: [A0.5] }")


def test_scope_gate_maps_scopeguard_findings(project, ag, monkeypatch):
    ext = install_fake_scopeguard(project)
    plug_scope(project)
    r = ag(project, "run", "plan", "b")
    assert r.code == 1, r
    assert "[plan] BR-002" in r.out
    assert "add to plan.md \"## Scope Coverage\": | BR-002 |" in r.out
    assert "The system shall request the payment" in r.out
    verdict = json.loads(read(project, f"{FEATURE}/gates/scope/plan.json"))
    assert verdict["status"] == "violation" and verdict["data"]["engine"] == "scopeguard 0.3.0"
    call = (ext / "scripts" / "python" / "calls.log").read_text().strip().split("\n")[-1]
    assert call.startswith("plan --root") and "--json" in call and "--feature-dir" in call
    assert "--config" not in call      # scope-config.yml does not exist in the example
    monkeypatch.setenv("FAKE_SG", "deferred")
    r = ag(project, "run", "plan", "b")
    assert "[WAIV] scope · plan" in r.out, r
    assert "BR-002" not in r.out.split("RESOLVE")[-1]


def test_deferral_must_cite_a_reference_when_required(project, ag, monkeypatch):
    install_fake_scopeguard(project)
    plug_scope(project)
    monkeypatch.setenv("FAKE_SG", "deferred")
    r = ag(project, "check", "scope", "plan")
    assert "1 waived" in r.out, r
    edit(project, CFG, "signoff:", "options:\n  scope: { require_deferral_reference: true }\nsignoff:")
    r = ag(project, "check", "scope", "plan")
    assert r.code == 1 and "without an RFI or ledger reference" in r.out, r


def test_scope_gate_refuses_an_unsupported_scopeguard_version(project, ag):
    install_fake_scopeguard(project, version="0.2.0")
    plug_scope(project)
    r = ag(project, "run", "plan", "b")
    assert r.code == 2 and "does not satisfy >=0.3.0,<0.5" in r.out, r


def test_scope_gate_pinned_by_sha256(project, ag):
    import hashlib
    ext = install_fake_scopeguard(project)
    plug_scope(project)
    # the pin is the sha256 of the file as released, with LF line endings (a CRLF checkout still matches)
    raw = (ext / "scripts" / "python" / "scopeguard.py").read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256(raw).hexdigest()
    edit(project, CFG, "signoff:", f"gates:\n  scope:\n    sha256: \"{'0' * 64}\"\nsignoff:")
    r = ag(project, "check", "scope", "plan")
    assert r.code == 2 and "pins " + "0" * 64 in r.out, r
    edit(project, CFG, "0" * 64, digest)
    assert ag(project, "check", "scope", "plan").code == 1
    edit(project, CFG, f'"{digest}"', "12345")
    assert ag(project, "check", "scope", "plan").code == 2   # an unquoted digest is refused


def test_scope_gate_without_scopeguard_cannot_evaluate(project, ag):
    plug_scope(project)
    r = ag(project, "run", "plan", "b")
    assert r.code == 2 and "install the scopeguard extension" in r.out, r


def test_scopeguard_error_is_fail_closed(project, ag, monkeypatch):
    install_fake_scopeguard(project)
    plug_scope(project)
    monkeypatch.setenv("FAKE_SG", "error")
    r = ag(project, "run", "plan", "b")
    assert r.code == 2 and "spec.md not found" in r.out, r


def test_inventory_lands_in_the_step_a_contract(project, ag):
    install_fake_scopeguard(project)
    edit(project, CFG, "      - { gate: A3, run: [A3.1] }", "      - { gate: A3, run: [A3.1] }\n      - { gate: scope, run: [inventory] }")
    r = ag(project, "run", "plan", "a")
    assert r.code == 0 and "SCOPE CONTRACT" in r.out, r


# --------------------------------------------------------------------------- #
# A third-party gate speaking the archiGuard protocol                           #
# --------------------------------------------------------------------------- #

CUSTOM_GATE = r'''
import json, sys
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("1.2.0"); sys.exit(0)
checks = [a for a in args if a.startswith("SEC")]
out = []
for c in checks:
    if c == "SEC.1":
        out.append({"check": c, "status": "violation", "findings": [
            {"rule": "SEC-007", "message": "TLS 1.0 enabled", "where": "src/main/resources/application.yml",
             "fix_hint": "require TLS 1.2+"}]})
    else:
        out.append({"check": c, "status": "pass", "findings": []})
print(json.dumps({"verdicts": out}))
sys.exit(1 if any(v["status"] == "violation" for v in out) else 0)
'''


def test_registered_external_gate(project, ag):
    write(project, "tools/secgate.py", CUSTOM_GATE)
    edit(project, CFG, "signoff:", (
        "gates:\n  SEC:\n    command: tools/secgate.py\n    version: \">=1.0\"\n"
        "    checks:\n      SEC.1: { name: transport security, target: code }\n"
        "      SEC.2: { name: headers, target: code }\nsignoff:"))
    edit(project, CFG, "        - { gate: A4, run: [A4.4] }", "        - { gate: A4, run: [A4.4] }\n        - { gate: SEC, run: [SEC.1, SEC.2] }")
    r = ag(project, "check", "SEC", "SEC.1", "SEC.2")
    assert r.code == 1, r
    assert "SEC-007" in r.out and "TLS 1.0" in r.out
    sec1 = json.loads(read(project, f"{FEATURE}/gates/SEC/SEC.1.json"))
    assert sec1["status"] == "violation"
    assert json.loads(read(project, f"{FEATURE}/gates/SEC/SEC.2.json"))["status"] == "pass"
    # the gate's own exit 3 escalates at once instead of looping
    write(project, "tools/secgate.py", CUSTOM_GATE.replace("sys.exit(1 if", "sys.exit(3 if"))
    r = ag(project, "run", "implement", "b")
    assert "SEC-007" in r.out and "[no repair - needs a person]" in r.out, r
    edit(project, CFG, "    version: \">=1.0\"", "    version: \">=2.0\"")
    assert ag(project, "check", "SEC", "SEC.1").code == 2


# --------------------------------------------------------------------------- #
# The real scopeGuard (CI checks it out; set SCOPEGUARD_SRC to run it locally)  #
# --------------------------------------------------------------------------- #

SCOPEGUARD_SRC = os.environ.get("SCOPEGUARD_SRC", "")


@pytest.mark.skipif(not SCOPEGUARD_SRC or not Path(SCOPEGUARD_SRC, "extension.yml").is_file(),
                    reason="SCOPEGUARD_SRC (a scopeGuard v0.3.x checkout) is not set")
def test_real_scopeguard_end_to_end(project, ag):
    src = Path(SCOPEGUARD_SRC)
    ext = project / ".specify" / "extensions" / "scopeguard"
    shutil.copytree(src / "scripts", ext / "scripts")
    shutil.copy(src / "extension.yml", ext / "extension.yml")
    shutil.copy(REPO / "scope-config-template.yml", project / ".specify" / "extensions" / "archiguard" / "scope-config.yml")
    edit(project, CFG, "      - { gate: A3, run: [A3.1] }", "      - { gate: A3, run: [A3.1] }\n      - { gate: scope, run: [inventory] }")
    plug_scope(project)
    edit(project, CFG, "        - { gate: A3, run: [A3.5] }", "        - { gate: scope, run: [tasks] }\n        - { gate: A3, run: [A3.5] }")
    r = ag(project, "run", "plan", "a")
    assert r.code == 0 and "SCOPE CONTRACT" in r.out, r
    assert "1 user stories, 6 requirements" in r.out      # the corporate prefixes of scope-config-template.yml
    r = ag(project, "run", "plan", "b")
    assert r.code == 1, r
    assert "[plan] BR-002" in r.out and "request the payment of the order total" in r.out
    assert "install the scopeguard preset" not in r.out
    plan = f"{FEATURE}/plan.md"
    edit(project, plan, "<!-- ARCH-201 (layering) is missing on purpose: the A3.3 check-plan finds it. -->", ARCH_201_ROW)
    edit(project, plan, "<!-- BR-002 (request the payment) is missing on purpose: the scope gate finds it when it is plugged in. -->",
         "| BR-002 | Request the payment of the order total | covered | Integration Points (payments) | |")
    r = ag(project, "run", "plan", "b")
    assert r.code == 0, r
    r = ag(project, "run", "tasks", "b")
    assert r.code == 0, r
    proc = subprocess.run([sys.executable, str(ext / "scripts" / "python" / "scopeguard.py"), "--version"],
                          capture_output=True, text=True)
    assert "0.3" in (proc.stdout + proc.stderr)

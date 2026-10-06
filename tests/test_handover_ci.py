"""Handover 4->5, the loop counter, the deterministic test loop, the compliance report, CI and configure."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET

from conftest import FEATURE, commit_all, design_signed, edit, read, write

CFG = ".specify/extensions/archiguard/archiguard-config.yml"

FAKE_TESTS = r'''
import os, sys
os.makedirs("reports", exist_ok=True)
fail = os.path.exists("FAIL_AC2")
case2 = '<testcase classname="com.acme.orders.PlaceOrderTest" name="AC_002_BR_002_payment_requested">' + \
    ('<failure message="no payment request">boom</failure>' if fail else '') + '</testcase>'
open("reports/TEST-PlaceOrderTest.xml", "w").write(
    '<?xml version="1.0"?><testsuite name="PlaceOrderTest">'
    '<testcase classname="com.acme.orders.PlaceOrderTest" name="AC_001_BR_001_order_created"/>' + case2 + '</testsuite>')
sys.exit(1 if fail else 0)
'''


def implemented(ag, root):
    """Signed design, clean code (the planted violations fixed), green fitness, test commands configured."""
    design_signed(ag, root)
    edit(root, "src/main/java/com/acme/orders/domain/Order.java",
         "import com.acme.orders.api.OrderController;   // ARCH-201: the domain layer must not depend on the api layer\n", "")
    edit(root, "src/main/java/com/acme/orders/api/OrderController.java",
         "import com.acme.payments.internal.PaymentGateway;   // ARCH-301: payments publishes only com.acme.payments.api",
         "import com.acme.payments.api.PaymentsClient;")
    write(root, "tools/fake_tests.py", FAKE_TESTS)
    py = sys.executable.replace("\\", "/")
    edit(root, CFG, "signoff:", f'tests:\n  command: "\\"{py}\\" tools/fake_tests.py"\n  build: "\\"{py}\\" -c pass"\nsignoff:')
    r = ag(root, "run", "implement", "b")
    assert r.code == 0, r
    commit_all(root, "T004 T005 US1 AC-001 AC-002 implemented")


# --------------------------------------------------------------------------- #
# handover 4 -> 5                                                               #
# --------------------------------------------------------------------------- #


def test_handover_entry_checks_and_manifest(project, ag):
    implemented(ag, project)
    r = ag(project, "handover")
    assert r.code == 0, r
    manifest = json.loads(read(project, f"{FEATURE}/gates/handover-4-5.json"))
    assert manifest["status"] == "pass"
    assert set(manifest["entry_checks"]) == {"H1", "H2", "H3", "H4", "H5", "H6"}
    assert manifest["requirements_to_tests"]["AC-001"] == ["src/test/java/com/acme/orders/PlaceOrderTest.java"]
    assert manifest["hashes"]["spec.md"] and manifest["pins"]


def test_handover_back_to_implement_is_repairable(project, ag):
    implemented(ag, project)
    edit(project, f"{FEATURE}/tasks.md", "- [x] T005", "- [ ] T005")
    write(project, "BUILD_BROKEN", "")
    py = sys.executable.replace("\\", "/")
    edit(project, CFG, f'build: "\\"{py}\\" -c pass"',
         f'build: "\\"{py}\\" -c \\"import os,sys; print(\'compile error\'); sys.exit(os.path.exists(\'BUILD_BROKEN\'))\\""')
    r = ag(project, "handover")
    assert r.code == 1, r
    assert "H1" in r.out and "T005" in r.out
    assert "H5: build failed" in r.out and "| compile error" in r.out
    assert "NEXT: back to implement" in r.out


def test_handover_pin_moved_needs_a_person(project, ag):
    implemented(ag, project)
    edit(project, f"{FEATURE}/spec.md", "one order line per basket item", "one order line per basket item, merged")
    r = ag(project, "handover")
    assert r.code == 3, r


# --------------------------------------------------------------------------- #
# loop counter and the deterministic test loop                                  #
# --------------------------------------------------------------------------- #


def test_test_loop_bounded_and_traced(project, ag):
    implemented(ag, project)
    write(project, "FAIL_AC2", "")
    codes = [ag(project, "loop", "test_loop", "--", "test").code for _ in range(4)]
    assert codes == [1, 1, 1, 3]
    assert "TODO(agent)" in read(project, f"{FEATURE}/gates/escalation-loop-test_loop.md")
    r = ag(project, "loop", "test_loop", "--", "test")
    assert r.code == 3                                    # stays escalated until a person resets it
    assert ag(project, "loop", "test_loop", "--status").code == 3
    assert ag(project, "loop", "test_loop", "--reset").code == 0
    (project / "FAIL_AC2").unlink()
    r = ag(project, "loop", "test_loop", "--", "test")
    assert r.code == 0, r
    assert "4/4 in-scope id(s) traced" in r.out
    verdict = json.loads(read(project, f"{FEATURE}/gates/test-loop.json"))
    assert verdict["status"] == "pass"
    assert verdict["data"]["trace"]["AC-002"] == ["com.acme.orders.PlaceOrderTest.AC_002_BR_002_payment_requested"]
    # green is terminal: the next red starts with the full budget
    write(project, "FAIL_AC2", "")
    r = ag(project, "loop", "test_loop", "--", "test")
    assert r.code == 1 and "repair iteration 1 of 3" in r.out, r
    assert "AC-002" in r.out and "AC-2" not in r.out


def test_failing_test_names_the_requirement(project, ag):
    implemented(ag, project)
    write(project, "FAIL_AC2", "")
    r = ag(project, "test")
    assert r.code == 1, r
    assert "failing test com.acme.orders.PlaceOrderTest.AC_002_BR_002_payment_requested (AC-002, BR-002)" in r.out


def test_unknown_loop_is_refused(project, ag):
    r = ag(project, "loop", "forever", "--", "test")
    assert r.code == 2 and "unknown loop 'forever'" in r.err


# --------------------------------------------------------------------------- #
# compliance report and CI                                                      #
# --------------------------------------------------------------------------- #


def test_compliance_report(project, ag, tmp_path):
    implemented(ag, project)
    assert ag(project, "handover").code == 0
    out = tmp_path / "summary.md"
    r = ag(project, "report", "--save", "--out", str(out))
    assert r.code == 0, r
    text = read(project, f"{FEATURE}/gates/architecture-compliance.md")
    assert "**Overall: pass**" in text
    assert "## Design authority sign-off" in text and "Lead architect" in text
    assert "| A4 | A4.4 | pass |" in text
    assert out.read_text(encoding="utf-8") == text


def test_ci_required_check(project, ag, monkeypatch, tmp_path):
    monkeypatch.setenv("CI", "true")
    junit = tmp_path / "archiguard.xml"
    r = ag(project, "ci", "--junit", str(junit), feature=False)
    assert r.code == 1, r
    assert "[PASS] standards lock current" in r.out and "[PASS] decision ledger intact" in r.out
    assert "ARCH-201" in r.out
    assert not (project / FEATURE / "gates" / "plan-verify.json").exists()     # CI never writes evidence
    suite = ET.parse(str(junit)).getroot()
    assert suite.find(".//failure") is not None
    # A local workstation date override does not reach CI
    monkeypatch.setenv("ARCHIGUARD_TODAY", "2099-01-01")
    monkeypatch.delenv("CI")
    edit(project, f"{FEATURE}/plan.md", "<!-- ARCH-201 (layering) is missing on purpose: the A3.3 check-plan finds it. -->",
         "| ARCH-201 | Layers depend downwards only (api -> application -> domain) | satisfied | Project Structure | |")
    monkeypatch.setenv("CI", "true")
    r = ag(project, "ci", feature=False)
    assert r.code == 0, r
    assert "CI RESULT: PASS" in r.out


# --------------------------------------------------------------------------- #
# configure                                                                     #
# --------------------------------------------------------------------------- #

EXTENSIONS_YML = """installed:
- archiguard
- scopeguard
settings:
  auto_execute_hooks: true
hooks:
  before_plan:
  - extension: archiguard
    command: speckit.archiguard.planentry
    enabled: true
    optional: false
  - extension: scopeguard
    command: speckit.scopeguard.inventory
    enabled: true   # scopeGuard's own hook
    optional: false
  after_plan:
  - extension: archiguard
    command: speckit.archiguard.plangate
    enabled: true
    optional: false
  - extension: other
    command: speckit.other.thing
    enabled: true
    optional: true
"""


def test_configure_switches_hooks_and_keeps_other_extensions(project, ag):
    write(project, ".specify/extensions.yml", EXTENSIONS_YML)
    edit(project, CFG, "      - { gate: A3, run: [A3.1] }", "      - { gate: A3, run: [A3.1] }\n      - { gate: scope, run: [inventory] }")
    r = ag(project, "configure", "--json", feature=False)
    data = json.loads(r.out)
    assert r.code == 0 and data["effective_integration"] == "hooks", r
    text = read(project, ".specify/extensions.yml")
    blocks = text.split("- extension: ")
    state = {b.split("\n")[1].strip(): ("enabled: true" in b) for b in blocks[1:]}
    assert state["command: speckit.archiguard.planentry"] is True       # hooks integration: archiGuard hooks on
    assert state["command: speckit.scopeguard.inventory"] is False      # archiGuard runs the scope gate itself
    assert state["command: speckit.other.thing"] is True                # other extensions untouched
    changed = [(a, b) for a, b in zip(EXTENSIONS_YML.split("\n"), text.split("\n")) if a != b]
    assert changed == [("    enabled: true   # scopeGuard's own hook", "    enabled: false")]   # one line touched
    for name in ("speckit.plan", "speckit.tasks", "speckit.implement"):
        write(project, f".specify/presets/archiguard-templates/commands/{name}.md", "---\n---\n")
    edit(project, CFG, "integration: hooks", "integration: inline")
    r = ag(project, "configure", feature=False)
    assert "speckit.archiguard.planentry       off   (was on)" in r.out, r
    r = ag(project, "configure", "--dry-run", feature=False)
    assert "0 hook setting(s) would change" in r.out, r


def test_test_loop_traces_ids_declared_in_the_test_source(project, ag):
    """JUnit names carry no ids; @Tag annotations and comments next to the test method do."""
    implemented(ag, project)
    write(project, "tools/fake_tests.py", (
        "import os\nos.makedirs('reports', exist_ok=True)\n"
        "open('reports/TEST-PlaceOrderTest.xml', 'w').write('<testsuite>"
        "<testcase classname=\"com.acme.orders.PlaceOrderTest\" name=\"createsOneLinePerItem()\"/>"
        "<testcase classname=\"com.acme.orders.PlaceOrderTest\" name=\"requestsThePayment_AC_002_BR_002\"/>"
        "</testsuite>')\n"))
    r = ag(project, "test")
    assert r.code == 0, r
    trace = json.loads(read(project, f"{FEATURE}/gates/test-loop.json"))["data"]["trace"]
    assert trace["AC-001"] == ["com.acme.orders.PlaceOrderTest.createsOneLinePerItem()"]
    assert trace["BR-001"] == ["com.acme.orders.PlaceOrderTest.createsOneLinePerItem()"]
    # the tag of one test never leaks to the next one
    edit(project, "src/test/java/com/acme/orders/PlaceOrderTest.java", "void requestsThePayment_AC_002_BR_002() {}",
         "void requestsThePayment() {}")
    write(project, "tools/fake_tests.py", read(project, "tools/fake_tests.py").replace(
        "requestsThePayment_AC_002_BR_002", "requestsThePayment"))
    r = ag(project, "test")
    assert r.code == 1 and "no passing test carries AC-002" in r.out, r


def test_tests_are_required_only_for_the_handover_scope(project, ag):
    edit(project, f"{FEATURE}/handover.yml", "scope: [UC-001, SC-001, AC-001, AC-002, BR-001, BR-002, D-001]",
         "scope: [UC-001, SC-001, AC-001, BR-001, D-001]")
    write(project, "src/test/java/com/acme/orders/PlaceOrderTest.java",
          'class PlaceOrderTest {\n    @Test @Tag("AC-001") @Tag("BR-001")\n    void createsOneLinePerItem() {}\n}\n')
    r = ag(project, "check", "H", "H4")
    assert r.code == 0, r


def test_configure_recommends_scopeguard_embedded_mode(project, ag):
    write(project, ".specify/extensions.yml", EXTENSIONS_YML)
    edit(project, CFG, "      - { gate: A3, run: [A3.1] }", "      - { gate: A3, run: [A3.1] }\n      - { gate: scope, run: [inventory] }")
    write(project, ".specify/extensions/scopeguard/extension.yml", 'extension:\n  id: scopeguard\n  version: "0.4.0"\n')
    r = ag(project, "configure", feature=False)
    assert "set 'integration: embedded'" in r.out, r
    write(project, ".specify/extensions/scopeguard/scopeguard-config.yml", "integration: embedded\n")
    assert "set 'integration: embedded'" not in ag(project, "configure", feature=False).out
    write(project, ".specify/extensions/scopeguard/extension.yml", 'extension:\n  id: scopeguard\n  version: "0.3.0"\n')
    write(project, ".specify/extensions/scopeguard/scopeguard-config.yml", "integration: inline\n")
    assert "set 'integration: embedded'" not in ag(project, "configure", feature=False).out

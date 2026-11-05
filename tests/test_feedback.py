"""Loop feedback to the domain master design: evidence after coding, never a gate (docs/loop-feedback.md)."""

from __future__ import annotations

import json
import shutil

import pytest

from conftest import FEATURE, commit_all, design_signed, edit, git, read, write

from archiguard_core import feedback
from archiguard_core.config import load_config
from archiguard_core.editguard import readonly_violation

CFG = ".specify/extensions/archiguard/archiguard-config.yml"
DMAP = ".specify/standards/domain-map.yaml"
GATES = f"{FEATURE}/gates"
FB_JSON = f"{GATES}/loop-feedback.json"
FB_MD = f"{GATES}/loop-feedback.md"
ORDER = "src/main/java/com/acme/orders/domain/Order.java"
LAYER_IMPORT = "import com.acme.orders.api.OrderController;   // ARCH-201: the domain layer must not depend on the api layer\n"


def waiver_301(ag, root, expires="2099-12-31"):
    r = ag(root, "ledger", "add", "--id", "WVR-0001", "--status", "approved", "--type", "waiver", "--title",
           "Legacy import", "--rule", "ARCH-301", "--owner", "Orders tech lead", "--approver", "Lead architect",
           "--expires", expires)
    assert r.code == 0, r


def notifications(root):
    """A new build unit with code no context maps (a new service nobody designed)."""
    base = "services/notifications"
    write(root, f"{base}/pom.xml", "<project/>\n")
    write(root, f"{base}/src/main/java/com/acme/notifications/OrderPlacedMailer.java",
          "package com.acme.notifications;\nclass OrderPlacedMailer {}\n")
    write(root, f"{base}/src/main/java/com/acme/notifications/MailTemplate.java",
          "package com.acme.notifications;\nclass MailTemplate {}\n")


def us1(ag, root):
    """The spec's US1 branch: signed design, a new unit, a payments change, ARCH-301 under a waiver."""
    git(root, "remote", "add", "origin", "https://example.com/acme/acme-shop.git")
    design_signed(ag, root)
    edit(root, ORDER, LAYER_IMPORT, "")
    waiver_301(ag, root)
    notifications(root)
    edit(root, "src/main/java/com/acme/payments/api/PaymentsClient.java", "}", "}\n// changed for orders\n")
    return ag(root, "run", "implement", "b")


def fb(root):
    return json.loads(read(root, FB_JSON))


def by_kind(data):
    return {(i["kind"], i["subject"]): i for i in data["items"]}


# --------------------------------------------------------------------------- #
# what it reports                                                               #
# --------------------------------------------------------------------------- #


def test_end_of_coding_reports_what_the_map_does_not_know(project, ag):
    r = us1(ag, project)
    assert r.code == 0, r
    assert "RESULT: PASS" in r.out
    assert "FEEDBACK for the domain master design (not blocking, for the next iteration): 7 item(s) - 3 high, 2 medium, 2 low" in r.out
    assert "topology: mixed - existing unit '.' (orders, payments) + NEW unit 'services/notifications' (no context)" in r.out
    assert "... 4 more: specs/001-place-order/gates/loop-feedback.md" in r.out
    data = fb(project)
    assert data["status"] == "evaluated" and data["computed_by"] == "implement-b"
    assert data["home_context"] == "orders" and data["repository"] == "acme-shop"
    assert "step" not in data                                   # never read as a step verdict
    assert [(i["impact"], i["kind"], i["subject"]) for i in data["items"]] == [
        ("high", "unmapped-code", "services/notifications"),
        ("high", "new-unit", "acme-shop:services/notifications"),
        ("high", "domain-change", "waiver:WVR-0001"),
        ("medium", "cross-context", "orders->payments"),
        ("medium", "topology", "orders:undeclared"),
        ("low", "vocabulary", "orders:shipment"),
        ("low", "map-gap", "customers:no-code"),
    ]
    items = by_kind(data)
    unit = items[("new-unit", "acme-shop:services/notifications")]
    assert unit["id"] == feedback.item_id("new-unit", "acme-shop:services/notifications") == "LF-2a2a5a3d"
    assert "existing unit '.'" in unit["suggestion"] and unit["for"] == [{"role": "lead architect"}]
    assert unit["evidence"] == [{"path": "services/notifications/pom.xml", "change": "added"}]
    unmapped = items[("unmapped-code", "services/notifications")]
    assert unmapped["occurrences"]["count"] == 2 and "services/notifications/**" in unmapped["suggestion"]
    waived = items[("domain-change", "waiver:WVR-0001")]
    assert waived["waiver"] == {"id": "WVR-0001", "rule": "ARCH-301", "expires": "2099-12-31"}
    assert waived["suggestion"].startswith("Waived by WVR-0001 until 2099-12-31:")
    cross = items[("cross-context", "orders->payments")]
    assert cross["impact"] == "medium" and "customer-supplier" in cross["suggestion"]
    assert cross["for"][0] == {"role": "domain owner", "context": "payments", "name": "Payments domain owner"}
    assert data["topology"]["answer"] == "mixed"
    assert [(u["root"], u["new"], u["contexts"]) for u in data["topology"]["units"]] == [
        (".", False, ["orders", "payments"]), ("services/notifications", True, ["(unmapped)"])]
    md = read(project, FB_MD)
    assert "**Answer: mixed.** The feature extends the existing unit `.` and creates the new unit `services/notifications`" in md
    assert "| LF-2a2a5a3d | high | new-unit |" in md


def test_topology_existing_unit_and_a_clean_feature(project, ag):
    design_signed(ag, project)
    edit(project, ORDER, LAYER_IMPORT, "")
    edit(project, "src/main/java/com/acme/orders/api/OrderController.java",
         "import com.acme.payments.internal.PaymentGateway;   // ARCH-301: payments publishes only com.acme.payments.api",
         "import com.acme.payments.api.PaymentsClient;")
    r = ag(project, "run", "implement", "b")
    assert r.code == 0, r
    data = fb(project)
    assert data["topology"]["answer"] == "existing"
    assert {i["kind"] for i in data["items"]} == {"topology", "vocabulary", "map-gap"}
    assert "topology: existing - existing unit '.' (orders)" in r.out


def test_imports_the_map_does_not_allow(project, ag):
    design_signed(ag, project)
    edit(project, ORDER, LAYER_IMPORT, "")
    # orders code now imports customers (conformist: allowed, nothing published declared) and a new payments class
    write(project, "src/main/java/com/acme/orders/application/Billing.java",
          "package com.acme.orders.application;\nimport com.acme.payments.internal.Ledger;\nclass Billing {}\n")
    write(project, "src/main/java/com/acme/payments/api/Refunds.java",
          "package com.acme.payments.api;\nimport com.acme.orders.domain.Order;\nclass Refunds {}\n")
    data = feedback.produce(project, load_config(project), project / FEATURE, "cli", write=False)
    items = by_kind(data)
    published = items[("domain-change", "published:payments:com.acme.payments.internal")]
    assert published["impact"] == "medium" and published["waiver"] is None
    assert "src/main/java/com/acme/orders/application/Billing.java:2 import com.acme.payments.internal.Ledger" in \
        published["occurrences"]["items"]
    relation = items[("domain-change", "relation:payments->orders")]
    assert "Propose the relation payments -> orders" in relation["suggestion"]


def test_deviation_of_a_domain_rule_and_unowned_entity(project, ag):
    edit(project, f"{FEATURE}/plan.md", "| ARCH-101 | HTTP APIs",
         "| ARCH-301 | Contexts depend on each other only through published interfaces | deviation | OrderController | ADR-0007 |\n"
         "| ARCH-101 | HTTP APIs")
    edit(project, f"{FEATURE}/handover.yml", "  D-001: { entity: Order, context: orders }",
         "  D-001: { entity: Order, context: orders }\n  D-002: { entity: Voucher }")
    data = feedback.produce(project, load_config(project), project / FEATURE, "cli", write=False)
    items = by_kind(data)
    dev = items[("domain-change", "rule:ARCH-301:orders")]
    assert dev["impact"] == "high" and dev["waiver"]["id"] == "ADR-0007"
    entity = items[("domain-change", "entity:Voucher")]
    assert "no context of domain map 1.4.0 owns Voucher" in entity["observation"]


# --------------------------------------------------------------------------- #
# the domain map's optional topology keys                                       #
# --------------------------------------------------------------------------- #


def _declare(root, orders, deployables):
    edit(root, DMAP, "    published: [com.acme.orders.api]\n", f"    published: [com.acme.orders.api]\n    deployable: {orders}\n")
    write(root, DMAP, read(root, DMAP) + "deployables:\n" + deployables)


def _topology_items(project, ag):
    git(project, "remote", "add", "origin", "git@example.com:acme/acme-shop.git")
    edit(project, ORDER, LAYER_IMPORT, "")
    data = feedback.produce(project, load_config(project), project / FEATURE, "cli", write=False)
    return data, {i["subject"]: i for i in data["items"] if i["kind"] in ("topology", "new-unit", "map-gap")}


def test_declared_deployable_answers_existing_and_raises_nothing(project, ag):
    _declare(project, "shop", '  shop: { repo: acme-shop, root: ".", kind: service }\n')
    data, items = _topology_items(project, ag)
    assert data["topology"]["units"][0]["declared"] == ["shop"]
    assert not [s for s in items if s.startswith("orders:") or s.startswith("repo:")]


def test_deployed_from_another_repository(project, ag):
    _declare(project, "orders-svc", '  orders-svc: { repo: acme-orders, root: ".", kind: service }\n')
    _, items = _topology_items(project, ag)
    assert "acme-orders" in items["orders:acme-shop"]["suggestion"]
    assert "repo:acme-shop" in items                      # no deployable names this repository


def test_code_in_an_undeclared_unit_and_undefined_deployable(project, ag):
    git(project, "checkout", "-q", "main")
    write(project, "services/legacy/pom.xml", "<project/>\n")
    commit_all(project, "legacy unit on main")
    git(project, "checkout", "-q", "001-place-order")
    git(project, "merge", "-q", "--ff-only", "main")
    edit(project, DMAP, '    code: ["src/main/java/com/acme/orders/**", "src/test/java/com/acme/orders/**"]',
         '    code: ["src/main/java/com/acme/orders/**", "src/test/java/com/acme/orders/**", "services/legacy/**"]')
    _declare(project, "[shop, mailer]", '  shop: { root: ".", kind: service }\n')
    write(project, "services/legacy/src/Legacy.java", "class Legacy {}\n")
    _, items = _topology_items(project, ag)
    assert "Add services/legacy as a deployable of orders" in items["orders:acme-shop:services/legacy"]["suggestion"]
    assert "deployable:mailer:undefined" in items
    assert not any(s.startswith("acme-shop:") for s in items)   # services/legacy existed on main: not a new unit


def test_new_unit_declared_in_the_map_raises_no_new_unit_item(project, ag):
    _declare(project, "[shop, notifications]",
             '  shop: { root: ".", kind: service }\n  notifications: { root: services/notifications, kind: service }\n')
    notifications(project)
    data, items = _topology_items(project, ag)
    assert not any(s.startswith("acme-shop:") for s in items)
    new = [u for u in data["topology"]["units"] if u["root"] == "services/notifications"][0]
    assert new["new"] is True and new["declared"] == ["notifications"]


def test_the_new_keys_change_no_gate(project, ag):
    _declare(project, "[shop]", "  shop: { repo: acme-shop, root: '.', kind: service }\n")
    assert ag(project, "run", "plan", "a").code == 0
    write(project, DMAP, read(project, DMAP).replace("deployables:\n", "deployables: not-a-mapping\n#"))
    assert ag(project, "run", "plan", "a").code == 0
    data = feedback.produce(project, load_config(project), project / FEATURE, "cli", write=False)
    assert "map:deployables" in {i["subject"] for i in data["items"]}


# --------------------------------------------------------------------------- #
# never a gate                                                                  #
# --------------------------------------------------------------------------- #


def _gate_files(root):
    out = {}
    for path in sorted((root / GATES).rglob("*")):
        rel = path.relative_to(root / GATES).as_posix()
        if path.is_file() and not rel.startswith("loop-feedback"):
            out[rel] = path.read_text(encoding="utf-8")
    return out


@pytest.mark.parametrize("outcome", ["pass", "violation", "escalated", "error"])
def test_exit_codes_and_gate_files_are_identical_with_and_without_feedback(project, ag, tmp_path, outcome):
    design_signed(ag, project)
    notifications(project)
    if outcome == "pass":
        edit(project, ORDER, LAYER_IMPORT, "")
        waiver_301(ag, project)
    if outcome == "error":
        edit(project, CFG, "  rulebook: acme-standards@v2026.10.1", "  rulebook: acme-standards@v9")
    other = tmp_path / "copy"
    shutil.copytree(project, other)                    # same commits, same state
    edit(other, CFG, "signoff:", "feedback:\n  enabled: false\nsignoff:")
    edit(project, CFG, "signoff:", "feedback:\n  enabled: true\nsignoff:")
    runs = 2 if outcome == "escalated" else 1
    for _ in range(runs):
        on, off = ag(project, "run", "implement", "b"), ag(other, "run", "implement", "b")
        assert on.code == off.code
        assert on.out.split("\nFEEDBACK")[0] == off.out.split("\nFEEDBACK")[0].replace(str(other), str(project))
    assert on.code == {"pass": 0, "violation": 1, "escalated": 3, "error": 2}[outcome]
    assert _gate_files(project) == _gate_files(other)
    assert ("FEEDBACK for the domain master design" in on.out) == (outcome in ("pass", "escalated"))
    assert (project / FB_JSON).is_file() == (outcome in ("pass", "escalated"))
    assert not (other / FB_JSON).exists() and "FEEDBACK" not in off.out


def test_not_evaluated_never_fails(project, ag):
    (project / FEATURE / "handover.yml").unlink()
    r = ag(project, "feedback", "--save")
    assert r.code == 0, r
    assert "FEEDBACK: not evaluated - no handover record (handover.yml)" in r.out
    assert fb(project)["status"] == "not-evaluated" and fb(project)["items"] == []


def test_without_a_base_branch_the_git_kinds_are_skipped(project, ag):
    edit(project, CFG, "signoff:", "git:\n  base: develop\nsignoff:")
    data = feedback.produce(project, load_config(project), project / FEATURE, "cli", write=False)
    assert data["status"] == "partial" and data["topology"]["answer"] == "unknown"
    assert {s["kind"] for s in data["skipped"]} >= {"unmapped-code", "new-unit", "topology", "cross-context"}
    assert {i["kind"] for i in data["items"]} <= {"vocabulary", "map-gap", "domain-change"}


def test_switched_off(project, ag):
    edit(project, CFG, "signoff:", "feedback:\n  enabled: false\nsignoff:")
    r = ag(project, "feedback", "--save")
    assert r.code == 0 and "switched off" in r.out
    assert not (project / FB_JSON).exists()


# --------------------------------------------------------------------------- #
# files: identity, write-if-changed, resolved                                   #
# --------------------------------------------------------------------------- #


def test_write_if_changed_and_resolved_items(project, ag):
    edit(project, ORDER, LAYER_IMPORT, "")
    notifications(project)
    assert ag(project, "feedback", "--save").code == 0
    first = fb(project)
    raw = read(project, FB_JSON)
    assert ag(project, "feedback", "--save").code == 0
    assert read(project, FB_JSON) == raw                          # nothing changed: the file is kept as it is
    shutil.rmtree(project / "services")                           # the new unit went away during the feature
    assert ag(project, "feedback", "--save").code == 0
    second = fb(project)
    gone = {r["id"] for r in second["resolved"]}
    assert feedback.item_id("new-unit", "orders:services/notifications") in gone
    assert feedback.item_id("unmapped-code", "services/notifications") in gone
    kept = {i["id"]: i["first_seen"] for i in second["items"]}
    assert all(kept[i["id"]] == i["first_seen"] for i in first["items"] if i["id"] in kept)
    assert ag(project, "feedback", "--save").code == 0
    assert fb(project)["resolved"] == second["resolved"]          # resolved items stay listed, the file is stable


def test_group_depth_follows_the_map_and_the_id_formula(project):
    cfg = load_config(project)
    from archiguard_core.domain import load_domain_map

    dm = load_domain_map(project / DMAP)
    assert feedback._group_depth(dm, cfg["feedback"]) == 6
    write(project, "src/main/java/com/acme/shipping/Label.java", "class Label {}\n")
    data = feedback.produce(project, cfg, project / FEATURE, "cli", write=False)
    assert ("unmapped-code", "src/main/java/com/acme/shipping") in by_kind(data)
    assert feedback.item_id("vocabulary", "orders:shipment") == "LF-" + __import__("hashlib").sha256(
        b"vocabulary\norders:shipment").hexdigest()[:8]


# --------------------------------------------------------------------------- #
# where it is shown                                                             #
# --------------------------------------------------------------------------- #


def _implemented(ag, root):
    from test_handover_ci import implemented

    implemented(ag, root)


def test_handover_manifest_and_compliance_report_carry_the_feedback(project, ag):
    _implemented(ag, project)
    notifications(project)
    commit_all(project, "T004 UC-001 notifications")
    r = ag(project, "handover")
    assert r.code == 0, r
    assert "FEEDBACK for the domain master design" in r.out
    manifest = json.loads(read(project, f"{GATES}/handover-4-5.json"))
    assert manifest["status"] == "pass"
    assert manifest["feedback"]["file"] == FB_JSON and manifest["feedback"]["answer"] == "mixed"
    assert manifest["feedback"]["items"] == fb(project)["summary"]["items"]
    assert fb(project)["computed_by"] == "handover-4-5"
    r = ag(project, "report", "--save")
    assert r.code == 0, r
    text = read(project, f"{GATES}/architecture-compliance.md")
    assert "**Overall: pass**" in text
    assert "## Loop feedback to the domain master design (not blocking)" in text
    assert "**Answer: mixed.**" in text and "| LF-2a2a5a3d |" not in text   # the repository has no origin here
    assert feedback.item_id("new-unit", "orders:services/notifications") in text


def test_report_when_switched_off(project, ag):
    edit(project, CFG, "signoff:", "feedback:\n  enabled: false\nsignoff:")
    r = ag(project, "report")
    assert "Loop feedback is switched off (feedback.enabled)." in r.out


def test_ci_prints_the_feedback_and_never_writes_it(project, ag, monkeypatch):
    design_signed(ag, project)
    notifications(project)
    monkeypatch.setenv("CI", "true")
    plain = ag(project, "ci")
    with_fb = ag(project, "ci", "--feedback")
    assert plain.code == with_fb.code
    assert "FEEDBACK for the domain master design" in with_fb.out and "FEEDBACK" not in plain.out
    assert not (project / FB_JSON).exists()


def test_configure_shows_the_feedback(project, ag):
    r = ag(project, "configure", "--dry-run", feature=False)
    assert "loop feedback : on (7 kinds)" in r.out
    r = ag(project, "configure", "--dry-run", "--json", feature=False)
    assert json.loads(r.out)["feedback"] == {"enabled": True, "kinds": list(feedback.FEEDBACK_KINDS)}


def test_the_edit_guard_protects_the_feedback_json(project):
    cfg = load_config(project)
    assert readonly_violation(project, cfg, FB_JSON, [])


def test_unknown_feedback_settings_are_errors(project, ag):
    edit(project, CFG, "signoff:", "feedback:\n  enable: true\nsignoff:")
    assert ag(project, "feedback").code == 2
    edit(project, CFG, "  enable: true", "  kinds: [unmapped-code, guesswork]")
    r = ag(project, "feedback")
    assert r.code == 2 and "guesswork" in r.err

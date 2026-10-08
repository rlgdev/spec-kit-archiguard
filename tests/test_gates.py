"""The gates on examples/orders: A0, A3, A4, the step runner (budget, no-progress, escalation) and sign-off."""

from __future__ import annotations

import json

from conftest import (
    ARCH_201_ROW,
    FEATURE,
    analyze_report,
    commit_all,
    design_signed,
    edit,
    git,
    read,
    repair_plan,
    write,
)

GATES = f"{FEATURE}/gates"


def verdict(root, gate, check):
    return json.loads(read(root, f"{GATES}/{gate}/{check}.json"))


# --------------------------------------------------------------------------- #
# /speckit.plan                                                                 #
# --------------------------------------------------------------------------- #


def test_plan_step_a_passes_and_prints_the_contract(project, ag):
    r = ag(project, "run", "plan", "a")
    assert r.code == 0, r
    for check in ("A0.1", "A0.2", "A0.3", "A3.1"):
        assert f"[PASS] {check[:2]} · {check}" in r.out
    assert "| ARCH-201 |" in r.out                      # the conformance table the plan must fill
    assert "T0xx [FITNESS]" in r.out                    # the fitness-test tasks tasks.md must carry
    assert verdict(project, "A0", "A0.1")["status"] == "pass"
    applicable = json.loads(read(project, f"{GATES}/applicable-rules.json"))
    assert {"ARCH-101", "ARCH-201", "ARCH-301", "ARCH-401", "ARCH-501"} <= {r["id"] for r in applicable["rules"]}


def test_plan_step_b_finds_the_missing_rule_then_passes_after_repair(project, ag):
    r = ag(project, "run", "plan", "b")
    assert r.code == 1, r
    assert "iteration 0 (budget 3)" in r.out
    assert "[A3.3] ARCH-201" in r.out
    assert "RESOLVE - fix every item, then run the same command again" in r.out
    assert "fix:   add: | ARCH-201 |" in r.out
    repair_plan(project)
    r = ag(project, "run", "plan", "b")
    assert r.code == 0, r
    assert "iteration 1 (budget 3)" in r.out
    assert "PASS after 1 repair iteration(s)" in r.out
    combined = json.loads(read(project, f"{GATES}/plan-b.json"))
    assert combined["status"] == "pass"
    assert [h["status"] for h in combined["history"]] == ["violation", "pass"]


def test_same_findings_again_escalate_without_waiting_for_the_budget(project, ag):
    assert ag(project, "run", "plan", "b").code == 1
    r = ag(project, "run", "plan", "b")
    assert r.code == 3, r
    assert "no progress: the same findings came back as in iteration 0" in r.out
    note = read(project, f"{GATES}/escalation-plan-b.md")
    assert "TODO(agent)" in note and "ARCH-201" in note


def test_budget_is_one_counter_per_insertion_point(project, ag):
    plan = f"{FEATURE}/plan.md"
    codes = []
    # a different finding every iteration: no repeated fingerprint, so only the budget stops the loop
    for n in range(4):
        edit(project, plan, "| ARCH-101 | HTTP APIs", f"| ARCH-10{n + 5} | HTTP APIs") if n == 0 else edit(
            project, plan, f"| ARCH-10{n + 4} |", f"| ARCH-10{n + 5} |")
        codes.append(ag(project, "run", "plan", "b").code)
    assert codes == [1, 1, 1, 3]
    combined = json.loads(read(project, f"{GATES}/plan-b.json"))
    assert combined["escalation"]["reason"] == "the budget of 3 repair iteration(s) is used up"
    # step A starts a new run of the command: the counter is reset
    assert ag(project, "run", "plan", "a").code == 0
    r = ag(project, "run", "plan", "b")
    assert "iteration 0 (budget 3)" in r.out


def test_budget_from_the_step_overrides_the_default(project, ag):
    cfg = ".specify/extensions/archiguard/archiguard-config.yml"
    edit(project, cfg, "    step_b:\n      max_iterations: 3\n      gates:\n        - { gate: A0, run: [A0.5] }",
         "    step_b:\n      max_iterations: 1\n      gates:\n        - { gate: A0, run: [A0.5] }")
    plan = f"{FEATURE}/plan.md"
    assert ag(project, "run", "plan", "b").code == 1
    edit(project, plan, "| ARCH-101 | HTTP APIs", "| ARCH-109 | HTTP APIs")
    r = ag(project, "run", "plan", "b")
    assert r.code == 3 and "budget of 1 repair" in r.out, r


def test_a0_domain_map_pin_mismatch_cannot_be_repaired(project, ag):
    edit(project, f"{FEATURE}/handover.yml", 'map_version: "1.4.0"', 'map_version: "1.3.0"')
    r = ag(project, "run", "plan", "a")
    assert r.code == 3, r
    assert "[no repair - needs a person]" in r.out
    assert verdict(project, "A0", "A0.1")["status"] == "violation"
    assert "TODO(agent)" in read(project, f"{GATES}/escalation-plan-a.md")


def test_a_stop_names_the_other_extensions_hooks_it_skips(project, ag):
    """A wrapped command that stops at a gate never reaches its post-execution hooks: the runner names them."""
    write(project, ".specify/extensions.yml", (
        "hooks:\n  after_plan:\n"
        "  - extension: git\n    command: speckit.git.commit\n    enabled: true\n    optional: true\n"
        "  - extension: agent-context\n    command: speckit.agent-context.update\n    enabled: true\n    optional: false\n"
        "  - extension: archiguard\n    command: speckit.archiguard.plangate\n    enabled: true\n"
        "  - extension: other\n    command: speckit.other.thing\n    enabled: false\n"
        "  after_tasks:\n  - extension: git\n    command: speckit.git.tasks\n    enabled: true\n"))
    edit(project, f"{FEATURE}/handover.yml", 'map_version: "1.4.0"', 'map_version: "1.3.0"')
    names = ("NOT RUN: /speckit.plan ends here, so these after_plan hooks of other extensions do not run: "
             "git: speckit.git.commit (optional); agent-context: speckit.agent-context.update. Tell the user; they run "
             "when the command is run again and passes.")
    r = ag(project, "run", "plan", "a", "--via", "hook")       # the hooks path: a before_plan hook stops the command
    assert r.code == 3 and names in r.out, r
    assert names not in ag(project, "run", "plan", "a").out    # by hand: no command is stopped
    edit(project, f"{FEATURE}/handover.yml", 'map_version: "1.3.0"', 'map_version: "1.4.0"')
    assert "NOT RUN" not in ag(project, "run", "plan", "a", "--via", "hook").out   # no stop, nothing skipped


def test_a0_entity_owned_by_another_context(project, ag):
    edit(project, f"{FEATURE}/handover.yml", "D-001: { entity: Order, context: orders }",
         "D-001: { entity: Payment, context: orders }")
    r = ag(project, "run", "plan", "a")
    assert r.code == 3, r
    assert "A0.3" in r.out and "payments" in r.out


def test_a0_relation_not_in_the_domain_map(project, ag):
    plan = f"{FEATURE}/plan.md"
    edit(project, plan, "| Request payment of the order total | payments | customer-supplier |",
         "| Request payment of the order total | payments | partnership |")
    r = ag(project, "run", "plan", "b")
    assert r.code == 1, r
    assert "[A0.5]" in r.out and "partnership" in r.out


def test_vocabulary_runs_in_report_mode(project, ag):
    r = ag(project, "run", "plan", "b")
    assert "A0.4 vocabulary" in r.out and "report mode" in r.out
    assert verdict(project, "A0", "A0.4")["status"] == "pass"


def test_deviation_needs_an_approved_ledger_entry(project, ag):
    plan = f"{FEATURE}/plan.md"
    repair_plan(project)
    edit(project, plan, ARCH_201_ROW, "| ARCH-201 | Layers | deviation | Project Structure | ADR-0099 |")
    r = ag(project, "run", "plan", "b")
    assert r.code == 1, r
    assert "ADR-0099" in r.out
    edit(project, plan, "| ARCH-201 | Layers | deviation | Project Structure | ADR-0099 |",
         "| ARCH-201 | Layers | deviation | Project Structure | ADR-0007 |")
    r = ag(project, "run", "plan", "b")
    assert "ADR-0007" in r.out and r.code == 1   # approved, but for ARCH-501, not ARCH-201
    assert ag(project, "ledger", "add", "--id", "ADR-0010", "--status", "approved", "--type", "adr", "--title", "Flat module",
              "--rule", "ARCH-201", "--owner", "Orders tech lead", "--approver", "Lead architect",
              "--expires", "2099-12-31").code == 0
    edit(project, plan, "| ADR-0007 |", "| ADR-0010 |")
    r = ag(project, "run", "plan", "b")
    assert r.code == 0, r
    assert "[WAIV] A3 · A3.3" in r.out


def test_not_applicable_needs_an_allowed_reason(project, ag):
    plan = f"{FEATURE}/plan.md"
    repair_plan(project)
    edit(project, plan, ARCH_201_ROW, "| ARCH-201 | Layers | not applicable | - | too small |")
    r = ag(project, "run", "plan", "b")
    assert r.code == 1 and "too small" in r.out, r
    edit(project, plan, "| ARCH-201 | Layers | not applicable | - | too small |",
         "| ARCH-201 | Layers | not applicable | - | no-new-component |")
    assert ag(project, "run", "plan", "b").code == 0


# --------------------------------------------------------------------------- #
# /speckit.tasks                                                                #
# --------------------------------------------------------------------------- #


def test_tasks_guard(project, ag):
    tasks = f"{FEATURE}/tasks.md"
    assert ag(project, "run", "tasks", "b").code == 0
    edit(project, tasks, "- [ ] T007 [FITNESS] Verify the layering - ARCH-201\n", "")
    r = ag(project, "run", "tasks", "b")
    assert r.code == 1 and "ARCH-201" in r.out, r
    edit(project, tasks, "Write the acceptance test for placing an order in src/test/java/com/acme/orders/PlaceOrderTest.java - Carries: AC-001, BR-001",
         "Write the order screen in src/main/java/com/acme/orders/api/OrderController.java - Carries: AC-001, BR-001")
    r = ag(project, "run", "tasks", "b")
    assert "AC-001 has no test task" in r.out, r


# --------------------------------------------------------------------------- #
# Sign-off and /speckit.implement                                               #
# --------------------------------------------------------------------------- #


def test_implement_is_refused_before_the_sign_off(project, ag):
    r = ag(project, "run", "implement", "a")
    assert r.code == 3, r
    assert "sign" in r.out.lower()


def test_signoff_is_refused_on_red_evidence(project, ag):
    edit(project, ".specify/extensions/archiguard/archiguard-config.yml",
         "  require: [speckit.plan, speckit.tasks]", "  require: [speckit.plan, speckit.tasks, A3.6]")
    analyze_report(project, critical=1)
    r = ag(project, "signoff", "--by", "Lead architect")
    assert r.code == 1, r
    assert "speckit.plan gates: violation" in r.err and "A3.6: violation" in r.err
    assert "speckit.tasks" not in r.err
    assert not (project / GATES / "signoff.json").exists()
    repair_plan(project)
    analyze_report(project, critical=0)
    r = ag(project, "signoff", "--by", "Lead architect")
    assert r.code == 1 and "uncommitted changes" in r.err and "plan.md" in r.err, r   # sign a commit, not a draft
    commit_all(project, "T000 UC-001 design")
    git(project, "checkout", "-q", "-b", "experiment")
    r = ag(project, "signoff", "--by", "Lead architect")
    assert r.code == 1 and "feature branch" in r.err, r
    git(project, "checkout", "-q", "001-place-order")
    assert ag(project, "signoff", "--by", "Lead architect").code == 0
    r = ag(project, "signoff", "--by", "Someone else")
    assert r.code == 1 and "already signed" in r.err, r


def test_signoff_then_implement_entry_and_pin_check(project, ag):
    design_signed(ag, project)
    signoff = json.loads(read(project, f"{GATES}/signoff.json"))
    assert signoff["by"] == "Lead architect" and signoff["evidence"]["speckit.plan"] == "pass"
    assert "plan.md" in signoff["hashes"]
    assert ag(project, "run", "implement", "a").code == 0
    # a design change after the sign-off moves a pin: no agent may repair that
    edit(project, f"{FEATURE}/plan.md", "Java 21", "Java 25")
    r = ag(project, "run", "implement", "a")
    assert r.code == 3 and "plan.md" in r.out, r
    # re-open, repair, sign again
    assert ag(project, "reopen", "--by", "Lead architect", "--reason", "Java upgrade").code == 0
    assert not (project / GATES / "signoff.json").exists()
    commit_all(project, "T000 UC-001 Java upgrade")
    assert ag(project, "signoff", "--by", "Lead architect").code == 0
    assert ag(project, "run", "implement", "a").code == 0


def test_fitness_functions_find_the_planted_violations_and_tick_the_tasks(project, ag):
    design_signed(ag, project)
    cfg = ".specify/extensions/archiguard/archiguard-config.yml"
    edit(project, cfg, "        - { gate: A4, run: [A4.4] }", "        - { gate: A4, run: [A4.4, A4.6] }")
    commit_all(project, "T010 UC-001 enable traceability")
    r = ag(project, "run", "implement", "b")
    assert r.code == 1, r
    assert "ARCH-201" in r.out and "Order.java:3" in r.out
    assert "ARCH-301" in r.out and "com.acme.payments.internal.PaymentGateway" in r.out
    tasks = read(project, f"{FEATURE}/tasks.md")
    assert "- [x] T006 [FITNESS]" in tasks and "- [x] T009 [FITNESS]" in tasks
    assert "- [ ] T007 [FITNESS]" in tasks and "- [ ] T008 [FITNESS]" in tasks
    order = "src/main/java/com/acme/orders/domain/Order.java"
    edit(project, order, "import com.acme.orders.api.OrderController;   // ARCH-201: the domain layer must not depend on the api layer\n", "")
    controller = "src/main/java/com/acme/orders/api/OrderController.java"
    edit(project, controller, "import com.acme.payments.internal.PaymentGateway;   // ARCH-301: payments publishes only com.acme.payments.api",
         "import com.acme.payments.api.PaymentsClient;")
    write(project, "src/test/java/com/acme/orders/OrderLineTest.java", "class OrderLineTest {}\n")
    commit_all(project, "fix the layering")
    r = ag(project, "run", "implement", "b")
    assert r.code == 1, r
    # A4.6: a commit without a task or requirement id, and a test file that verifies no id
    assert "commit 'fix the layering' names no task" in r.out
    assert "OrderLineTest.java carries no requirement id" in r.out
    write(project, "src/test/java/com/acme/orders/OrderLineTest.java", "class OrderLineTest { /* BR-001 */ }\n")
    commit_all(project, "T004 BR-001 order line test")
    r = ag(project, "run", "implement", "b")
    assert "OrderLineTest.java" not in r.out
    assert "names no task" in r.out   # history is not rewritten: the earlier commit is still reported


def test_rule_waived_in_the_ledger(project, ag):
    design_signed(ag, project)
    assert ag(project, "ledger", "add", "--id", "WVR-0001", "--status", "approved", "--type", "waiver", "--title", "Legacy import",
              "--rule", "ARCH-301", "--owner", "Orders tech lead", "--approver", "Lead architect",
              "--expires", "2099-12-31").code == 0
    r = ag(project, "run", "implement", "b")
    assert r.code == 1, r                               # ARCH-201 is still open ...
    assert "[A4.4] ARCH-301" not in r.out               # ... ARCH-301 is waived
    assert "1 waived" in r.out
    a44 = verdict(project, "A4", "A4.4")
    assert any(w["waiver"] == "WVR-0001" for w in a44["waived"])


def test_verify_runs_every_gate_once_without_state(project, ag):
    r = ag(project, "verify", "plan")
    assert r.code == 1, r
    assert not (project / GATES / ".state" / "plan-b.json").exists()
    repair_plan(project)
    assert ag(project, "verify", "plan").code == 0


def test_missing_rulebook_fails_closed(project, ag):
    edit(project, ".specify/extensions/archiguard/archiguard-config.yml",
         "  rulebook: acme-standards@v2026.10.1", "  rulebook: acme-standards@v2027.1.0")
    r = ag(project, "run", "plan", "b")
    assert r.code == 2, r
    assert "CANNOT EVALUATE" in r.out


def test_hook_and_inline_paths_never_both_run(project, ag):
    # the example has no preset: integration inline falls back to the hooks
    edit(project, ".specify/extensions/archiguard/archiguard-config.yml", "integration: hooks", "integration: inline")
    r = ag(project, "run", "plan", "b", "--via", "inline")
    assert r.code == 0 and "skipped" in r.out and "preset is not installed" in r.out
    r = ag(project, "run", "plan", "b", "--via", "hook")
    assert r.code == 1
    # with the preset's command files in place the inline step runs and the hook step is skipped
    for name in ("speckit.plan", "speckit.tasks", "speckit.implement"):
        write(project, f".specify/presets/archiguard-templates/commands/{name}.md", "---\n---\n")
    assert "skipped" in ag(project, "run", "plan", "b", "--via", "hook").out
    assert ag(project, "run", "plan", "b", "--via", "inline").code in (1, 3)


def test_check_command_runs_single_checks(project, ag):
    r = ag(project, "check", "A3", "A3.3", "--json")
    data = json.loads(r.out)
    assert r.code == 1
    statuses = {v["check"]: v["status"] for v in (data if isinstance(data, list) else data.get("verdicts", [data]))}
    assert statuses.get("A3.3") == "violation"


def test_unknown_check_is_a_usage_error(project, ag):
    r = ag(project, "check", "A3", "A3.99")
    assert r.code == 2


def test_any_design_artefact_change_after_the_sign_off_is_caught(project, ag):
    design_signed(ag, project)
    assert ag(project, "run", "implement", "a").code == 0
    edit(project, f"{FEATURE}/contracts/orders.yaml", "openapi", "openapi")   # unchanged content: still green
    assert ag(project, "run", "implement", "a").code == 0
    write(project, f"{FEATURE}/contracts/extra.yaml", "openapi: 3.0.0\n")
    edit(project, f"{FEATURE}/data-model.md", "- sku, quantity, price", "- sku, quantity, price, discount")
    r = ag(project, "run", "implement", "a")
    assert r.code == 3, r
    assert "contracts/extra.yaml was added" in r.out and "data-model.md changed" in r.out
    assert "archiguard reopen" in r.out


def test_domain_map_move_after_the_sign_off_stays_red(project, ag):
    design_signed(ag, project)
    edit(project, ".specify/standards/domain-map.yaml", 'domain_map_version: "1.4.0"', 'domain_map_version: "1.4.1"')
    edit(project, ".specify/extensions/archiguard/archiguard-config.yml", 'pin: "1.4.0"', 'pin: "1.4.1"')
    edit(project, f"{FEATURE}/handover.yml", 'map_version: "1.4.0"', 'map_version: "1.4.1"')
    for _ in range(2):   # the finding does not clear itself on the next run
        r = ag(project, "check", "A0", "A0.1")
        assert r.code == 3 and "moved from 1.4.0 to 1.4.1 after the design authority sign-off" in r.out, r


def test_traceability_needs_a_task_and_a_requirement_id(project, ag):
    design_signed(ag, project)
    for message, ok in (("T011 tidy imports", False), ("BR-001 tidy imports", False), ("T011 BR-001 tidy imports", True)):
        write(project, "src/main/java/com/acme/orders/application/Note.java", f"class Note {{ /* {message} */ }}\n")
        commit_all(project, message)
        r = ag(project, "check", "A4", "A4.6")
        assert (f"commit '{message}' names no" in r.out) is (not ok), r
    edit(project, f"{FEATURE}/tasks.md", "Create the module skeleton", "Create the module skeleton and the README")
    commit_all(project, "tidy the tasks")              # design and evidence commits are not code
    assert "tidy the tasks" not in ag(project, "check", "A4", "A4.6").out

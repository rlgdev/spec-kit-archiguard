"""Configuration (budgets, ceiling, local overrides, validation), the YAML reader and the standards binding."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import REPO, commit_all, edit, git, read, write
from archiguard_core import yamlio
from archiguard_core.common import ArchiGuardError
from archiguard_core.config import DEFAULT_PIPELINE, load_config

CFG = ".specify/extensions/archiguard/archiguard-config.yml"
LOCAL = ".specify/extensions/archiguard/local-config.yml"


def cfg_with(root: Path, text: str):
    write(root, CFG, text)
    return load_config(root)


# --------------------------------------------------------------------------- #
# defaults and the template                                                     #
# --------------------------------------------------------------------------- #


def test_template_equals_the_built_in_defaults(tmp_path):
    (tmp_path / ".specify").mkdir()
    from_template = load_config(tmp_path, str(REPO / "config-template.yml"))
    built_in = load_config(tmp_path)
    assert from_template.data == built_in.data
    assert built_in["pipeline"]["speckit.plan"]["step_a"][0] == {
        "gate": "A0", "run": ["A0.1", "A0.2", "A0.3"], "repair": False, "mode": None}
    assert [e["gate"] for e in built_in["pipeline"]["speckit.plan"]["step_b"]["gates"]] == ["scope", "A0", "A0", "A3"]
    assert built_in.budget("speckit.plan") == 3 and built_in.ceiling == 6
    assert set(built_in["loops"]) == {"handover_validator", "implement_converge", "handover_entry", "test_loop"}
    assert set(DEFAULT_PIPELINE) == {"speckit.plan", "speckit.tasks", "speckit.implement"}


def test_budget_above_the_ceiling_is_refused(project):
    text = read(project, CFG).replace("    step_b:\n      max_iterations: 3", "    step_b:\n      max_iterations: 7")
    with pytest.raises(ArchiGuardError, match="exceeds the ceiling of 6"):
        cfg_with(project, text)
    with pytest.raises(ArchiGuardError, match="loops.test_loop"):
        cfg_with(project, read(project, CFG).replace("    step_b:\n      max_iterations: 7", "    step_b:\n      max_iterations: 3")
                 + "loops:\n  test_loop: 9\n")


@pytest.mark.parametrize("snippet, message", [
    ("pipline: {}\n", "unknown setting(s) pipline"),
    ("defaults:\n  max_iteration: 3\n", "defaults: unknown setting(s) max_iteration"),
    ("integration: sometimes\n", "integration must be"),
    ("mode: strict\n", "mode must be"),
])
def test_invalid_settings_are_named(project, snippet, message):
    text = read(project, CFG)
    for key in ("integration:", "mode:"):
        if snippet.startswith(key):
            text = "\n".join(line for line in text.split("\n") if not line.startswith(key)) + "\n"
    if snippet.startswith("defaults:"):
        text = text.replace("defaults:\n  max_iterations: 3\n", "")
    with pytest.raises(ArchiGuardError, match=message.replace("(", r"\(").replace(")", r"\)")):
        cfg_with(project, text + snippet)


def test_pipeline_entry_validation(project):
    base = read(project, CFG)
    with pytest.raises(ArchiGuardError, match="cannot raise its mode to 'enforce'"):
        cfg_with(project, base.replace("mode: enforce", "mode: report").replace(
            "{ gate: A0, run: [A0.4], mode: report }", "{ gate: A0, run: [A0.4], mode: enforce }"))
    with pytest.raises(ArchiGuardError, match="cannot be repaired by the agent"):
        cfg_with(project, base.replace("{ gate: A0, run: [A0.1, A0.2, A0.3], repair: false }",
                                       "{ gate: A0, run: [A0.1, A0.2, A0.3], repair: true }"))
    with pytest.raises(ArchiGuardError, match="archiGuard plugs into"):
        cfg_with(project, base.replace("  speckit.tasks:", "  speckit.clarify:\n    step_a: []\n  speckit.tasks:"))
    with pytest.raises(ArchiGuardError, match="gate 'B9' is not registered"):
        cfg_with(project, base.replace("{ gate: A3, run: [A3.5] }", "{ gate: B9, run: [B9.1] }"))
    with pytest.raises(ArchiGuardError, match="A3.2"):
        cfg_with(project, base.replace("{ gate: A3, run: [A3.5] }", "{ gate: A3, run: [A3.2] }"))


def test_dotted_pipeline_keys_and_list_step_b(project):
    cfg = cfg_with(project, read(project, CFG).replace("  speckit.tasks:\n    step_b:\n      gates:\n",
                                                       "  speckit.tasks:\n    step_b:\n"))
    assert cfg.step_entries("tasks", "b")[0]["gate"] == "A3"
    assert cfg.budget("tasks") == 3


# --------------------------------------------------------------------------- #
# local overrides: workstation only, a closed list of keys                      #
# --------------------------------------------------------------------------- #


def test_local_overrides_apply_on_a_workstation_only(project, monkeypatch):
    write(project, LOCAL, "integration: inline\ndefaults:\n  max_iterations: 5\nmode: report\nloops:\n  test_loop: 2\n")
    cfg = load_config(project)
    assert cfg["integration"] == "inline"
    assert cfg["defaults"]["max_iterations"] == 5
    assert cfg["loops"]["test_loop"] == 2
    assert cfg["mode"] == "enforce"
    assert any("'mode' cannot be overridden locally" in n for n in cfg.notes)
    monkeypatch.setenv("CI", "true")
    ci = load_config(project)
    assert ci["integration"] == "hooks" and ci["loops"]["test_loop"] == 3 and ci.ci


def test_local_override_cannot_pass_the_ceiling(project):
    write(project, LOCAL, "defaults:\n  max_iterations: 9\n")
    with pytest.raises(ArchiGuardError, match="ceiling"):
        load_config(project)


def test_environment_overrides(project, monkeypatch):
    monkeypatch.setenv("ARCHIGUARD_MAX_ITERATIONS", "2")
    monkeypatch.setenv("ARCHIGUARD_INTEGRATION", "inline")
    cfg = load_config(project)
    assert cfg.budget("plan") == 2 and cfg["integration"] == "inline"
    monkeypatch.setenv("ARCHIGUARD_CI", "1")
    cfg = load_config(project)
    assert cfg.budget("plan") == 3 and cfg["integration"] == "hooks"


# --------------------------------------------------------------------------- #
# YAML reader (standard library only) - parity with PyYAML on every shipped file #
# --------------------------------------------------------------------------- #


def shipped_yaml():
    skip = {"dist", ".git", "node_modules"}
    for path in sorted(REPO.rglob("*")):
        if path.suffix in (".yml", ".yaml") and not skip & set(path.relative_to(REPO).parts) \
                and ".github" not in path.parts:
            yield path


@pytest.mark.parametrize("path", list(shipped_yaml()), ids=lambda p: p.relative_to(REPO).as_posix())
def test_yaml_parity_with_pyyaml(path):
    yaml = pytest.importorskip("yaml")
    text = path.read_text(encoding="utf-8")
    assert yamlio.parse_builtin(text, str(path)) == yaml.safe_load(text)


def test_yaml_round_trip():
    data = {"a": 1, "b": [1, "two", {"c": None, "d": True}], "e": "x: y", "f": "", "g": "#not a comment",
            "h": {"nested": ["p", "q"]}, "i": 1.5, "j": "2026-01-01", "k": "yes"}
    assert yamlio.loads(yamlio.dumps(data)) == data


def test_yaml_errors_name_the_line():
    with pytest.raises(ArchiGuardError, match=r"x\.yml:2: unexpected indentation"):
        yamlio.parse_builtin("a: 1\n  b: [2\n", "x.yml")
    with pytest.raises(ArchiGuardError):
        yamlio.parse_builtin("a: &anchor 1\nb: *anchor\n", "x.yml")


# --------------------------------------------------------------------------- #
# standards: rulebook, lock, drift, applicable rules                            #
# --------------------------------------------------------------------------- #


def test_example_rulebook_is_valid(project, ag):
    r = ag(project, "validate-standards", feature=False)
    assert r.code == 0 and "rulebook is valid" in r.out, r
    r = ag(project, "validate-standards", str(REPO / "templates" / "rulebook"), feature=False)
    assert r.code == 0, r


def test_rulebook_problems_are_reported(project, ag):
    rules = ".specify/standards/skills/layering/rules.yml"
    edit(project, rules, "    level: must", "    level: mandatory")
    r = ag(project, "validate-standards", feature=False)
    assert r.code == 1 and "ARCH-201" in r.out, r


def test_lock_is_current_and_drift_is_detected(project, ag):
    r = ag(project, "resolve", "--check", feature=False)
    assert r.code == 0, r
    commit_all(project, "an unrelated commit")          # project commits never drift the lock
    assert ag(project, "resolve", "--check", feature=False).code == 0
    edit(project, ".specify/standards/skills/secrets/rules.yml", "No credentials in source code",
         "No credentials or tokens in source code")
    r = ag(project, "resolve", "--check", feature=False)
    assert r.code == 1 and "ARCH-401" in r.out, r
    # the gates read the committed lock; the drift is the CI required check's job
    r = ag(project, "ci", feature=False)
    assert r.code == 1 and "ARCH-401 changed" in r.out, r
    assert ag(project, "resolve", feature=False).code == 0
    assert ag(project, "resolve", "--check", feature=False).code == 0
    # a lock that no longer matches the config is refused by every gate that needs the rules (fail-closed)
    edit(project, CFG, "  profile: java-service", "  profile: java-service\n  include: [ARCH-601]")
    r = ag(project, "run", "plan", "b")
    assert r.code == 2 and "resolve" in r.out, r


def test_excluding_a_must_rule_needs_a_waiver(project, ag):
    edit(project, CFG, "  lock: .specify/archiguard/standards.lock.yml",
         "  lock: .specify/archiguard/standards.lock.yml\n  exclude: [ARCH-401]")
    r = ag(project, "resolve", feature=False)
    assert r.code == 2 and "ARCH-401" in r.err and "waiver" in r.err, r
    assert ag(project, "ledger", "add", "--id", "WVR-0401", "--status", "approved", "--type", "waiver", "--title", "Vault migration",
              "--rule", "ARCH-401", "--owner", "o", "--approver", "a", "--expires", "2099-01-01").code == 0
    edit(project, CFG, "exclude: [ARCH-401]", "exclude: [{ rule: ARCH-401, waiver: WVR-0401 }]")
    r = ag(project, "resolve", feature=False)
    assert r.code == 0 and "1 excluded" in r.out, r


def test_rules_command_lists_the_applicable_rules(project, ag):
    r = ag(project, "rules")
    assert r.code == 0, r
    for rid in ("ARCH-101", "ARCH-201", "ARCH-301", "ARCH-401", "ARCH-501"):
        assert rid in r.out
    assert "ARCH-601" not in r.out or "payments" in r.out   # the payments pack applies only in its context


def test_scaffold_writes_the_starting_files(project, ag, tmp_path):
    out = tmp_path / "map.yaml"
    assert ag(project, "scaffold", "domain-map", "--out", str(out), feature=False).code == 0
    assert "domain_map_version" in out.read_text(encoding="utf-8")
    assert ag(project, "scaffold", "domain-map", "--out", str(out), feature=False).code == 2   # no silent overwrite
    rb = tmp_path / "rb"
    assert ag(project, "scaffold", "rulebook", "--out", str(rb), feature=False).code == 0
    assert ag(project, "validate-standards", str(rb), feature=False).code == 0


def test_rulebook_in_its_own_checkout_is_pinned_by_tag_and_commit(project, ag):
    std = project / ".specify" / "standards"
    git(std, "init", "-q")
    git(std, "add", "-A")
    git(std, "commit", "-q", "-m", "standards")
    edit(project, ".specify/standards/rulebook.yml", "version: v2026.10.1", "version: v2026.10.2")
    git(std, "commit", "-qam", "next")
    r = ag(project, "resolve", feature=False)
    assert r.code == 2 and "check out the pinned tag" in r.err, r
    git(std, "tag", "v2026.10.1")
    r = ag(project, "resolve", feature=False)
    assert r.code == 0, r
    lock = read(project, ".specify/archiguard/standards.lock.yml")
    assert "commit: " + git(std, "rev-parse", "HEAD") in lock


def test_unknown_options_and_gate_settings_are_errors(project):
    base = read(project, CFG)
    with pytest.raises(ArchiGuardError, match=r"options.scope: unknown setting\(s\) require_deferal_reference"):
        cfg_with(project, base + "options:\n  scope: { require_deferal_reference: true }\n")
    with pytest.raises(ArchiGuardError, match="options.A9.9: no such check"):
        cfg_with(project, base + "options:\n  A9.9: { x: 1 }\n")
    with pytest.raises(ArchiGuardError, match=r"gates.scope: unknown setting\(s\) sha265"):
        cfg_with(project, base + "gates:\n  scope: { sha265: abc }\n")


def test_local_budget_override_keeps_a_list_form_step(project):
    text = read(project, CFG).replace("  speckit.tasks:\n    step_b:\n      gates:\n", "  speckit.tasks:\n    step_b:\n")
    write(project, CFG, text)
    write(project, LOCAL, "pipeline:\n  speckit.tasks:\n    step_b:\n      max_iterations: 2\n")
    cfg = load_config(project)
    assert cfg.budget("tasks") == 2
    assert [e["gate"] for e in cfg.step_entries("tasks", "b")] == ["A3"]

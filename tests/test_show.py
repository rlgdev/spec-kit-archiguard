"""archiguard show: the setup in force and the skills of the rulebook, read-only."""

from __future__ import annotations

import json
import shutil

from conftest import REPO, commit_all, edit, git, read, write

CFG = ".specify/extensions/archiguard/archiguard-config.yml"
SKILLS = "api-contracts context-boundaries data-ownership layering payments-pci secrets".split()
LOCK = ".specify/archiguard/standards.lock.yml"
SECRETS_RULES = ".specify/standards/skills/secrets/rules.yml"
PROFILE = ".specify/standards/profiles/java-service.yml"
ARCH_402 = """
  - id: ARCH-402
    title: No secrets in configuration files
    level: should
    checks:
      - { target: code, kind: forbid_text, files: ["**/*.properties"], pattern: "password=" }
"""


def show(ag, root, *args):
    return ag(root, "show", *args, feature=False)


def test_show_lists_every_skill_in_force_with_its_skill_md_and_rules(project, ag):
    r = show(ag, project)
    assert r.code == 0, r
    out = r.out
    assert out.startswith("archiGuard ") and " | show" in out.split("\n")[0]
    assert "integration   : hooks" in out and "Policy:" in out                 # the configure report comes first
    assert "in force      : 6 skills, 6 rules from .specify/archiguard/standards.lock.yml" in out, r
    assert "(acme-standards@v2026.10.1; profile java-service; pack payments-pci)" in out
    for skill in SKILLS:
        assert f".specify/standards/skills/{skill}/SKILL.md" in out, skill
    assert "Layered architecture inside a bounded context. Read before placing any class." in out   # the description
    assert "ARCH-601   must   Card numbers are never logged  [code · declared check · via pack:payments-pci · context payments]" in out
    assert "[plan · agent judgement · via profile:java-service]" in out                               # ARCH-501
    assert "stacks        : java (detected)" in out
    assert "not in force  : none" in out
    assert "rulebook drift: none" in out
    assert "checks:" not in out
    verbose = show(ag, project, "--verbose").out
    assert "checks: code:layers" in verbose
    assert "Every HTTP API is described by an OpenAPI 3 document" in verbose                          # ARCH-101's text
    assert "Every HTTP API is described by an OpenAPI 3 document" not in out

    data = json.loads(show(ag, project, "--json").out)
    assert data["command"] == "show" and data["dry_run"] is True
    skills = data["skills"]
    assert [s["skill"] for s in skills["in_force"]] == SKILLS
    pci = next(s for s in skills["in_force"] if s["skill"] == "payments-pci")
    assert pci["skill_md_exists"] is True and pci["rules"][0]["sources"] == ["pack:payments-pci"]
    assert skills["drift"] == [] and skills["not_in_force"] == [] and skills["stacks"] == ["java"]


def test_show_writes_nothing_and_names_the_hooks_configure_would_change(project, ag):
    write(project, ".specify/extensions.yml", (
        "installed:\n- archiguard\nhooks:\n  before_plan:\n  - extension: archiguard\n"
        "    command: speckit.archiguard.planentry\n    enabled: false\n    optional: false\n"))
    commit_all(project, "registry")
    r = show(ag, project)
    assert r.code == 0, r
    assert "speckit.archiguard.planentry       off   (the config wants it on)" in r.out, r
    assert "1 hook setting(s) differ from the config - run 'archiguard configure'" in r.out
    assert git(project, "status", "--porcelain") == ""                   # no registry change, no gates/ evidence
    assert ag(project, "configure", feature=False).code == 0
    r = show(ag, project)
    assert "speckit.archiguard.planentry       on\n" in r.out and "Every hook matches the config." in r.out, r


def test_show_a_partly_selected_skill_a_skill_left_out_and_an_excluded_rule(project, ag):
    write(project, SECRETS_RULES, read(project, SECRETS_RULES) + ARCH_402)
    edit(project, PROFILE, "skills: [api-contracts, layering, context-boundaries, secrets, data-ownership]",
         "skills: [api-contracts, layering, context-boundaries, data-ownership]\nrules: [ARCH-401]")
    edit(project, ".specify/standards/skills/layering/rules.yml", "applies_when: { stack: [java] }",
         "applies_when: { stack: [go] }")
    assert ag(project, "resolve", feature=False).code == 0
    out = show(ag, project).out
    assert "secrets                1 of 2 rules  .specify/standards/skills/secrets/SKILL.md" in out, out
    assert "not selected: ARCH-402" in out
    assert "stack go - not detected here" in out
    # a must rule excluded with an approved waiver: the skill has no rule in the lock any more
    r = ag(project, "ledger", "add", "--id", "ADR-0042", "--type", "waiver", "--title", "legacy credentials",
           "--rule", "ARCH-401", "--owner", "Orders tech lead", "--approver", "Lead architect",
           "--status", "approved", "--expires", "2099-01-31", feature=False)
    assert r.code == 0, r
    edit(project, CFG, "  lock: .specify/archiguard/standards.lock.yml",
         "  lock: .specify/archiguard/standards.lock.yml\n  exclude: [{ rule: ARCH-401, waiver: ADR-0042 }]")
    assert ag(project, "resolve", feature=False).code == 0
    out = show(ag, project).out
    assert "in force      : 5 skills, 5 rules" in out, out
    assert "not in force  : 1 skill of acme-standards with no rule in the lock" in out
    assert "secrets              2 rules    [excluded: ARCH-401] Secrets never live" in out
    assert "excluded      : ARCH-401 (must) waiver ADR-0042 until 2099-01-31" in out
    data = json.loads(show(ag, project, "--json").out)["skills"]
    assert data["not_in_force"] == [{"skill": "secrets", "rules": 2, "excluded": ["ARCH-401"],
                                     "description": "Secrets never live in code or configuration in the repository."}]


def test_show_without_a_lock_a_stale_lock_and_drift(project, ag):
    (project / LOCK).unlink()
    out = show(ag, project).out
    assert "in force      : none - the gates and the agent read the skills from the standards lock" in out, out
    assert "available     : 6 skills in acme-standards; 'archiguard resolve' would put 6 rules of the 6 marked * in force" in out
    assert "    * payments-pci         1 rule     Card data handling for the payments context." in out
    assert json.loads(show(ag, project, "--json").out)["skills"]["would_select"] == SKILLS
    assert ag(project, "resolve", feature=False).code == 0
    edit(project, SECRETS_RULES, "No credentials in source code", "No credentials or tokens in source code")
    assert "rulebook drift: ARCH-401 changed - run 'archiguard resolve'" in show(ag, project).out
    edit(project, CFG, "  profile: java-service", "  profile: java-service\n  include: [ARCH-601]")
    out = show(ag, project).out
    assert "STALE         : the standards section of archiguard-config.yml changed" in out, out
    assert "rulebook drift: config changed" in out


def test_show_from_the_lock_when_the_rulebook_is_not_checked_out(project, ag):
    (project / ".specify/standards/skills/layering/SKILL.md").unlink()
    out = show(ag, project).out
    assert ".specify/standards/skills/layering/SKILL.md  (MISSING in the checkout" in out, out
    assert "rulebook drift: not checked - the rulebook at" in out and "is not valid" in out
    shutil.move(str(project / ".specify/standards"), str(project / "standards-elsewhere"))
    r = show(ag, project)
    assert r.code == 0, r
    assert "in force      : 6 skills, 6 rules" in r.out                       # the lock alone says what is in force
    assert "ARCH-201   must   Layers depend downwards only" in r.out
    assert "rulebook drift: not checked - the rulebook is not checked out" in r.out
    assert "NOTE: the rulebook is not checked out at .specify/standards" in r.out


def test_show_in_a_project_with_no_standards_bound(tmp_path, ag):
    root = tmp_path / "fresh"
    write(root, CFG, (REPO / "config-template.yml").read_text(encoding="utf-8"))
    git(root, "init", "-q")
    r = show(ag, root)
    assert r.code == 0, r
    assert "in force      : none - no rulebook is bound (standards.rulebook)" in r.out, r
    assert "rulebook drift" not in r.out

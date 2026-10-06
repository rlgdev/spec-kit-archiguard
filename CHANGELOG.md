# Changelog

All notable changes to archiGuard are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- The bash and PowerShell launchers reject the Windows Store `python3` alias stub (it prints an install hint and
  exits 0) with the same marker check auditGuard and Guardians use; the header comment already promised it.
- A plug-in gate whose command is not a `.py` file (a shell script or binary) is probed with `<command> --version`
  directly, as docs/plugin-contract.md says; it was run through archiGuard's Python and every `version:` constraint
  on such a gate failed with exit 2.
- `docs/configuration.md` documents all options the engine reads: `A3.5.test_task_pattern`, `A3.5.fitness_tasks`,
  `A3.5.rules` and `scope.deferral_reference_pattern` were missing from the Options table, and the
  `edit_guard.after_signoff` default lists `gates/signoff.json`.

### Changed

- CI tests the scopeGuard integration and the end-to-end install against scopeGuard 0.4.0, the version the
  Guardians bundle pins (was 0.3.0).

### Added

- `tools/build.py --check` (CI): versions equal, the files the manifests name exist, the catalog `provides` counts
  match the manifests. The CI `lint` job runs it with pyflakes and shellcheck, like the siblings.
- Repository governance for corporate use: `CODEOWNERS`, `SECURITY.md` (private vulnerability reporting),
  `CONTRIBUTING.md` (the family's conventions and release steps), Dependabot for the GitHub Actions.
- The README points to the Guardians bundle and its getting-started guide.

## [0.1.0] - 2026-10-05

First release: the A-gates of the specification "archiGuard · A-gates specification - A0 · A3 · A4 ·
handover 4->5" (draft v0.2) as a Spec Kit extension, a preset and a workflow.

### Added

- **Gate runner** with the plug-in contract: gate manifests (checks with `target` and `repairable`), exit
  codes `0` pass / `1` repair / `2` cannot evaluate (fail-closed) / `3` escalated, a verdict file per check
  (`specs/<feature>/gates/<gate>/<check>.json`, with commit and pins) and a combined verdict per step.
- **One iteration budget per insertion point.** Step A after Setup, step B before the post-execution
  hooks of `/speckit.plan`, `/speckit.tasks` and `/speckit.implement`; step B re-runs every gate on each
  iteration, the runner owns the counter, a repeated set of findings escalates early, and a check no
  agent may repair escalates at once. The escalation note carries `TODO(agent)` items for the agent's
  problem report. Budgets are capped by the ceiling in `package-policy.yml` (6).
- **A0 domain guard**: A0.1 pin check, A0.2 home context, A0.3 entity ownership, A0.4 vocabulary
  (report mode by default), A0.5 relations in the plan.
- **A3 plan conformance**: A3.1 context loader (`gates/applicable-rules.json` and the contract the plan
  must meet), A3.3 check-plan (`## Architecture Conformance`, declared plan / contract checks, allowed
  not-applicable reasons, ADR-backed deviations), A3.4 constitution check, A3.5 task guard (requirement
  ids, tests first, a `[FITNESS]` task per rule with a code check), A3.6 analyze report, A3.7 cited
  decisions. A3.2 is the scope gate.
- **A4 fitness functions**: A4.1 entry pin check against the design sign-off (every design artefact and pin),
  A4.2 edit guard (Claude Code `PreToolUse` / `PostToolUse` through Spec Kit agent events; it also blocks the
  agent's shell from the commands reserved for people), A4.4 fitness runner (`layers`,
  `context_boundaries`, `forbid_import`, `forbid_text`, `require_text`, `require_file`, `contract_routes`,
  `command`; Java, JS/TS, Python, C#, Go, COBOL imports), A4.5 converge, A4.6 traceability (every code commit since
  the base branch names its task and a requirement id; changed test files carry the ids they verify).
- **Handover 4 -> 5**: entry checks H1-H6 and the test-handover manifest `gates/handover-4-5.json`;
  the deterministic test loop (`archiguard test`, JUnit reports, ids traced by test name or by the tags and
  comments in the test source); bounded workflow loops (`archiguard loop <name> -- <command>`).
- **Standards binding**: rulebook (architecture standards as skills), profiles and packs;
  `archiguard resolve` writes the committed `standards.lock.yml`; `validate-standards`; excluding a must
  rule needs a ledger waiver.
- **Decision ledger**: hash-chained JSON Lines (`archiguard ledger add | revoke | list | verify`); entries
  are proposed unless added as approved with an approver, and never rewritten; waivers need an owner, an
  approver and an expiry date.
- **Design sign-off** (`archiguard signoff`, `reopen`) on green evidence, on a committed design on the feature
  branch, pinning the hashes of every design artefact.
- **Pluggable gates**: scopeGuard (`>=0.3.0,<0.5`; with 0.4 `configure` recommends its `integration: embedded`, and
  `scope-config.yml` can trace use cases with `story_key: UC`) as the `scope` gate through an adapter, with an optional
  sha256 pin; any gate speaking the archiGuard protocol registered under `gates:`.
- `archiguard-config.yml`: `integration: inline | hooks`, `mode: enforce | report`, the pipeline per
  command, budgets, loop bounds, standards, domain map, ledger, sign-off evidence, tests, edit guard.
  Unknown settings are errors. Workstation overrides (`local-config.yml`, `ARCHIGUARD_*`) never reach CI.
- `configure`: applies the config to Spec Kit's hooks (archiGuard's and, when the scope gate is plugged,
  scopeGuard's), shows the settings in force and what is missing.
- `archiguard ci`: lock drift, ledger, every plugged gate once; JUnit and Markdown output; a GitHub Action
  and a Bitbucket Pipelines example.
- Compliance report (`gates/architecture-compliance.md`).
- Preset `archiguard-templates`: wraps `/speckit.plan`, `/speckit.tasks`, `/speckit.implement` and
  `/speckit.analyze`; appends Integration Points, Architecture Conformance, Scope Coverage and the Fitness
  phase to the templates.
- Workflow `archiguard-sdd`: plan -> tasks -> analyze -> design sign-off -> implement <-> converge ->
  handover 4 -> 5 -> test loop -> report -> pull request approval.
- Templates: domain map, handover record, a starting rulebook (`archiguard scaffold`).
- Example `examples/orders` with a missing plan rule, a layering and a context-boundary violation.

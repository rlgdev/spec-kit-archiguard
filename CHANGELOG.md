# Changelog

All notable changes to archiGuard are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **The scope stamp (scopeGuard 0.5).** The default pipeline runs `scope [stamp, inventory]` in step A of
  `/speckit.plan`: the first run stamps the scope of `spec.md` (`specs/<feature>/scopeguard-stamp.json`); a spec
  that moved since the stamp without a recorded reason stops the step for a person (exit `3`). The adapter maps
  scopeGuard's `"repairable": false` items and findings (a stamped ID removed from `spec.md`, one added after the
  stamp) to a non-repairable check, so step B escalates at once instead of spending the budget, and the escalation
  note names the decision (`scopeguard stamp --reason`, or restore `spec.md`). The `scope` manifest gains the `stamp`
  check (`target: spec`, `repairable: false`).
- `edit_guard.always_readonly` covers `specs/*/scopeguard-stamp.json`: the agent may neither re-stamp nor delete
  the stamp. The preset wraps name the stamp among the files never edited to make a gate pass.
- **Loop feedback to the domain master design** ([docs/loop-feedback.md](docs/loop-feedback.md), specification
  [docs/loop-feedback-specification.md](docs/loop-feedback-specification.md)): after coding, archiGuard compares the
  files changed on the branch with the domain map and writes `specs/<feature>/gates/loop-feedback.json` and `.md`. It
  covers seven kinds of item: `unmapped-code`, `cross-context`, `new-unit`, `topology`, `vocabulary`, `domain-change`
  and `map-gap`. Each item has a stable `LF-` id, an observation, a short suggestion for the next iteration, the
  people it is for, the target artefact and an impact hint. A topology answer (`existing`, `new`, `mixed`) says
  whether the feature extended an existing build unit or created a new one. **It is evidence, never a gate:** exit
  codes, verdicts, the iteration state and escalations are unchanged, and a test asserts this for every outcome.
- It is computed at the end of `/speckit.implement` step B (`pass` or `escalated`; the `FEEDBACK` block is printed
  after the result), recomputed by `archiguard handover` (manifest key `feedback`) and by `archiguard report --save`
  (section *Loop feedback to the domain master design (not blocking)* of the compliance report).
- `archiguard feedback [--save] [--json]` and the agent command `/speckit.archiguard.feedback`; `archiguard ci
  --feedback` prints it for the final commit without writing it.
- `feedback:` config section (`enabled`, `kinds`, `code`, `ignore`, `unit_markers`, `group_depth`, `repository`,
  `domain_rules`, `max_items`, `print_items`); `configure` shows it, and its `--json` carries `feedback`.
- Optional domain map keys `contexts.<c>.deployable` and `deployables: {<name>: {repo, root, kind}}`, read only by
  the loop feedback; no gate reads them. The `scaffold domain-map` template shows them.

### Changed

- `gates.scope.version` accepts scopeGuard `>=0.3.0,<0.6` (was `<0.5`); CI tests the integration and the
  end-to-end install against scopeGuard 0.5.0.
- The preset's `/speckit.implement` step B and the `implementgate` hook command tell the agent to copy the
  `FEEDBACK` summary into the Completion Report, and never to edit the feedback files or act on the items.
  `handover` and `report` say the same. The `archiguard-sdd` PR approval gate names the loop feedback.
- The A0.4 term check moved into `gates/a0.unknown_terms`, which the loop feedback reuses. The A0.4 result is
  unchanged.

### Fixed

- `ledger add` takes the `created` date from the same source as the expiry checks, so `ARCHIGUARD_TODAY` (workstation
  only, never CI) fixes both.

## [0.2.0] - 2026-11-08

`archiguard show` lists the setup in force and the rulebook skills the project is bound to, and archiGuard gets
along with the other extensions of a project: it names their hooks a stopped command skips, keeps the line endings
of Spec Kit's files, reads long hook descriptions without PyYAML, and no longer hides other catalogs.

### Added

- **`archiguard show`** and the agent command `/speckit.archiguard.show`: the setup in force, read-only. It prints
  what `configure` reports (integration, mode, the gates and budgets of each command, the hooks, the policy files)
  without writing `.specify/extensions.yml` - hooks that differ from the config are named with `configure` as the
  fix - and then the **skills**: every skill of the rulebook with a rule in the standards lock, with its `SKILL.md`,
  its description, its rules (level, targets, declared check or agent judgement, the profile, pack or `include`
  that selects it, the stack or context it is limited to, a stack not detected in the repository), the rules of a
  partly selected skill that are not in force, the skills the lock leaves out, the excluded rules with their
  waivers, and the drift between the lock and what `resolve` would write now. Without a lock it lists the
  rulebook's skills and marks the ones `resolve` would select. `--verbose` adds every rule's text and checks;
  `--json` gives the same as data. Exit `0`.
- When a gate stops a wrapped command (an escalation, or `cannot evaluate`; inline steps A and B, and step A through
  the hooks), the runner names the other extensions' enabled `after_<command>` hooks the stopped command skips
  (`NOT RUN: ...`, for example git's commit or agent-context's update; a setup error of such a run lists them too, and
  hooks with a `condition`, which the agent skips anyway, are left out), and the preset tells the agent to report them.
  In a new project the first `/speckit.plan` stops at step A, so these hooks no longer stop running without a word.
- The preset steps say what to do when the archiGuard extension is gone (the error names a file under
  `.specify/extensions/archiguard/`: `archiGuard not installed - skipped`, remove the preset) and continue the command;
  any other error, such as no `python` on PATH, still ends it.

### Changed

- The catalog install instructions add Spec Kit's `default` and `community` catalogs before the archiGuard catalog:
  a project catalog file replaces Spec Kit's own catalogs, and the earlier instructions hid every other extension of
  the project from `specify extension search`, `info` and `update`.
- Uninstall: why the preset goes first, and how to keep an `embedded` scopeGuard working.

### Fixed

- The built-in YAML reader (used without PyYAML) reads quoted scalars folded across lines, as PyYAML's dump writes
  long ones in Spec Kit's `.specify/extensions.yml` (`description: '... of the` / `planner'`); it stopped with
  "unterminated string" on every Spec Kit project with a long hook description.
- `configure` keeps the line endings of `.specify/extensions.yml`. Spec Kit writes it with CRLF on Windows; rewritten
  with LF, `git diff` showed every hook of every other extension removed and added again.

## [0.1.1] - 2026-10-07

### Added

- `tools/build.py --check` (CI): versions equal, the files the manifests name exist, the catalog `provides` counts
  match the manifests. The CI `lint` job runs it with pyflakes and shellcheck, like the siblings.
- Repository governance for corporate use: `CODEOWNERS`, `SECURITY.md` (private vulnerability reporting),
  `CONTRIBUTING.md` (the family's conventions and release steps), Dependabot for the GitHub Actions.
- The README points to the Guardians bundle and its getting-started guide.
- The preset declares `requires.extensions: archiguard >=0.1.0`: Spec Kit 1.0.4 or newer warns after `specify preset add`
  when the extension is missing (the wrapped steps do nothing without it); older Spec Kit versions ignore the key.

### Changed

- CI tests the scopeGuard integration and the end-to-end install against scopeGuard 0.4.1, the version the
  Guardians bundle pins (was 0.3.0).

### Fixed

- `scaffold domain-map`: the payments context of the template no longer pulls in a pack (`payments-compliance`) that
  the rulebook template does not define, so `resolve` no longer fails with "pack 'payments-compliance' is not defined
  in the rulebook" on the two scaffolded files.
- `tools/build.py` marks every archive entry as made on Unix (`create_system = 3`), so an archive built on Windows
  has the same sha256 as one built on Linux/macOS and keeps the launchers' executable bit.
- The bash and PowerShell launchers reject the Windows Store `python3` alias stub (it prints an install hint and
  exits 0) with the same marker check auditGuard and Guardians use; the header comment already promised it.
- The engine no longer writes `__pycache__` into `.specify/extensions/archiguard/` (the launcher sets
  `sys.dont_write_bytecode`): a `git add .specify` after a run committed the `.pyc` files.
- A plug-in gate whose command is not a `.py` file (a shell script or binary) is probed with `<command> --version`
  directly, as docs/plugin-contract.md says; it was run through archiGuard's Python and every `version:` constraint
  on such a gate failed with exit 2.
- `docs/configuration.md` documents all options the engine reads: `A3.5.test_task_pattern`, `A3.5.fitness_tasks`,
  `A3.5.rules` and `scope.deferral_reference_pattern` were missing from the Options table, and the
  `edit_guard.after_signoff` default lists `gates/signoff.json`.

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

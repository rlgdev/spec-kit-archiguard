# Configuration reference

archiGuard reads one committed file, `.specify/extensions/archiguard/archiguard-config.yml`
(scaffolded from [`config-template.yml`](../config-template.yml) by `specify extension add`).
Every setting has a default; the file only needs what differs. **An unknown setting is an error**, also
inside `options` and a gate registration, so a typo can never switch a gate or a pin off silently.

After changing `integration` or the `pipeline`, run `archiguard configure` (or
`/speckit.archiguard.configure`) to apply it to Spec Kit's hooks. Everything else takes effect on the
next run.

## Precedence

```text
built-in defaults  <-  archiguard-config.yml  <-  local-config.yml and ARCHIGUARD_* (workstation only)
```

- `package-policy.yml`, shipped inside the extension, holds the **ceiling** for every iteration budget and
  loop bound (`max_iterations_ceiling: 6`). It belongs to the team that publishes archiGuard; Spec Kit
  replaces it on every update, so a project cannot raise it.
- **Workstation overrides** in `.specify/extensions/archiguard/local-config.yml` may set only
  `integration`, `defaults.max_iterations`, `loops.*` and `pipeline.*.step_b.max_iterations`. Other keys
  there are ignored with a note. The environment variables `ARCHIGUARD_INTEGRATION` and
  `ARCHIGUARD_MAX_ITERATIONS` do the same for one shell; `ARCHIGUARD_TODAY=YYYY-MM-DD` fixes the date for
  expiry checks (for trying a waiver's expiry).
- **CI ignores every override.** When `CI` or `ARCHIGUARD_CI` is set, only the committed file counts.

## Settings

| Setting | Default | Meaning |
|---------|---------|---------|
| `version` | `1` | config format |
| `integration` | `inline` | `inline`: steps A and B run inside the wrapped commands (needs the archiguard-templates preset; without it archiGuard falls back to `hooks` and `configure` says so). `hooks`: the archiGuard hook commands run them |
| `mode` | `enforce` | `report` runs and records every gate but never blocks (shadow mode for a pilot). A pipeline entry may lower its mode to `report`, never raise it |
| `defaults.max_iterations` | `3` | repair iterations of a step B that sets no budget of its own |
| `standards.rulebook` | – | `<name>@<tag>` of the standards repository. Without it the rule-based checks exit `2` |
| `standards.path` | `.specify/standards` | the pinned checkout of the standards repository (a git submodule) |
| `standards.profile` | – | the central rule set for this stack (`profiles/<name>.yml`) |
| `standards.include` | `[]` | extra rule ids |
| `standards.exclude` | `[]` | `[{ rule: ARCH-118, waiver: ADR-0042 }]`; excluding a `must` rule needs an approved ledger entry that names it |
| `standards.lock` | `.specify/archiguard/standards.lock.yml` | written by `archiguard resolve`; commit it |
| `domain.map` | `.specify/standards/domain-map.yaml` | the domain map |
| `domain.pin` | – | the domain map version this repository is pinned to (A0.1) |
| `ledger.path` | `.specify/archiguard/ledger.jsonl` | the decision ledger |
| `feature.handover` | `handover.yml` | the handover record in each feature directory |
| `stack` | `auto` | `auto` detects the stack from the rulebook's markers; or a list such as `[java]` |
| `pipeline` | see below | the gates plugged into each command |
| `loops` | 3 each | bounds of the workflow loops: `handover_validator`, `implement_converge`, `handover_entry`, `test_loop` |
| `gates` | `scope` | registered plug-in gates (below); allowed keys: `extension`, `version`, `command`, `sha256`, `config`, `timeout`, `manifest`, `checks` (and the manifest fields `id`, `name`, `protocol`, `implementation`, `description` when the manifest is inline) |
| `signoff.require` | `[speckit.plan, speckit.tasks, A3.6]` | evidence that must be green before `archiguard signoff`: a command (all its gates, once) or a check |
| `tests.command` / `tests.build` | `auto` | test and build commands for H5, the test loop and the stack markers (`mvn`, `gradle`, `npm`, `pytest`, `dotnet`, `go`) |
| `tests.globs` | `auto` | test file globs for H4 and A4.6 |
| `tests.junit` | surefire, failsafe, gradle, `reports/**` | JUnit XML report globs |
| `tests.timeout` | `1800` | seconds per command |
| `git.base` | `main` | A4.6 reads commits and changed test files since this branch |
| `edit_guard.enabled` | `true` | the A4.2 hook |
| `edit_guard.always_readonly` | standards, `.specify/archiguard/**`, `.specify/extensions/archiguard/**`, `specs/*/gates/**/*.json` | never editable by an agent |
| `edit_guard.after_handover` | `spec.md`, `ba/**`, `handover.yml` | read-only once the feature has a handover record |
| `edit_guard.after_signoff` | `plan.md`, `research.md`, `data-model.md`, `quickstart.md`, `contracts/**` | read-only once the design is signed |
| `edit_guard.human_only` | `signoff`, `reopen`, `resolve`, `ledger add`, `ledger revoke` | archiGuard subcommands an agent may not run from its shell tool |
| `fitness.provider` | `graph-free` | `graph` is reserved for a code-graph provider in a later version |
| `options` | `{}` | per-check settings (below) |

## The pipeline

```yaml
pipeline:
  speckit.plan:                 # speckit.plan | speckit.tasks | speckit.implement (or plan / tasks / implement)
    step_a:                     # right after Setup: a list of gate entries
      - { gate: A0, run: [A0.1, A0.2, A0.3], repair: false }
    step_b:                     # before the post-execution hooks and the Completion Report
      max_iterations: 3         # the one budget of this insertion point
      gates:
        - { gate: A3, run: [A3.3, A3.7] }
```

A gate entry has `gate`, `run` (its checks, in order), and optionally:

- `repair`: omitted, each check follows its manifest (a check that no agent may repair, such as A0.1 or
  A4.1, escalates; the others loop). `false` turns repair off for the whole entry: a red check stops the
  command. `true` is refused when the entry contains a check that cannot be repaired.
- `mode`: `report` records the findings without blocking.

There is **no per-gate budget**. Step B re-runs every gate on each iteration, so the verdict that leaves
the step describes one artefact state. The runner escalates early when the same set of findings comes
back. Step A runs once; its red checks are part of the contract step B verifies, except the
non-repairable ones, which escalate at once.

The default pipeline:

| Command | Step A | Step B |
|---------|--------|--------|
| `speckit.plan` | A0 [A0.1 A0.2 A0.3] no repair · A3 [A3.1] · scope [inventory] | scope [plan] · A0 [A0.5] · A0 [A0.4] report · A3 [A3.3 A3.7] |
| `speckit.tasks` | – | scope [tasks] · A3 [A3.5] |
| `speckit.implement` | A4 [A4.1] no repair | scope [implement] · A4 [A4.4 A4.6] |

Checks that are not plugged anywhere by default: A3.4 (constitution check; add it to the plan's step B
if you want it enforced), A3.6 (run by `/speckit.analyze` and the sign-off), A4.5 (the converge loop of
the workflow), H1–H6 (`archiguard handover`). A3.2 is provided by the scope gate (`scope [plan]`), A4.2
by the edit guard, and A4.3 natively by `/speckit.implement`.

## Registered gates

```yaml
gates:
  scope:                                    # archiGuard's registration of the scopeGuard engine (default)
    extension: scopeguard                   # installed Spec Kit extension that provides the gate
    version: ">=0.3.0,<0.5"                 # archiGuard refuses another version (exit 2)
    command: scripts/python/scopeguard.py   # relative to .specify/extensions/<extension>/
    sha256: null                            # optional pin of that file (quoted 64-character hex)
    config: .specify/extensions/archiguard/scope-config.yml
  SEC:                                      # a third-party gate
    command: tools/secgate.py               # relative to the project root when no extension is named
    version: ">=1.0"
    timeout: 600
    manifest: tools/secgate-manifest.yml    # or the checks inline:
    # checks:
    #   SEC.1: { name: transport security, target: code, repairable: true }
```

See [plugin-contract.md](plugin-contract.md).

## Options

| Option | Default | Meaning |
|--------|---------|---------|
| `A0.4.strip_suffixes` | `[Request, Response, Dto, ...]` | suffixes removed before a name is compared with the glossary |
| `A0.5.section` | `Integration Points` | the plan section A0.5 reads |
| `A3.3.section` | `Architecture Conformance` | the plan section A3.3 reads |
| `A3.4.section` / `A3.4.article` | `Constitution Check` / – | the section, and a constitution article that must be named in it |
| `A3.5.require_ids` | `story` | `story`: tasks in user-story phases must carry requirement ids; `all`; `off` |
| `A3.5.require_marker` / `carries_marker` | `false` / `Carries:` | require the ids after an explicit marker |
| `A3.5.test_first_prefixes` | `[AC]` | ids whose test task must come before their implementation tasks |
| `A3.5.fitness_marker` | `[FITNESS]` | the marker of fitness-test tasks (A4.4 ticks them) |
| `A3.5.id_prefixes`, `A4.6.id_prefixes` | `UC SC AC BR D FR NFR` | the requirement id prefixes |
| `A3.6.report` | `gates/analyze-report.md` | where `/speckit.analyze` saves its report |
| `A3.7.id_pattern` | ADR, WVR, WAIVER, CLDD, SECD, DATD ids | the ids A3.7 treats as cited decisions |
| `A4.4.exclude` | `[]` | globs the fitness functions skip, e.g. `["**/generated/**"]` |
| `A4.5.phase_pattern` | `convergence` | the tasks phase A4.5 reads |
| `A4.6.commits` / `A4.6.tests` | `true` / `true` | the two halves of traceability |
| `H4.prefixes` | `[AC, BR]` | ids that need a test before the handover |
| `handover.checks` | `[H1 ... H6]` | the entry checks `archiguard handover` runs |
| `scope.require_deferral_reference` | `false` | a scope deferral must cite an RFI or a ledger entry |
| `ci.exclude_features` | `[]` | feature directory globs `archiguard ci` skips |

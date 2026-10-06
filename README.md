# archiGuard for Spec Kit

[![CI](https://github.com/rlgdev/spec-kit-archiguard/actions/workflows/ci.yml/badge.svg)](https://github.com/rlgdev/spec-kit-archiguard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> Part of the **Guardians** family for Spec Kit (scopeGuard · archiGuard · auditGuard). Install the three together with the [Guardians bundle](https://github.com/rlgdev/spec-kit-guardians) and start with its [getting-started guide](https://github.com/rlgdev/spec-kit-guardians/blob/main/docs/getting-started.md).

**Deterministic architecture gates for [GitHub Spec Kit](https://github.com/github/spec-kit).**
A feature stays inside its bounded context, the plan shows how it meets every architecture rule that
applies to it, and the code is released to testing only when the fitness functions are green.
The gates run as mandatory steps inside `/speckit.plan`, `/speckit.tasks` and `/speckit.implement`.
When a gate finds a gap, the agent repairs the artefact. If that still fails within the iteration
budget, the agent stops and hands you a problem report. Budgets, the gates that run, and the
standards a project must obey are set in one config file.

| Gate | What it decides | Where it runs |
|------|-----------------|---------------|
| **A0 domain guard** | the feature lives in one context of the agreed domain map and reaches other contexts only through relations the map allows | `/speckit.plan` |
| **A3 plan conformance** | the plan covers the spec, states how it meets every applicable rule, and cites only approved decisions | `/speckit.plan`, `/speckit.tasks`, `/speckit.analyze` |
| **A4 fitness functions** | the code stays inside the signed plan and the rulebook | `/speckit.implement`, every agent edit |
| **H handover 4 → 5** | the code may enter the deterministic test loop | after implement |
| **scope** (plug-in) | no requirement is dropped, on the [scopeGuard](https://github.com/rlgdev/spec-kit-scopeguard) engine | plan, tasks, implement |

Every gate is deterministic: plain parsing, set arithmetic, import graphs and regular expressions,
with no LLM in the loop. The agent repairs; the script decides.

## Why

An agent that turns a specification into a plan and code does not know your architecture. Spec Kit's
constitution check is a prompt: it can only report what the model happened to load and notice. The
result looks plausible and slips past review: a feature that writes another context's aggregate, a
layer that imports the one above it, a new integration with a relation nobody agreed, a plan that
silently skips the rule about secrets.

archiGuard makes these rules data. The domain map, the rulebook (architecture standards as skills)
and the decision ledger are pinned per repository. The gates check every artefact that leaves a
step against them, and record a verdict file with the hashes of what they checked. The design
authority signs the plan on that evidence, and CI re-runs every gate on the final commit.

## How it works

By default (`integration: inline`) the archiGuard preset wraps the three Spec Kit commands with
two mandatory steps:

| Command | Step A, right after Setup | Step B, before the post-execution hooks and the Completion Report |
|---------|---------------------------|-------------------------------------------------------------------|
| `/speckit.plan` | **A0.1–A0.3** domain guard (pin, home context, entity ownership); **A3.1** the applicable rules and the contract the plan must meet; the **scope** inventory | **scope** coverage spec → plan; **A0.5** relations in the plan; **A0.4** vocabulary (report mode); **A3.3** check-plan; **A3.7** cited decisions |
| `/speckit.tasks` | – | **scope** coverage plan → tasks; **A3.5** task guard (requirement ids, tests first, a fitness task per rule with a code check) |
| `/speckit.implement` | **A4.1** entry pin check against the design sign-off | **scope** carrying tasks done; **A4.4** fitness functions; **A4.6** traceability |

`/speckit.analyze` saves its report for **A3.6**, and the **A4.2** edit guard runs as a Claude Code
hook on every edit. With `integration: hooks` the same steps run as separate archiGuard commands
from Spec Kit's `before_*` / `after_*` hooks. Either way a gate runs exactly once: the path that is not
configured prints `skipped`.

Exit codes, for every command: `0` pass, `1` findings to repair, `2` cannot evaluate (fail-closed:
fix the setup, the agent does not repair), `3` escalated (needs a person).

### Repair, re-check, escalate

Step B is a bounded loop. **There is one iteration budget per step, and every gate of the step re-runs on
each iteration**, so the final verdict describes the artefact that leaves the step:

1. **Check.** The runner runs every gate plugged into the step and lists every finding under
   `RESOLVE`, with where it is, the fix and the rule or specification text to work from.
2. **Repair.** The agent fixes all of them: it designs the missing rule into the plan, moves an
   import to the published interface, adds the fitness task. It never edits the specification, the
   standards, the ledger, the config or a verdict file, and it never marks a rule `not applicable` or
   `deviation` without an allowed reason or an approved ADR.
3. **Re-check.** The runner counts the iterations itself; the agent never passes a number.
4. **Escalate** (exit `3`) when the budget is used up, when the same findings come back (the repairs
   conflict), or when a check that no agent may repair is red (a domain-map pin, a moved
   specification). The runner writes `gates/escalation-<command>-<step>.md`; the agent completes every
   `TODO(agent)` in it (what it tried, the blocker, the decision needed) and ends the command.

Step A starts a new run of the command and resets the counter. A pass, an escalation and an error are
terminal: the next step B starts with the full budget.

## Install

Requires Spec Kit (`specify-cli`) 1.0.1 or newer and Python 3.9+ (standard library only). If `python`
is not on `PATH`, the launchers use the Python that ships with `specify-cli`, or `uv`.

From your Spec Kit project root:

```bash
# 1. the extension: the gate runner, the checkers, the commands, hooks and the edit guard, the config files
specify extension add archiguard --from https://github.com/rlgdev/spec-kit-archiguard/releases/download/v0.1.0/archiguard.zip

# 2. the preset: makes the gates steps of /speckit.plan, /speckit.tasks and /speckit.implement,
#    saves the /speckit.analyze report, and adds the archiGuard sections to the plan and tasks templates
specify preset add --from https://github.com/rlgdev/spec-kit-archiguard/releases/download/v0.1.0/archiguard-preset.zip

# 3. the scope gate's engine (do NOT add the scopeguard-templates preset: archiGuard wraps the commands).
#    With scopeGuard 0.4+, set 'integration: embedded' in .specify/extensions/scopeguard/scopeguard-config.yml
specify extension add scopeguard --from https://github.com/rlgdev/spec-kit-scopeguard/releases/download/v0.4.0/scopeguard.zip

# 4. apply the config: archiGuard's and scopeGuard's hooks off (inline), the edit guard wired
bash .specify/extensions/archiguard/scripts/bash/archiguard.sh configure
#    Windows: .specify/extensions/archiguard/scripts/powershell/archiguard.ps1 configure
#    or, inside your agent: /speckit.archiguard.configure
```

Spec Kit asks you to confirm installs from a URL; answer `y`. Then bind the project to its standards
(below) and run `configure` again; it prints what is in force and what is still missing.

<details>
<summary>Install through a catalog (for teams)</summary>

```bash
specify extension catalog add https://raw.githubusercontent.com/rlgdev/spec-kit-archiguard/main/catalog/extensions.json --name archiguard --install-allowed
specify extension add archiguard

specify preset catalog add https://raw.githubusercontent.com/rlgdev/spec-kit-archiguard/main/catalog/presets.json --name archiguard --install-allowed
specify preset add archiguard-templates
```

For a corporate catalog, mirror both archives and the scopeGuard release into the internal catalog and
pin them by version and sha256 (`dist/SHA256SUMS` is attached to every release).

</details>

To upgrade: add `--force` to the extension command, run `specify preset remove archiguard-templates`
before adding the new preset, and run `configure` again. Your `archiguard-config.yml` is kept.

### Bind the project to its standards

```text
.specify/standards/             a pinned checkout (git submodule) of the standards repository
  rulebook.yml                  name, version (= tag), stack markers, allowed not-applicable reasons
  skills/<skill>/SKILL.md       the guidance the agent reads
  skills/<skill>/rules.yml      ARCH-### rules as data: level must|should, checks with target + kind
  profiles/<name>.yml           a named rule set per stack, owned centrally
  packs/<name>.yml              rules a domain-map context pulls in
  domain-map.yaml               the domain master design (contexts, relations, code mapping)
.specify/archiguard/
  standards.lock.yml            written by 'archiguard resolve' - commit it
  ledger.jsonl                  the decision ledger (ADRs and waivers), hash-chained
specs/<feature>/handover.yml    written by the formal handover: use cases, D artefacts, scope, pins
```

```yaml
# .specify/extensions/archiguard/archiguard-config.yml
standards:
  rulebook: acme-standards@v2026.10.1    # the standards repository, pinned by tag
  profile: java-service                  # the central rule set for this stack
  include: []                            # extra rules
  exclude: []                            # [{ rule: ARCH-118, waiver: ADR-0042 }] - a must rule needs a waiver
domain:
  pin: "1.4.0"                           # the domain map version this repository is pinned to
```

```bash
A=".specify/extensions/archiguard/scripts/bash/archiguard.sh"
bash $A scaffold domain-map         # starting files, if you have none yet: domain-map | rulebook | handover
bash $A validate-standards          # lint the rulebook
bash $A resolve                     # -> .specify/archiguard/standards.lock.yml (commit it)
bash $A rules --feature-dir specs/001-place-order    # what applies to a feature
```

The gates read the rules from the lock, never from the rulebook directly. CI re-resolves and fails on
drift, so a rule change reaches a project only through a reviewed lock change.
[docs/standards.md](docs/standards.md) describes the rulebook format and every check kind.

## What a failure looks like

From [`examples/orders`](examples/orders): the plan leaves out the layering rule ARCH-201, and the
code has two planted violations.

```text
$ archiguard run plan b
archiGuard 0.1.0 | speckit.plan · step B | feature: specs/001-place-order | iteration 0 (budget 3)
  [PASS] A0 · A0.5 relations in the plan
  [PASS] A0 · A0.4 vocabulary                   1 finding(s), report mode
  [FAIL] A3 · A3.3 check-plan                   1 blocking
  [PASS] A3 · A3.4 constitution check
  [PASS] A3 · A3.7 ledger check

RESULT: VIOLATION | 1 blocking, 1 advisory, 0 waived | evidence: specs/001-place-order/gates/plan-b.json

RESOLVE - fix every item, then run the same command again (the runner counts the iterations):
  1. [A3.3] ARCH-201 - ARCH-201 Layers depend downwards only (api -> application -> domain) is missing from 'Architecture Conformance'
       where: plan.md:22
       fix:   add: | ARCH-201 | Layers depend downwards only (api -> application -> domain) | satisfied | <where the plan meets it> | |  (read .specify/standards/skills/layering/SKILL.md first)

$ archiguard run implement b
  [FAIL] A4 · A4.4 fitness runner               2 blocking
  1. [A4.4] ARCH-201 - layer 'domain' must not depend on layer 'api' (import 'com.acme.orders.api.OrderController')
       where: src/main/java/com/acme/orders/domain/Order.java:3
  2. [A4.4] ARCH-301 - 'com.acme.payments.internal.PaymentGateway' is not part of the published interface of context 'payments'
       where: src/main/java/com/acme/orders/api/OrderController.java:4
       fix:   use what 'payments' publishes: com.acme.payments.api
```

Each check also writes a verdict file, `specs/<feature>/gates/<gate>/<check>.json`, with the
findings, the waivers, the commit and the pins (spec version and hash, domain map, rulebook tag,
lock hash) of the artefacts it checked.

## Evidence, sign-off and the edit guard

- **Design sign-off.** `archiguard signoff --by "<name>"` records the design authority's sign-off in
  `gates/signoff.json` with the hashes of every design artefact (spec, plan, research, data model,
  quickstart, contracts, handover record) and the pins. It is refused unless the evidence in
  `signoff.require` is green (default: the plan and tasks gates and A3.6), the design is committed on the
  feature branch, and no sign-off exists yet. `/speckit.implement` starts only on a signed design whose
  artefacts and pins have not moved (A4.1). A design change after the sign-off is
  `archiguard reopen --by <name> --reason <text>`, then a new sign-off.
- **Decision ledger.** `archiguard ledger add | revoke | list | verify`. An entry is `proposed` unless
  it is added with `--status approved --approver <name>`; waivers also need an expiry date. Entries are
  hash-chained and never rewritten: a tampered ledger stops A3.7 and CI. A `deviation` in the plan, an
  excluded must rule and a waived finding all need an approved, unexpired entry that names the rule.
  Protect `.specify/archiguard/` and `.specify/standards` with CODEOWNERS, so every ledger or lock change
  is reviewed by the lead architect.
- **Edit guard (A4.2).** A Claude Code `PreToolUse` / `PostToolUse` hook, wired through Spec Kit's
  agent events. It blocks agent edits of the standards, the lock, the ledger, the archiGuard config and
  engine, and the verdict files; of `spec.md` and the handover record once the handover exists; and of
  the signed design during Implement. After an edit it runs the rule checks with target `edit` on the
  edited file and hands the violations back to the agent. It also blocks the agent's shell from running
  the commands reserved for people: `signoff`, `reopen`, `resolve`, `ledger add`, `ledger revoke`. It is a
  convenience, never the guarantee: on any setup problem it lets the edit through, and the gates, the
  pull request review and CI decide.

## Handover 4 → 5 and the test loop

`archiguard handover` runs the entry checks H1 tasks complete, H2 converged, H3 fitness green,
H4 every in-scope acceptance criterion and business rule is carried by a test, H5 the build is green,
and H6 the pins are intact. It writes `gates/handover-4-5.json`, the test-handover manifest
(commit, hashes, pins, requirement → tests map, test command, verdicts, waivers). A red H1–H5 goes
back to implement; a moved pin (H6) needs a person.

`archiguard test` runs the test command, reads the JUnit reports, and traces every in-scope id to a
passing test case: by its name (`AC_002_payment_requested`), or by what its source declares directly above
the test (`@Tag("AC-002")`, an attribute, or a `// BR-042` comment). Workflow loops are bounded with `archiguard loop <name> -- <command>`: the counter lives in the
feature's `gates/.state/`, the first red run past `loops.<name>` exits `3` with an escalation note, and a
green run resets it.

## Commands

| Command | What it does |
|---------|--------------|
| `/speckit.archiguard.configure` | apply `archiguard-config.yml` to Spec Kit's hooks and show what is in force |
| `/speckit.archiguard.rules` | the rules that apply to the feature and the contract the plan must meet |
| `/speckit.archiguard.handover` | handover 4 → 5 |
| `/speckit.archiguard.report` | the architecture compliance report (`gates/architecture-compliance.md`) |
| `/speckit.archiguard.planentry` … `implementgate` | steps A and B as hook commands (`integration: hooks`) |
| `/speckit.archiguard.editguard` | the A4.2 hook (agent event, not for direct use) |

The command line (`bash .specify/extensions/archiguard/scripts/bash/archiguard.sh <command>`, or the
`.ps1` / `.py` launchers) adds `run`, `verify`, `check`, `resolve`, `validate-standards`, `signoff`,
`reopen`, `test`, `loop`, `ledger`, `ci`, `scaffold` and `version`. Every command takes
`--feature-dir`, `--json` and `--verbose`; `archiguard <command> --help` lists the rest.

## Configuration

`.specify/extensions/archiguard/archiguard-config.yml` is committed and changed through a pull
request. The full reference is in [docs/configuration.md](docs/configuration.md); the shape:

```yaml
version: 1
integration: inline          # inline (needs the preset) | hooks
mode: enforce                # enforce | report (shadow: record, never block); an entry may lower it
defaults:
  max_iterations: 3          # repair iterations per step; package-policy.yml caps every budget (6)
pipeline:                    # the gates plugged into each command, in order
  speckit.plan:
    step_a:
      - { gate: A0, run: [A0.1, A0.2, A0.3], repair: false }
      - { gate: A3, run: [A3.1] }
      - { gate: scope, run: [inventory] }
    step_b:
      max_iterations: 3      # the one budget of this insertion point
      gates:
        - { gate: scope, run: [plan] }
        - { gate: A0, run: [A0.5] }
        - { gate: A0, run: [A0.4], mode: report }
        - { gate: A3, run: [A3.3, A3.7] }
  # speckit.tasks, speckit.implement ...
loops: { handover_validator: 3, implement_converge: 3, handover_entry: 3, test_loop: 3 }
gates:                       # registered plug-in gates (archiGuard's own need no registration)
  scope: { extension: scopeguard, version: ">=0.3.0,<0.5", command: scripts/python/scopeguard.py }
```

- **Budgets.** A project may lower budgets, never exceed the ceiling the service team ships in
  `package-policy.yml`. A workstation may override `integration`, budgets and loop bounds in
  `local-config.yml` or with `ARCHIGUARD_INTEGRATION` / `ARCHIGUARD_MAX_ITERATIONS`; CI (`CI=true`)
  ignores every local override.
- **Unknown settings are errors**, so a typo never switches a gate off silently.
- **Pilot.** `mode: report` runs and records every gate without blocking; a single entry can be put in
  report mode (`A0.4` is, by default) but never raised above the global mode.

## Plugging in a gate

The runner knows a gate only through the plug-in contract: a manifest (its checks, each with a
`target` and whether an agent may repair it), a command line
(`<command> <check...> --feature-dir <dir> --iteration N --config <file> --json`), the exit codes above,
and verdict JSON on stdout. Register it under `gates:` and plug it into a step:

```yaml
gates:
  SEC:
    command: tools/secgate.py
    version: ">=1.0"
    sha256: "<optional pin of the command file>"
    checks:
      SEC.1: { name: transport security, target: code }
pipeline:
  speckit.implement:
    step_b:
      gates:
        - { gate: A4, run: [A4.4, A4.6] }
        - { gate: SEC, run: [SEC.1] }
```

The scope gate is plugged in the same way, through an adapter for scopeGuard's CLI. archiGuard
switches scopeGuard's own hooks off when the scope gate is in the pipeline, so scope is checked once.
[docs/plugin-contract.md](docs/plugin-contract.md) has the full contract.

## Hard stops with the workflow engine

[`workflows/archiguard-sdd`](workflows/archiguard-sdd/workflow.yml) runs plan → tasks → analyze →
design sign-off (a human gate) → implement ⇄ converge → handover 4 → 5 → test loop → compliance report
→ pull request approval (a human gate), with shell-step gates in between. Every loop is bounded by
`loops:` in the config.

```bash
specify workflow add archiguard-sdd --from https://raw.githubusercontent.com/rlgdev/spec-kit-archiguard/main/workflows/archiguard-sdd/workflow.yml
specify workflow run archiguard-sdd -i feature=specs/001-place-order -i design_authority="<name>"
# Windows: add -i archiguard="pwsh -File .specify/extensions/archiguard/scripts/powershell/archiguard.ps1"
```

## CI

The required check runs every plugged gate once on the final commit, re-resolves the standards lock,
and verifies the ledger. It never loops and never writes evidence.

```bash
python .specify/extensions/archiguard/scripts/python/archiguard.py ci --junit reports/archiguard.xml
```

[docs/ci.md](docs/ci.md) has a GitHub Actions job (or `uses: rlgdev/spec-kit-archiguard@v0.1.0`) and a
Bitbucket Pipelines step.

## What archiGuard does and does not prove

- It proves that every applicable rule is **accounted for** in the plan, that the code passes every
  declared check, that every deviation and waiver is an approved, unexpired decision, and that the
  artefacts the design authority signed are the ones that reach testing.
- It does **not** judge whether a design is good. A `satisfied` row whose reference is weak, or a rule
  with no declared check (shown as *agent judgement* in the report), still needs the design authority.
- The fitness functions are static (imports, file patterns, contracts). Runtime rules (`target: runtime`)
  belong to the architecture assessor and are not run here.
- The repair is done by the agent, following the gate commands. The runner verifies the result after
  every iteration and owns the counter, so the loop cannot run forever or end in a claimed success.

## Uninstall

```bash
specify preset remove archiguard-templates
specify extension remove archiguard
```

Run `configure` of scopeGuard afterwards if you keep it, to turn its own hooks back on.

## Development

```bash
python -m pytest -q          # engine tests (set SCOPEGUARD_SRC to a scopeGuard checkout for the integration test)
python tools/build.py --check  # versions, manifests and catalogs agree (CI)
python tools/build.py        # dist/archiguard.zip, dist/archiguard-preset.zip, dist/archiguard-sdd.yml, dist/SHA256SUMS
```

To release, bump the version in `extension.yml`, `preset/preset.yml`, the workflow,
`scripts/python/archiguard_core/__init__.py` and `catalog/*.json`, add a CHANGELOG entry, then push a
`vX.Y.Z` tag. The release workflow runs the tests, builds the archives and attaches them to the release.

[CONTRIBUTING.md](CONTRIBUTING.md) has the conventions and the release steps of the family.

## License

[MIT](LICENSE)

# Loop feedback to the domain master design — Specification v1.0

> **Status:** implemented in archiGuard 0.2.0, auditGuard 0.3.0 and Guardians 0.2.0, with the proposed defaults of
> section 10. Where the body below differs, the amendment wins. User documentation: [loop-feedback.md](loop-feedback.md).

| | |
|---|---|
| Feature | **Loop feedback**: after coding, the evidence of what the feature did that the domain master design (DMD, loop step 0) does not describe, with a short suggestion per item for the next iteration |
| Repositories | `rlgdev/spec-kit-archiguard` (producer) · `rlgdev/spec-kit-auditguard` (recorder, triage, backlog hand-over) · `rlgdev/spec-kit-guardians` (pins, alignment check) |
| Host | GitHub Spec Kit ≥ 1.0.1 · Python ≥ 3.9, standard library only · git |
| Principle | **Evidence, not a gate.** The feedback never blocks, never changes an exit code, a verdict, an iteration count or an escalation |
| Traceability | User stories `US1–US7`, functional requirements `FR-###`, non-functional `NFR-###`, success criteria `SC-###` |

## Amendments in the implementation

| # | Requirement | Amendment | Why |
|---|-------------|-----------|-----|
| A1 | FR-106, D3 | `domain-change` has a fourth source: (d) every waiver of a domain rule that the fitness runner applied for this feature (`gates/A4/A4.4.json` → `waived`) and that no other item carries raises `waiver:<id>` (impact high, with its expiry). For this the feedback also reads the feature's A4.4 verdict. | A waived import in a file the branch did not change is invisible to source (a), but the feature still relies on the waiver. This is debt with a date. |
| A2 | FR-133, Appendix A | Items sort by impact, then by kind in the order of §3.2, so `unmapped-code` comes before `new-unit`. Appendix A shows the order and the items the implementation actually gives: ARCH-301's waiver is `waiver:WVR-0001`, and the data model of `examples/orders` has `Shipment` (`LF-831ba84c`), not `Checkout`. | The draft appendix was written before the code. |
| A3 | FR-134 | `resolved[]` accumulates. An id an earlier run of the feature raised stays listed (with `resolved_at` and `resolved_by`) until it is raised again, up to 50 entries. | With write-if-changed (FR-135), a list of only the last run's resolutions would rewrite the file once more for nothing. |
| A4 | FR-204 | `report` without `--save` states when and at which commit the feedback was computed. It does not compare that commit with HEAD. | Write-if-changed keeps the commit of the last content change, so a HEAD comparison would flag every later commit. |
| A5 | FR-205, §7.1 | Added the agent command `/speckit.archiguard.feedback`. `archiguard feedback` prints every item, not only `print_items`. Not implemented (P2): FR-206's `$GITHUB_STEP_SUMMARY`, FR-209 `--note` and FR-210 `--all`. | — |
| A6 | FR-103, FR-104 | No `new-unit` item is raised when *any* deployable of the map declares the unit root, not only one of the home context. Topology (c) also covers a declared new unit that holds home-context code but is not one of the home context's deployables. | The DMD already knows the unit; what remains is whether the home context belongs in it. |
| A7 | FR-202, §5.3 | The agent copies the block's first line, its `topology:` line and its last line (`details:` or `... more:`). In the block, each suggestion is cut to fit 200 characters. | A short, stable Completion Report; the file holds the full text. |
| A8 | FR-105 | The A0.4 term logic moved into `gates/a0.unknown_terms`, which A0.4 and the feedback share. The A0.4 results are unchanged. | One definition of a term outside the glossary. |
| A9 | FR-402, §5.4 (auditGuard) | Feedback events refer to the snapshot of `loop-feedback.json` through `file_fingerprint`, carried by the `report.saved` event of that file version. `occurrences` is stored as a count. | One snapshot per file version, not one per item. |
| A10 | FR-504, FR-505 (auditGuard) | The loop-feedback sections of `trail.md`, `sprint.md` and the feature pages appear once any feedback is recorded. Also added: the agent command `/speckit.auditguard.backlog`, `feedback_recorded` in `configure --json`, and a `feedback` filter and the pending triage in the viewer. `--ref` is refused on any subject other than `feedback:`. | Projects without archiGuard 0.2 see unchanged views. |
| A11 | §8.1 (auditGuard example) | `tools/make-example.py` sets `ARCHIGUARD_TODAY` to the story's clock. For that, `archiguard ledger add` now takes `created` from the same date source as the expiry checks. The example's triage accepts `LF-2ba4e67d` (with `--ref ARCH-77`), defers `LF-831ba84c`, and ships `audit/backlog-S-2026-22.csv`. | A deterministic example: the waiver in the story would otherwise expire on the real clock. |

---

## 0. Summary and decisions

### 0.1 What the feature delivers

The A0 and A4 gates treat the domain map as a contract: a feature must fit the map, or it stops. They do not
report what the map *missed*: code that no context maps, a new build unit that may be a new microservice,
a context whose deployment unit nobody declared, a dependency that only passes because of a waiver, or a term
missing from the glossary. Today that knowledge is lost when the feature ends. It should flow back to the DMD.

After coding, archiGuard compares what the feature did with the DMD. It writes **loop feedback**, a list of
items. Each item has an observation, the person it is for, the artefact the fix belongs in, an impact hint,
and a **short suggestion** for the next iteration. A **topology** section answers the question the gates cannot
answer: *did this feature extend an existing unit, or create a new one?*

The feedback is part of the final feedback of the loop: the `/speckit.implement` Completion Report, the test
handover manifest, and the architecture compliance report the pull request is approved on. auditGuard records
every item as evidence. A person triages each item (accept, reject or defer), and the accepted items are handed
over as **backlog candidates** at sprint close. Nothing in this flow can stop a command.

### 0.2 Decisions taken

| # | Decision | Taken |
|---|----------|-------|
| D1 | Not a gate | The feedback is not in `pipeline:`, has no verdict status, never changes an exit code, a step's `RESULT`, the iteration counter or an escalation, and never creates a `RESOLVE` item. If it cannot be computed, the file says so and the runner prints one line. Nothing else changes. |
| D2 | Deterministic | It uses the same means as the gates: git, globs, the domain map, the handover record, the lock, the ledger and the plan. There is no LLM in it. Each suggestion is a template filled with data. |
| D3 | Read-only analyses only | The feedback never runs a gate check, a build or a test, and never writes a verdict. It reuses archiGuard's read-only analyses: path→context mapping, import extraction, entity-name extraction, the ledger and the plan parsers. |
| D4 | Producer: archiGuard | archiGuard owns the domain map, the git base and the code analysis. The code is a new module, `archiguard_core/feedback.py`. The output sits with the other evidence in `specs/<feature>/gates/`. |
| D5 | When it runs | At the end of coding (implement step B, terminal outcome `pass` or `escalated`), again at handover 4 → 5, and again with the compliance report. The run on the final commit is **the final feedback** (§6.1). |
| D6 | Recorder and triage: auditGuard | auditGuard records the items as events (`feedback.raised` / `updated` / `resolved`). A person triages them with `auditguard decide feedback:<id>`. `auditguard backlog` exports backlog candidates. |
| D7 | Stable identity | An item's id is derived from its kind and subject, never from the feature. So the same gap raised by two features, or by two runs, is one item and one backlog candidate. |
| D8 | Topology is optional data in the map | Two new optional keys, `contexts.<c>.deployable` and `deployables:`. Only the feedback reads them; A0, A3 and A4 ignore them. Existing maps stay valid. Without the keys, the feedback still reports units and says the topology is undeclared. |
| D9 | The agent only reports | The agent copies the printed summary into its Completion Report. It never edits the feedback, and it never acts on it in the current command, because the items are for the DMD and the next iteration. |
| D10 | Name | "Loop feedback": feedback from implementation back to loop step 0. Files: `gates/loop-feedback.json` (authoritative) and `gates/loop-feedback.md` (view). Item ids: `LF-xxxxxxxx`. |

---

## 1. Scope, actors, glossary

**In scope.** archiGuard: the computation, its two files, the runner, handover and report integration, a
`feedback` command, the `feedback:` config section, the optional domain-map keys, preset and workflow text,
docs, tests and an example. auditGuard: the collector, three event kinds, the `feedback:` decision subject,
the trail, sprint and feature views, the `backlog` command, the seal counts, an opt-in completeness rule,
docs and tests. Guardians: the bundle pins, one `verify` check and one getting-started section.

**Out of scope.** Changing the domain map automatically. Any gate on the feedback. Creating issues in a tracker
directly: P1 exports files that trackers import (§5.6). Feedback to the rulebook (rules left to agent judgement)
and to the specification (scope deferrals): both can be added later as new kinds through the same item contract.
Runtime topology discovery (parsing Kubernetes or Helm manifests beyond recognising them as unit markers).

**Actors.**
- *Lead architect*: owns the DMD, triages topology and domain-change items, and releases the next map version.
- *Domain owner*: the `owner` of a context in the map; owns its glossary and entities.
- *BA*: names entities in the data model.
- *Tech lead / design authority*: owns the refactoring and the waivers that are due.
- *Product owner*: takes the accepted items into the backlog.
- *Agent*: runs the commands and reports the summary; never triages.
- *CI*: prints the feedback of the final commit.

**Glossary.**
- *Item*: one observation with a suggestion.
- *Kind*: the type of an item (§3.2).
- *Subject*: what an item is about, as a feature-independent key (`orders->payments`).
- *Occurrences*: the files or lines behind an item.
- *Unit*: a build or deployment unit, recognised by a *unit marker* (`pom.xml`, `package.json`, `Dockerfile`, ...)
  in its *unit root* directory. Whether a unit is a microservice is what the DMD declares (`deployables.<name>.kind`).
- *Deployable*: a unit the DMD declares for a context.
- *Triage*: a person's decision on an item.
- *Backlog candidate*: an item that is not rejected and not resolved, exported for the tracker.

---

## 2. User stories

Priorities: P1 ships in archiGuard 0.2.0 / auditGuard 0.3.0, P2 in 0.2.x / 0.3.x.

### US1: See after coding what the DMD does not know (P1)
As a lead architect, I want every feature to report, when coding is done, the code, units, relations and terms
the domain map does not describe, each with a short suggestion, so that the next map version learns from the
implementation.

*Acceptance.* **Given** `examples/orders` on a branch that adds `services/notifications/pom.xml` and two Java
files under it, **when** `archiguard run implement b` passes, **then** `gates/loop-feedback.json` contains a
`new-unit` item for `services/notifications` and an `unmapped-code` item for its files, each with a suggestion
and the lead architect as addressee. The runner prints the `FEEDBACK` block after `RESULT`. The exit code is `0`.

### US2: Answer "new service or existing one?" (P1)
As a developer or architect, I want the feedback to say which units the feature changed, which of them are new
on the branch, and what the DMD declares for them, so that a new microservice never appears unnoticed.

*Acceptance.* **Given** the branch of US1, **when** the feedback is computed, **then** the topology answer is
`mixed`: the existing unit `.` holds `orders` and `payments` code, and the new unit `services/notifications`
holds code that no context maps. Both units are shown with their marker and whether a deployable is declared.

### US3: Never be blocked by it (P1)
As a developer, I want the feedback to have no effect on the gates.

*Acceptance.* **Given** any project, **when** `run implement b`, `handover` and `report --save` run with
`feedback.enabled: true` and then with `false`, **then** the exit codes, the verdict files, the combined step files,
the iteration state and the escalation notes are byte-identical, apart from the feedback's own files and the
manifest's `feedback` key. **Given** a missing domain map, **then** the feedback records `status: not-evaluated`
with the reason, and the step outcome is unchanged.

### US4: Find the feedback in the final reports (P1)
As a tech lead, I want the feedback in the Completion Report, in the handover manifest and in the compliance
report the PR is approved on, so that it is in front of me when the feature is done.

*Acceptance.* **Given** the US1 branch, **when** `archiguard-sdd` runs to its `report` step, **then** the
Completion Report has the `Loop feedback (not blocking)` lines, `handover-4-5.json` has `feedback.items: 7`, and
`architecture-compliance.md` has the loop feedback section with the topology answer. `Overall` is the same as
without the feature.

### US5: Keep it as evidence (P1)
As an auditor, I want every item recorded in the feature's chain with a snapshot of the file, so that I can
see what the implementation fed back, when, and what happened to it.

*Acceptance.* **Given** the US1 branch with auditGuard installed, **when** the `after_implement` hook runs,
**then** the feature's chain has seven `feedback.raised` events and one `report.saved` (`loop-feedback.json`) with
its snapshot. A second hook with no change records nothing.

### US6: Turn it into backlog items (P1)
As a lead architect and product owner, I want to accept, reject or defer each item (with the tracker key once
it exists), and to export the accepted items in a format our tracker imports, merged across features.

*Acceptance.* **Given** `LF-2a2a5a3d` was raised by two features, **when** a person runs
`auditguard decide feedback:LF-2a2a5a3d accept --by "Lead architect" --reason "DMD 1.5.0"`, **then**
`auditguard backlog --status accepted --format csv` prints one row for it, listing both features. A later
`decide ... accept --ref ARCH-77` sets its status to `in-backlog`.

### US7: Tell new items from known ones (P2)
As a lead architect, I want an item that was already accepted or rejected in an earlier sprint to be marked
`known`, so that the next feature does not ask for the same triage again.

---

## 3. Functional requirements

### 3.1 Principles and inputs (FR-00x)

- **FR-001** The feedback SHALL NOT change an exit code, a verdict file, a combined step file
  (`gates/<command>-<step>.json`), the iteration state (`gates/.state/`), an escalation note, or the `RESULT` line
  of any archiGuard command. It SHALL NOT appear under `RESOLVE` and SHALL NOT be counted in a step's blocking,
  advisory or waived totals.
- **FR-002** The computation SHALL read only:
  - the domain map (`domain.map`) and the handover record (for the home context);
  - git: the files changed on the branch against `git.base`, plus uncommitted and untracked files (the
    `a4.changed_files` logic), and the files *added* on the branch (`git diff --name-status --diff-filter=A
    <base>...HEAD`, plus untracked files);
  - the standards lock, the decision ledger, and `plan.md` (`## Architecture Conformance`, with the A3.3 parser);
  - `data-model.md` and `contracts/` (with the A0.4 entity-name extraction);
  - the previous `gates/loop-feedback.json`.

  It SHALL write only `gates/loop-feedback.json` and `gates/loop-feedback.md`.
- **FR-003** *Code files* are the changed files whose extension is a source extension known to archiGuard's
  code analysis (`codeanalysis.LANGUAGES`), or that match `feedback.code` when that is set. Files matching
  `feedback.ignore` and `options.A4.4.exclude` are never code. Test code is code.
- **FR-004** When an input is missing, the kinds that need it are skipped and listed in `skipped[]`, each with its
  reason, and `status` is `partial`. With no domain map or no valid home context, `status` is `not-evaluated`.
  An exception inside the computation is caught, recorded as `status: not-evaluated` with the message, and printed
  as one line. It SHALL NOT raise exit `2`.
- **FR-005** With `feedback.enabled: false` nothing is computed, no file is written and nothing is printed. The
  compliance report says `Loop feedback is switched off (feedback.enabled).`

### 3.2 Item kinds (FR-1xx)

Each kind is listed with its subject key, impact hint, addressee and suggestion template. Templates are filled
with data; `<...>` are placeholders. A kind can be switched off through `feedback.kinds`.

- **FR-101 `unmapped-code`.** A code file that `DomainMap.context_of_path` maps to no context.
  - Grouping: files under a *new* unit (FR-103) form one group whose path is the unit root. Any other file is
    grouped by the first *D* segments of its directory (the whole directory when it is shallower). *D* is
    `feedback.group_depth`, or, with `auto`, the most common number of literal leading segments in the map's
    `code:` globs (`src/main/java/com/acme/orders/**` has 6; on a tie the smaller wins; with no globs, 2).
  - Subject: the group path. Impact: **high** (A4.4 cannot check the boundaries of unmapped code).
    For: lead architect.
  - Suggestion: `Map <group>/** to a context in the next domain map version (contexts.<home>.code if it belongs to <home>), or declare a new context for it.`
  - When no context in the map declares `code:` at all, this kind is replaced by the single `map-gap` item
    `map:no-code-paths`, which avoids one item per directory.
- **FR-102 `cross-context`.** Code files mapped to a context *other* than the home context. There is one item per
  other context.
  - Subject: `<home>-><other>`. Impact: **medium** when the map has a relation `<home> -> <other>`, **high** when
    it has none. For: the other context's owner and the lead architect.
  - Suggestion with a relation: `<n> file(s) of <other> changed in a <home> feature under the <type> relation: plan the change as a <other> backlog item owned by <owner>, or record a partnership / shared kernel if the two contexts evolve together.`
  - Suggestion without a relation: `The map has no relation <home> -> <other>: propose one in the next domain map version, or split the change into a <other> feature.`
- **FR-103 `new-unit`.** A unit marker (a file name that matches `feedback.unit_markers`, `fnmatch`) added on the
  branch makes its directory a *new unit root*.
  - Subject: `<repository>:<unit root>`. Impact: **high**. For: lead architect.
  - Suggestion: `Decide in the domain master design whether <unit root> is a new deployable (deployables.<name> with contexts.<context>.deployable), or move its code into the existing unit <nearest existing unit>.`
  - A new unit that is already declared as a deployable of the home context (`repo` = this repository, `root` =
    the unit root) raises no item. The topology shows it as `new, declared`.
- **FR-104 `topology`.** Raised for the home context only, and only when the feature changed code:
  - (a) subject `<home>:undeclared`, impact **medium**, when the home context declares no `deployable`.
    Suggestion: `Declare the deployment unit(s) of <home> in the domain map (contexts.<home>.deployable, deployables.<name>), so the next feature can tell a new service from an existing one.`
  - (b) subject `<home>:<repository>`, impact **medium**, when every deployable of the home context lives in
    another repository. Suggestion: `<home> code changed in <repository>, but the domain master design deploys <home> from <repos>: declare this repository as a deployable of <home>, or move the change there.`
  - (c) subject `<home>:<repository>:<unit root>`, impact **medium**, when the home context's code changed in an
    *existing* unit that is not one of its declared deployables. Suggestion: `Add <unit root> as a deployable of <home>, or move the code into <declared root>.`
  - (d) Only when the map has a `deployables:` section: subject `repo:<repository>`, impact **medium**, when no
    deployable names this repository. Suggestion: `This repository is not a deployable in the domain master design (a new service?): declare it, or name the deployable it belongs to.`
  - A unit that already has a `new-unit` item never also raises (c).
- **FR-105 `vocabulary`.** An entity or contract name (the A0.4 extraction, honouring the
  `options.A0.4.strip_suffixes` option) that is not in `DomainMap.vocabulary(home)`.
  - Subject: `<home>:<normalised term>`. Impact: **low**. For: the home context's domain owner and the BA.
  - Suggestion: `Add <term> to the glossary of <home> (or as a synonym of an existing term) in the next domain map version, or rename it in the data model and contracts.`
- **FR-106 `domain-change`.** Something the feature needed that the map does not allow. There are three sources:
  - (a) **Imports.** For each import in a changed code file of context *s* that resolves (by path or by
    `context_of_module`) to context *d* ≠ *s*. The *module prefix* is the imported name without its last segment
    (the package or namespace), or the directory of the resolved file for a path import.
    - when `allows(s, d)` is none: subject `relation:<s>-><d>`, with suggestion `Propose the relation <s> -> <d> (and its type) in the next domain map version, or remove the dependency.`
    - when it is allowed but `is_published` is false: subject `published:<d>:<module prefix>`, with suggestion `Publish <module> in contexts.<d>.published, or use what <d> publishes (<published>).`
    - Occurrences are `file:line import`.
  - (b) **Deviations.** A `deviation` row in `## Architecture Conformance` for a *domain rule* (see the note at the
    end of this requirement). Subject `rule:<rule id>:<home>`, with suggestion `<rule id> is met by deviation (<ADR>): decide in the domain master design whether the map or the rule changes, so the deviation can end.`
  - (c) **Ownership.** A D artefact of the handover whose entity no context owns, or that is owned by a context
    with no relation to the home context. This is the A0.3 logic recomputed; under `mode: enforce` A0.3 has already
    stopped such a feature, so the source matters in `mode: report`. Subject `entity:<Entity>`, with suggestion
    `Give <Entity> an owning context in the next domain map version, or reach it through an allowed relation.`
  - Impact: **high** when an approved, unexpired ledger waiver for a domain rule is in force for the item (the
    waiver id and expiry go into the suggestion: `waived by <id> until <date>: ... before then`), otherwise
    **medium**. For: lead architect, plus the tech lead when a waiver is in force.
  - *Domain rules* are `feedback.domain_rules`, or, with `auto`, the lock's rules that have a
    `context_boundaries` check.
- **FR-107 `map-gap`.** Gaps in the map that limit what the gates can check, limited to the home context, the
  contexts related to it, and the contexts of the changed code:
  - `<context>:no-code`: the context declares no `code:` paths, so A4.4 cannot attribute its files. Suggestion: `Declare the code paths of <context> (contexts.<context>.code) so the context-boundary fitness function covers it.`
  - `<context>:no-owner`: the context has no `owner`. Suggestion: `Name the domain owner of <context>, so its feedback has an addressee.`
  - `deployable:<name>:undefined`: a `deployable` that has no entry in `deployables:` (when that section exists). Suggestion: `Add <name> to deployables: with its repo and root.`
  - `map:no-code-paths`: see FR-101.

  Impact: **low**, and **medium** for `map:no-code-paths`. For: lead architect.
- **FR-108** Every item SHALL carry `target`: where the fix belongs, for example `domain-map: contexts.orders.code`,
  `domain-map: relations`, `domain-map: deployables`, `code` (refactoring) or `ledger: WVR-0001`.

### 3.3 Topology (FR-12x)

- **FR-121** The *unit* of a changed code file is the nearest directory at or above it, up to the repository
  root, that contains a file matching `feedback.unit_markers` at HEAD. A file with no such ancestor belongs to the
  unit `(none)`. A unit is *new* when every marker in its root was added on the branch. Without a base branch,
  `new` is `null` (unknown).
- **FR-122** The repository's name is `feedback.repository`. With `auto`, it is the last path segment of the
  `origin` remote URL without `.git`, or else the name of the root folder. It is read from the local git config
  only.
- **FR-123** For each unit the topology lists `root`, `marker`, `new`, the contexts of its changed code files
  (`(unmapped)` for files no context maps), the number of changed code files, and `declared`: the deployables
  whose `repo` is this repository and whose `root` is the unit root.
- **FR-124** The feature-level `answer` is:
  - `existing`: every changed code file is in an existing unit;
  - `new`: every one is in a new unit;
  - `mixed`: both;
  - `unknown`: the base is missing, or no file is in a unit;
  - `none`: no code changed.

  It is printed as one sentence (§5.3) and shown first in the Markdown view.
- **FR-125** The domain map MAY declare:
  - `contexts.<c>.deployable`: one name or a list;
  - `deployables.<name>`: `{repo, root, kind}`, where `root` defaults to `.`, `repo` to this repository, and
    `kind` is one of `service | library | job | frontend | other`.

  `DomainMap` SHALL parse both, but no gate SHALL read them, and their absence or content SHALL NOT change any
  A0, A3 or A4 result.

### 3.4 Items, identity, files (FR-13x)

- **FR-131** Item id: `LF-` followed by the first 8 hex digits of `sha256("<kind>\n<subject>")`, extended to 12
  digits on a collision within one file. The subject never contains the feature.
- **FR-132** Item fields (§5.1): `id`, `kind`, `subject`, `title` (≤ 100 characters), `observation` (one sentence),
  `suggestion` (one or two sentences, imperative, for the next iteration), `for[]` (roles, with names from the
  map's `owner` where known), `target`, `impact` (`high | medium | low`), `waiver` (`{id, expires}` or null),
  `occurrences` (`{count, items[≤ 25]}`), `evidence[]` (paths, with lines where there are any) and `first_seen`
  (carried over from the previous file).
- **FR-133** Items are sorted by impact (high first), then by kind in the order of §3.2, then by subject. At most
  `feedback.max_items` are written; the rest are counted in `truncated`.
- **FR-134** `resolved[]` lists the ids of the previous file that are no longer raised, with `resolved_at`. This
  happens only when both runs are `evaluated` or `partial` and the item's kind was not skipped.
- **FR-135** Write-if-changed: the files are rewritten only when anything other than `computed_at`, `computed_by`
  and `commit` changed, so an unchanged feedback leaves no new evidence.
- **FR-136** `loop-feedback.json` SHALL NOT have a `step` key. archiGuard's report and auditGuard's collector
  recognise step verdicts by that key, and this file must never be read as one. The existing edit-guard pattern
  `specs/*/gates/**/*.json` protects it from agent edits. `loop-feedback.md` is a view, regenerated with the JSON.

### 3.5 When it is computed and where it is shown: archiGuard (FR-2xx)

- **FR-201 End of coding.** When `run implement b` (inline or `--via hooks`) ends with a terminal status of
  `pass` or `escalated`, the runner computes the feedback in the same process (`computed_by: implement-b`). It
  then prints the `FEEDBACK` block (§5.3) after the `RESULT` line, or `FEEDBACK: not evaluated - <reason>`. It
  does not compute the feedback on `violation` (an iteration is in progress) or on `error`.
- **FR-202 Completion Report.** The preset's `speckit.implement.md` step B SHALL tell the agent, for exit `0` and
  exit `3`:
  - copy the `FEEDBACK` summary line and the topology line as printed, under `Loop feedback (not blocking)`;
  - never edit the feedback files;
  - **do not act on the items in this command**: they are for the DMD and the next iteration.

  The same text goes into the `implementgate` hook command.
- **FR-203 Handover 4 → 5.** `archiguard handover` recomputes the feedback (`computed_by: handover-4-5`), because
  code may change in the converge and handover loops. It adds `feedback: {file, sha256, status, answer, items,
  by_impact}` to `handover-4-5.json`. The entry checks and the handover status are unchanged.
- **FR-204 Compliance report.** `archiguard report --save` recomputes the feedback (`computed_by: report`).
  `report` without `--save` reads the existing file and, when its commit differs from HEAD, adds `computed at
  <commit>, HEAD is <commit>`. The report adds a section after `## Test loop`:
  `## Loop feedback to the domain master design (not blocking)`, holding the topology answer and the item table
  (§5.2). `Overall` is never affected.
- **FR-205 Command.** `archiguard feedback [--feature-dir D] [--save] [--json]` computes and prints the feedback;
  `--save` writes the files (`computed_by: cli`). Agents may run it; it is not human-only.
- **FR-206 CI.** `archiguard ci --feedback` prints the feedback of the final commit after the gate results. It
  writes nothing and never affects the exit code. (P2: it also appends the Markdown to `$GITHUB_STEP_SUMMARY`
  when that is set.)
- **FR-207 Workflow.** In `archiguard-sdd`, the `report` step already runs `report --save`. The `pr-approval`
  message adds: `The loop feedback (gates/loop-feedback.md) goes to the lead architect; it does not block this approval.`
- **FR-208 Configure.** `archiguard configure` prints
  `loop feedback : on (7 kinds) · after implement, handover, report` or `loop feedback : off`.
- **FR-209 (P2) Rationale.** `archiguard feedback --note <id> "<text>"` lets the agent record why it put the code
  where it did. The note is stored as `notes[]` (`by: agent`, `at`) in the JSON and shown in the Markdown. The
  agent never edits the file itself.
- **FR-210 (P2) Baseline.** `archiguard feedback --all` computes the code-based kinds over all code files of the
  repository, not just the branch. The lead architect runs it after releasing a map version to see which gaps
  remain.

### 3.6 Configuration and the domain map extension (FR-3xx)

- **FR-301** archiGuard's config gains the `feedback:` section (§5.8). It is added to `DEFAULT_CONFIG` and its
  validation, so unknown keys are errors and an old config without the section gets the defaults.
- **FR-302** `templates/domain-map-template.yaml` and `docs/standards.md` (*The domain map*) document
  `deployable` and `deployables` as optional keys read only by the loop feedback.
- **FR-303** `docs/loop-feedback.md` (user documentation) covers the kinds, the topology, the files, the
  lifecycle (§6.1) and the config.

### 3.7 auditGuard: recording (FR-4xx)

- **FR-401** The archiGuard collector reads `gates/loop-feedback.json` when it is present
  (`collectors.archiguard.feedback`, default `true`). `loop-feedback.json` is added to `SPECIAL`, so it is never
  read as a step verdict.
- **FR-402** On a new file fingerprint, the collector records a `report.saved` event (`name: loop-feedback.json`)
  with the snapshot as evidence. It then compares the items with the chain, using the chain as its memory:
  - `feedback.raised` for an id that is not open in the feature's chain;
  - `feedback.updated` for an open id whose item fingerprint changed (canonical JSON without `first_seen`), with
    `changed_fields`;
  - `feedback.resolved` for an open id that is in the file's `resolved[]`, or that is absent from a file whose
    `status` is `evaluated`.

  Every event carries the item and refers to the snapshot. A file with `status: not-evaluated` raises and resolves
  nothing.
- **FR-403** The new kinds are core kinds (not namespaced) and are listed in `docs/events.md` (§5.4).
- **FR-404 (P2)** A `feedback.raised` event carries `known: {verdict, ref, at, sprint}` when a decision with subject
  `feedback:<id>` exists in the `_project` chain or the feature's chain (US7).

### 3.8 auditGuard: triage and hand-over (FR-5xx)

- **FR-501** `auditguard decide feedback:<id> accept|reject|defer --by NAME [--role R] --reason T [--ref KEY]
  [--feature-dir D]`. This command is for people only (the same guard as every `decide`) and `--reason` is
  required for `reject` and `defer`. The decision is recorded as `decision` with subject `feedback:<id>`, the item
  snapshot and `ref`. It goes into the `_project` chain, because the DMD is project-level, or into the feature's
  chain with `--feature-dir`. An id that is in no chain is an error. A later decision on the same id supersedes
  the earlier one; for example, `accept --ref ARCH-77` after the tracker item was created.
- **FR-502** The *triage status* of an id is derived from its latest decision and from whether it is still open
  in any chain (§6.4):

  | Status | Meaning |
  |---|---|
  | `new` | not decided |
  | `deferred` | latest decision is `defer` |
  | `accepted` | `accept` without a ref |
  | `in-backlog` | `accept` with a ref |
  | `rejected` | latest decision is `reject` |
  | `resolved` | no longer raised in any feature, and not accepted |
- **FR-503** Open items (`model.open_items`) gain `feedback`: the ids in `new` or `deferred`. The open-items line
  reads `n loop-feedback item(s) untriaged`.
- **FR-504 Views.**
  - `trail.md` gains `## Loop feedback` after `## Gate verdicts`, with id, impact, kind, subject, suggestion, for
    and status.
  - `sprint.md` gains `## Loop feedback to the domain master design`, merged by id across the sprint's features,
    with a features column.
  - `features/<feature>.md` lists the feature's items with their status.
  - (P2) The viewer gains a *Feedback* screen with filters by kind, impact, addressee and status.
- **FR-505 Backlog export.** `auditguard backlog [--sprint S | --all] [--status new,accepted,...|all]
  [--format md|csv|json] [--out FILE]`. It writes one row per id, merged across features (§5.6). The default
  `--status` is `new,accepted`: the items that still need a tracker item. The command is read-only and agents may
  run it. It records nothing.
- **FR-506 Sprint close.** `sprint close` adds `feedback: {new, deferred, accepted, in_backlog, rejected,
  resolved}` to `seal.json`, inside the hash. It renders `audit/sprints/<S>/loop-feedback.md`, the sprint's
  backlog candidates with their triage status. `render` renders it as well, because the view can be regenerated
  from the sealed journals. `export` includes it in the audit pack.
- **FR-507 Completeness rule.** `rules.feedback_triaged_before_close` is `false` by default (D1). When it is on,
  `check` and `sprint close` report untriaged items as `[WARN]` in `mode: record` and `[FAIL]` in `mode: enforce`.
- **FR-508** `verify --golden` needs no change: G4 covers the snapshots of `loop-feedback.json` like any other
  evidence.

### 3.9 Guardians (FR-6xx)

- **FR-601** The bundle pins archiGuard `0.2.0` and auditGuard `0.3.0` (the versions that ship this feature).
- **FR-602** `guardians verify` gains `loop_feedback_recorded`:
  - `[OK]`: archiGuard `feedback.enabled` is true and auditGuard collects it;
  - `[WARN]`: archiGuard writes the feedback but auditGuard is older than `0.3.0` or has
    `collectors.archiguard.feedback: false`; the `fix:` line names the key;
  - `[--]`: the feedback is off.
- **FR-603** `docs/getting-started.md` gains *After coding: the loop feedback*, with the lifecycle of §6.1 and the
  triage commands.

---

## 4. Non-functional requirements

- **NFR-001 Non-interference.** Exit codes and every gate file are identical with the feedback on and off (US3);
  a test enforces this for `pass`, `violation`, `escalated` and `error` outcomes.
- **NFR-002 Determinism.** Equal inputs give byte-identical files, apart from `computed_at`, `computed_by` and
  `commit`. Paths use `/` on every OS, and keys are sorted.
- **NFR-003 Cost in the agent's loop.** There is no extra agent turn and no extra process: the feedback is
  computed inside the step-B process. The printed block has at most `feedback.print_items + 3` lines (6 by
  default).
- **NFR-004 Performance.** One git diff and one import scan, of the changed code files only. The feedback adds at
  most 1 s on `examples/orders` and at most 10 s for 2,000 changed files.
- **NFR-005 Bounded output.** At most 25 occurrences per item and `feedback.max_items` items (50).
- **NFR-006 Compatibility.**
  - auditGuard 0.2.x ignores the file, because it has no `step` key.
  - archiGuard 0.1.x ignores the new map keys (unknown context keys are not validated today).
  - The sibling version ranges (`collectors.archiguard.version: ">=0.1,<0.3"`) already admit archiGuard 0.2.0.
- **NFR-007 No network.** Everything is local. The repository name comes from the local git config.
- **NFR-008 Standard library only**, Python ≥ 3.9. The launchers are unchanged.

---

## 5. Data contracts

### 5.1 `specs/<feature>/gates/loop-feedback.json`

```json
{
  "tool": "archiguard",
  "kind": "loop-feedback",
  "schema": 1,
  "guardrail_version": "0.2.0",
  "feature": "specs/001-place-order",
  "status": "evaluated",
  "computed_at": "2026-11-12T16:40:03+01:00",
  "computed_by": "implement-b",
  "commit": "0e334be3a1…",
  "base": "main",
  "repository": "acme-shop",
  "pins": {"domain_map": "1.4.0", "rulebook": "acme-standards@v2026.10.1", "spec": "3"},
  "home_context": "orders",
  "topology": {
    "answer": "mixed",
    "units": [
      {"root": ".", "marker": "pom.xml", "new": false, "contexts": ["orders", "payments"], "files": 4, "declared": []},
      {"root": "services/notifications", "marker": "pom.xml", "new": true, "contexts": ["(unmapped)"], "files": 2, "declared": []}
    ]
  },
  "summary": {"items": 7, "high": 3, "medium": 2, "low": 2,
              "by_kind": {"new-unit": 1, "unmapped-code": 1, "domain-change": 1, "cross-context": 1, "topology": 1, "vocabulary": 1, "map-gap": 1}},
  "items": [
    {
      "id": "LF-2a2a5a3d",
      "kind": "new-unit",
      "subject": "acme-shop:services/notifications",
      "title": "New build unit services/notifications is not in the domain master design",
      "observation": "This branch adds services/notifications/pom.xml; no deployable of the domain map names it.",
      "suggestion": "Decide in the domain master design whether services/notifications is a new deployable (deployables.<name> with contexts.<context>.deployable), or move its code into the existing unit '.'.",
      "for": [{"role": "lead architect"}],
      "target": "domain-map: deployables, contexts.<context>.deployable",
      "impact": "high",
      "waiver": null,
      "occurrences": {"count": 1, "items": ["services/notifications/pom.xml"]},
      "evidence": [{"path": "services/notifications/pom.xml", "change": "added"}],
      "first_seen": "2026-11-12T16:40:03+01:00"
    }
  ],
  "resolved": [],
  "skipped": [],
  "truncated": 0
}
```

`status`: `evaluated | partial | not-evaluated`, plus `reason` when not evaluated. `skipped[]`: `{kind, reason}`.

### 5.2 `specs/<feature>/gates/loop-feedback.md` (and the report section)

```markdown
# Loop feedback - specs/001-place-order

Not blocking: what this feature did that the domain master design does not describe, for the next iteration.
archiGuard 0.2.0 · after implement step B · commit 0e334be · domain map 1.4.0 · repository acme-shop

## Topology: new service or existing one?

**Answer: mixed.** The feature extends the existing unit `.` and creates the new unit `services/notifications`,
which no context of the domain master design maps.

| Unit | New on this branch | Contexts of the changed code | Code files | Declared deployable |
|---|---|---|---|---|
| `.` (pom.xml) | no | orders (home), payments | 4 | none |
| `services/notifications` (pom.xml) | **yes** | unmapped | 2 | none |

## Items (7: 3 high, 2 medium, 2 low)

| Id | Impact | Kind | Subject | Suggestion for the next iteration | For |
|---|---|---|---|---|---|
| LF-2a2a5a3d | high | new-unit | acme-shop:services/notifications | Decide in the DMD whether it is a new deployable, or move its code into the existing unit `.` | lead architect |
| ... | | | | | |

## Resolved since the last run

None.
```

The compliance report section uses the same topology sentence and the item table, without the header lines.

### 5.3 The `FEEDBACK` block (terminal, after `RESULT`)

```text
FEEDBACK for the domain master design (not blocking, for the next iteration): 7 item(s) - 3 high, 2 medium, 2 low
  topology: mixed - existing unit '.' (orders, payments) + NEW unit 'services/notifications' (no context)
  [high]   LF-ef1129cf unmapped-code  services/notifications - Map services/notifications/** to a context in the next domain map version (…
  [high]   LF-2a2a5a3d new-unit       acme-shop:services/notifications - Decide in the domain master design whether services/notifications is a new …
  [high]   LF-42456a00 domain-change  waiver:WVR-0001 - Waived by WVR-0001 until 2026-12-31: refactor the code to meet ARCH-301, or change the domain map …
  ... 4 more: specs/001-place-order/gates/loop-feedback.md
```

One summary line, one topology line, at most `feedback.print_items` items (3) with their suggestions shortened to
one line, and a `... n more` line. With no items, the block is one line:
`FEEDBACK for the domain master design: nothing to report (topology: existing unit '.')`.

### 5.4 auditGuard events

| Kind | `data` |
|------|--------|
| `feedback.raised` | `id, kind, subject, title, observation, suggestion, impact, for[], target, waiver, occurrences.count, map_version, computed_by, computed_commit, fingerprint, known?` |
| `feedback.updated` | the same, plus `changed_fields[]` |
| `feedback.resolved` | `id, kind, subject, raised_event, computed_by, computed_commit` |
| `decision` (subject `feedback:<id>`) | `subject, verdict (accept \| reject \| defer), by, role, reason, ref?, item` |

`stage` is the feature's stage at the time (implement or test). The evidence is the snapshot of `loop-feedback.json`.

### 5.5 Item triage state machine

```text
raised ──> new ──decide accept──> accepted ──decide accept --ref──> in-backlog
            │  └─decide defer──> deferred ──(next triage)──> accepted | rejected
            └─decide reject──> rejected
any state except accepted / in-backlog ──(no feature raises it any more)──> resolved
```

### 5.6 Backlog export (`auditguard backlog`)

- `--format csv`. The columns import into common trackers:

  ```text
  External ID,Summary,Description,Priority,Labels,Status,Ref,Features,First sprint,Evidence
  LF-2a2a5a3d,"New build unit services/notifications is not in the domain master design","This branch adds services/notifications/pom.xml; no deployable of the domain map names it. Suggestion: Decide in the domain master design whether ... Target: domain-map: deployables. For: lead architect.",High,"loop-feedback;new-unit;orders",accepted,,specs/001-place-order,S-2026-22,audit/sprints/S-2026-22/001-place-order/evidence/3c9e…-loop-feedback.json
  ```

  `Priority` maps `high | medium | low` through `backlog.priority` (default `High | Medium | Low`). `Labels` are
  `loop-feedback`, the kind and the contexts in the subject.
- `--format md`: one table per addressee role, in the item columns of §5.2 plus `Features`, `Status` and `Ref`.
- `--format json`: a list of items with every field, `features[]`, `sprints[]`, `status`, `ref` and `decisions[]`.

### 5.7 Domain map: optional topology keys

```yaml
contexts:
  orders:
    # ... existing keys ...
    deployable: orders-service              # one name or a list: the unit(s) the context is deployed in
deployables:                                # optional: where each unit lives (polyrepo and monorepo)
  orders-service:   { repo: acme-shop,     root: ".",  kind: service }
  payments-service: { repo: acme-payments, root: ".",  kind: service }
```

### 5.8 Configuration

```yaml
# archiguard-config.yml - loop feedback to the domain master design: evidence after coding, never a gate.
feedback:
  enabled: true
  kinds: [unmapped-code, cross-context, new-unit, topology, vocabulary, domain-change, map-gap]
  code: auto                  # globs of code files; auto = the source extensions of archiGuard's code analysis
  ignore: ["specs/**", ".specify/**", "audit/**", "docs/**", ".github/**"]
  unit_markers: [pom.xml, build.gradle, build.gradle.kts, package.json, go.mod, "*.csproj", pyproject.toml,
                 setup.py, Cargo.toml, Dockerfile, Chart.yaml]
  group_depth: auto           # directory depth of an unmapped-code item; auto = the depth of the map's code globs
  repository: auto            # this repository's name in deployables; auto = the origin remote's name
  domain_rules: auto          # rules whose deviations / waivers are domain feedback; auto = rules with a context_boundaries check
  max_items: 50
  print_items: 3
```

```yaml
# auditguard-config.yml
collectors:
  archiguard:
    feedback: true            # record gates/loop-feedback.json (feedback.raised / updated / resolved)
rules:
  feedback_triaged_before_close: false
backlog:
  priority: { high: High, medium: Medium, low: Low }
  labels: [loop-feedback]
```

---

## 6. Behaviour

### 6.1 Lifecycle: when the feedback is created and how it is handed over

```text
 loop step 0   domain master design (domain-map.yaml vN, lead architect) <────────────────────────────────┐
     │                                                                                                    │
 specify / plan / tasks       A0 gates: the map as a contract (blocks)                                    │
     │                                                                                                    │
 implement     ─T1─> gates/loop-feedback.json + .md ─> FEEDBACK block ─> Completion Report                │
     │            └T2─> auditGuard: feedback.raised / updated / resolved (evidence)                       │
 handover 4→5  ─T3─> handover-4-5.json "feedback" (the code that enters testing)                          │
 test loop                                                                                                │
 report --save ─T4─> architecture-compliance.md "Loop feedback" = THE FINAL FEEDBACK ─> PR approval (informs)
 sprint review ─T5─> triage: decide feedback:<id> accept|reject|defer ; backlog --format csv ─> tracker ──┤
                     decide ... accept --ref <tracker key>   (backlog items: map vN+1, refactoring before   │
                     a waiver expires, glossary, ownership)                                               │
 sprint close  ─T6─> seal counts + audit/sprints/<S>/loop-feedback.md, in the audit pack                  │
 next iteration ─T7─> map vN+1 released and pinned ──────────────────────────────────────────────────────┘
```

| # | When | Triggered by | What happens | Output | Handed to |
|---|------|--------------|--------------|--------|-----------|
| T1 | End of coding: implement step B ends `pass` or `escalated` | the runner, in the same process | computed, files written, block printed | `gates/loop-feedback.json` / `.md`; the `Loop feedback` lines of the Completion Report | the developer, who reads it; the agent only reports it |
| T2 | `after_implement` hook, `collect`, any later hook | auditGuard collector | items recorded with a snapshot | `feedback.*` events; `trail.md` section | the audit trail |
| T3 | Handover 4 → 5 | `archiguard handover` (workflow step or a person) | recomputed on the code that enters testing | `handover-4-5.json` → `feedback` | the QA lead (a new unit can mean a new deployment and test environment) |
| T4 | End of the loop, on the final commit | `archiguard report --save` (workflow `report` step) | recomputed; section in the compliance report | `architecture-compliance.md` | the tech lead at PR approval, as information |
| T5 | Sprint review or architecture board | the lead architect, with the domain owners | `auditguard backlog --status new`, then one decision per item; `backlog --status accepted --format csv` is imported into the tracker; `decide ... accept --ref <key>` links each tracker item | `decision` events; backlog CSV | the product owner (architecture backlog) |
| T6 | Sprint close | a person (`sprint close`) | triage counts sealed; sprint view rendered | `seal.json` → `feedback`; `audit/sprints/<S>/loop-feedback.md`; the audit pack | the audit record of the sprint |
| T7 | Next iteration | the lead architect releases map vN+1; projects move the pin | items no longer raised; `known` items not triaged again | — | — |

**Typical backlog items per kind:**

| Kind | For | Typical backlog item |
|---|---|---|
| new-unit | lead architect | DMD vN+1: declare `notifications-service` as a deployable of a context, or merge the code into `orders` |
| unmapped-code | lead architect | DMD vN+1: map `services/notifications/**` to a context (or a new context) |
| domain-change (waiver) | tech lead + lead architect | Refactor `orders` to `com.acme.payments.api` before 2026-12-31 (WVR-0001), or publish the package in DMD vN+1 |
| cross-context | the other context's owner | Payments backlog: take ownership of the change in `PaymentsClient` |
| topology | lead architect | DMD vN+1: declare the deployables of `orders` |
| vocabulary | domain owner, BA | Glossary of `orders`: add `Checkout`, or rename it in the data model |
| map-gap | lead architect | DMD vN+1: declare the code paths of `customers` |

### 6.2 Computation order

1. Load the config. When `feedback.enabled` is false, stop (FR-005).
2. Load the domain map and the home context. If either is missing: `not-evaluated`.
3. Read git: changed files, added files and the base. Without git or a base, skip the kinds that need them
   (`partial`).
4. Select the code files (FR-003) and map each to a context.
5. Find the units and work out the topology (§3.3).
6. Compute the kinds in the order of §3.2, applying the deduplication rules (FR-101, FR-104).
7. Attach waivers, ids, `first_seen` and `resolved[]`, then sort and cap.
8. Write the files if anything changed (FR-135), then print.

### 6.3 Topology decision table (home context)

| Home context's code is in | Declared deployables of home | Items |
|---|---|---|
| existing units only | none | `topology <home>:undeclared` |
| existing units only | in this repository, roots match | none |
| an existing unit | in this repository, other root | `topology <home>:<repo>:<unit>` |
| any unit | only in other repositories | `topology <home>:<repo>` |
| a new unit | none, or not that root | `new-unit <repo>:<unit>`, plus `topology <home>:undeclared` when there is none |
| a new unit | declared at that root | none (`new, declared`) |

---

## 7. Interfaces

### 7.1 archiGuard CLI

```text
archiguard feedback [--feature-dir D] [--save] [--json] [--note <id> "<text>"] [--all]   # --note, --all: P2
archiguard report   [--feature-dir D] [--save] [--json] [--out FILE]   # --save recomputes the feedback first
archiguard handover [--feature-dir D] [--json]                         # manifest gains "feedback"
archiguard ci       [...] [--feedback]                                  # prints, never writes, never fails
```

### 7.2 Preset `speckit.implement.md`, step B (additions)

> **2. Exit 0: pass.** [...] plus the advisory findings and waivers as printed. When the output has a `FEEDBACK`
> block, add a `Loop feedback (not blocking)` section to the Completion Report with its summary line and its
> topology line as printed. **Do not act on the feedback in this command**: its items are for the domain master
> design and the next iteration. Never edit `gates/loop-feedback.json` or `.md`.
>
> **4. Exit 3: escalate.** [...] Report `archiGuard: ESCALATED ...` and, when printed, the `FEEDBACK` summary and
> topology lines.

### 7.3 auditGuard CLI

```text
auditguard decide feedback:<id> <accept|reject|defer> --by NAME [--role R] [--reason T] [--ref KEY] [--feature-dir D]   # --reason required for reject and defer
auditguard backlog [--sprint S | --all] [--status new,deferred,accepted,in-backlog,rejected,resolved|all] [--format md|csv|json] [--out FILE]
```

---

## 8. Repository, modules, tests, release

### 8.1 Changes per repository

| Repository | Files |
|---|---|
| spec-kit-archiguard | `scripts/python/archiguard_core/feedback.py` (new) · `runner.py` (FR-201, block in `render_text`) · `commands.py` (`cmd_feedback`, `build_report` section, `cmd_handover` key) · `gates/handover.py` (`build_manifest`) · `domain.py` (optional keys) · `config.py` (`feedback` defaults and validation) · `configure.py` (FR-208) · `cli.py` · `config-template.yml` · `templates/domain-map-template.yaml` · `preset/commands/speckit.implement.md` and the `implementgate` command · `workflows/archiguard-sdd/workflow.yml` (FR-207) · `docs/loop-feedback.md` (new), `docs/configuration.md`, `docs/standards.md`, `README.md` (one section) · `tests/test_feedback.py` (new) · `CHANGELOG.md` |
| spec-kit-auditguard | `collectors/archiguard.py` · `decisions.py` (`feedback` subject, `--ref`) · `model.py` (triage status, open items) · `render_md.py` (trail, sprint, feature) · `backlog.py` (new) · `cli.py` · `config.py` and `config-template.yml` · `decisions.build_seal` (counts) · `docs/events.md`, `docs/collectors.md`, `docs/configuration.md`, `README.md` · tests · `tools/make-example.py` (an item, a decision, a backlog file in `examples/orders`) |
| spec-kit-guardians | `bundle/bundle.yml`, `catalog/*.json` (pins) · `guardians_core/verify.py` (`loop_feedback_recorded`) · `docs/getting-started.md` · tests |

### 8.2 Tests (minimum)

- **archiGuard.**
  - One fixture per kind, including every row of the topology decision table (§6.3).
  - `group_depth: auto` on the example map.
  - Id stability across runs and features.
  - Write-if-changed.
  - `resolved[]` after a repair.
  - `not-evaluated` and `partial` paths: no map, no handover, no git, no base.
  - The non-interference matrix (NFR-001) for `pass`, `violation`, `escalated` and `error`.
  - The block layout and its line cap.
  - The report section, and the handover manifest key.
  - An unknown `feedback.*` key is a config error.
  - A0 and A4 results are unchanged with and without the new map keys.
- **auditGuard.**
  - raised, updated and resolved from successive files; no event for an unchanged file; nothing from a
    `not-evaluated` file.
  - A decision in `_project` and in a feature chain; the triage status table.
  - `known` items.
  - Backlog merge across two features, and the CSV columns.
  - Seal counts inside the hash.
  - The rule off and on, in record and enforce modes.
  - The agent-context refusal for `decide`.
- **Guardians.** `loop_feedback_recorded` in its three states.

### 8.3 Implementation order

1. archiGuard: config section, optional map keys, `feedback.py` with the kinds and the topology, files, `feedback`
   command.
2. archiGuard: runner, handover, report, preset and workflow text, docs. Release `0.2.0`.
3. auditGuard: collector, events, views, `decide feedback:`, `backlog`, seal. Release `0.3.0`.
4. Guardians: pins and verify check. Release `0.2.0`.

---

## 9. Success criteria

- **SC-001** On the US1 branch, the feedback lists exactly the seven items of Appendix A, in that order, with the
  topology answer `mixed`.
- **SC-002** The exit codes and gate files are identical with the feedback on and off, in all four outcomes
  (NFR-001).
- **SC-003** Running the computation a second time without a change rewrites no file, and auditGuard records no
  event.
- **SC-004** An item raised by two features is one row in `auditguard backlog`, listing both features.
- **SC-005** `decide feedback:<id> accept --ref KEY` is shown as `in-backlog` in `trail.md`, `sprint.md` and the
  backlog export, and the sprint seal counts it.
- **SC-006** With a missing domain map, the file says `not-evaluated` with the reason, and the step's exit code is
  unchanged.
- **SC-007** The printed block is at most 6 lines with the defaults.

---

## 10. Points to confirm (proposed defaults; all implemented as proposed)

| # | Question | Proposed |
|---|----------|----------|
| P1 | Is the feedback on by default for existing projects after the upgrade? | Yes (`feedback.enabled: true`): it never blocks and costs no agent turn. |
| P2 | Where do triage decisions live? | In the `_project` chain, because the DMD is project-level. `--feature-dir` puts a decision into one feature's chain instead. |
| P3 | Do untriaged items affect sprint close? | No by default. `rules.feedback_triaged_before_close` is opt-in, and gives `[WARN]` in `mode: record`. |
| P4 | Tracker integration | Files only in P1 (CSV, Markdown, JSON). A plug-in that creates issues from `backlog --format json` comes later. |
| P5 | Topology for contexts other than the home context | Units only, in the topology table. Items for the home context only, to keep the noise low. |
| P6 | Should the domain map's own validation (`validate-standards`, A0) check the new keys? | No: they stay feedback-only until a later version decides to gate on them. |

---

## Appendix A. Example: `examples/orders`, feature `001-place-order`

**Set-up.** Domain map 1.4.0 (contexts `orders`, `payments`, `customers`), home context `orders`, base `main`,
repository `acme-shop`, a `pom.xml` at the root. The branch:
- adds `services/notifications/pom.xml` and two Java files under `services/notifications/src/main/java/com/acme/notifications/`;
- changes `src/main/java/com/acme/payments/api/PaymentsClient.java`;
- keeps the import of `com.acme.payments.internal.PaymentGateway` in `OrderController.java` under the approved
  waiver `WVR-0001` for ARCH-301 (expires 2026-12-31);
- has the entity `Shipment` in `data-model.md` (not in the glossary of `orders`).

The map declares no deployables, and `customers` has `modules` but no `code`.

| Id | Impact | Kind | Subject | Suggestion for the next iteration | For |
|---|---|---|---|---|---|
| LF-ef1129cf | high | unmapped-code | services/notifications | Map `services/notifications/**` to a context in the next map version, or declare a new context for it | lead architect |
| LF-2a2a5a3d | high | new-unit | acme-shop:services/notifications | Decide in the DMD whether `services/notifications` is a new deployable, or move its code into the existing unit `.` | lead architect |
| LF-42456a00 | high | domain-change | waiver:WVR-0001 | Waived by WVR-0001 until 2026-12-31: refactor the code to meet ARCH-301, or change the domain map so the dependency is allowed (a relation or a published interface), before then | lead architect, tech lead |
| LF-885c1908 | medium | cross-context | orders->payments | 1 file of `payments` changed under the customer-supplier relation: plan it as a payments backlog item owned by the Payments domain owner, or record a partnership | Payments domain owner, lead architect |
| LF-2ba4e67d | medium | topology | orders:undeclared | Declare the deployment unit(s) of `orders` (`contexts.orders.deployable`, `deployables`) | lead architect |
| LF-831ba84c | low | vocabulary | orders:shipment | Add `Shipment` to the glossary of `orders` (or as a synonym), or rename it in the data model | Orders domain owner, BA |
| LF-c90bb238 | low | map-gap | customers:no-code | Declare the code paths of `customers` so the context-boundary fitness function covers it | lead architect |

**Completion Report lines written by the agent (T1):**

```text
archiGuard: PASS after 0 repair iteration(s) · 1 waived (ARCH-301, WVR-0001)
Loop feedback (not blocking): 7 item(s) for the domain master design - 3 high, 2 medium, 2 low
  topology: mixed - existing unit '.' (orders, payments) + NEW unit 'services/notifications' (no context)
  ... 4 more: specs/001-place-order/gates/loop-feedback.md
```

**Triage and hand-over at the sprint review (T5), then sprint close (T6):**

```bash
A=".specify/extensions/auditguard/scripts/bash/auditguard.sh"
bash $A backlog --status new
bash $A decide feedback:LF-2a2a5a3d accept --by "Lead architect" --reason "notifications becomes its own context in DMD 1.5.0"
bash $A decide feedback:LF-831ba84c reject --by "Orders domain owner" --reason "Shipment moves to the fulfilment context; renamed in the next spec"
bash $A backlog --sprint S-2026-22 --status accepted --format csv --out backlog-S-2026-22.csv   # import into the tracker
bash $A decide feedback:LF-2a2a5a3d accept --ref ARCH-77 --by "Lead architect" --reason "created in the tracker"
bash $A sprint close S-2026-22 --by "Roman"                                                     # seal: feedback counts
```

# Loop feedback to the domain master design

The A0 and A4 gates treat the domain map as a contract: a feature must fit the map, or it stops. They do not tell
the lead architect what the map *missed*: code that no context maps, a new build unit that may be a new service, a
context whose deployment unit nobody declared, a dependency that only passes because of a waiver, a term the
glossary does not know. **Loop feedback** carries that back from the implementation to loop step 0, the domain
master design (DMD), as evidence with a short suggestion per item for the next iteration.

**It is evidence, never a gate.** It never changes an exit code, a verdict, an iteration count or an escalation. If
it cannot be computed, the file says why and the runner prints one line. It is deterministic: git, globs, the domain
map, the handover record, the lock, the ledger and the plan, with no LLM. Every suggestion is a template filled with
data. The [specification](loop-feedback-specification.md) has the full contract.

## When it is created and how it is handed over

| When | What happens | Who it is for |
|---|---|---|
| End of coding: `/speckit.implement` step B ends `pass` or `escalated` | the runner computes the feedback in the same process, writes the files and prints the `FEEDBACK` block after the result; the agent copies its summary into the Completion Report and does not act on it | the developer |
| auditGuard hook (`after_implement`, `collect`) | every item is recorded as evidence (`feedback.raised` / `updated` / `resolved`), with a snapshot of the file | the audit trail |
| `archiguard handover` (4 → 5) | recomputed on the code that enters testing; the manifest `handover-4-5.json` gets a `feedback` entry | the QA lead (a new unit can mean a new deployment) |
| `archiguard report --save` on the final commit | recomputed; the compliance report gets the section *Loop feedback to the domain master design (not blocking)*. This is **the final feedback** | the tech lead at PR approval (informs, never blocks) |
| Sprint review / architecture board | `auditguard backlog --status new`, then `auditguard decide feedback:<id> accept \| reject \| defer`; `auditguard backlog --status accepted --format csv` for the tracker, `decide ... accept --ref <key>` links each tracker item | the lead architect, the domain owners, the product owner |
| Sprint close | the triage counts are sealed; the sprint's feedback view goes into the audit pack | the audit record |
| Next iteration | the lead architect releases the next map version; the gaps it closes are no longer raised | — |

`archiguard feedback [--save]` (or `/speckit.archiguard.feedback`) computes it on demand, and `archiguard ci
--feedback` prints it for the final commit without writing anything.

## What it reports

Each item has an id (`LF-` plus 8 hex digits of `sha256("<kind>\n<subject>")`), a kind, a subject, an observation,
a suggestion, the people it is for, the artefact the fix belongs in (`target`) and an impact hint. The subject never
contains the feature, so the same gap found by two features (or two runs) is one item and one backlog row.

| Kind | Subject | Impact | What it found | Typical suggestion |
|---|---|---|---|---|
| `unmapped-code` | the directory (grouped like the map's `code:` globs) | high | changed code that no context's `code:` maps (A4.4 cannot check it) | map `<dir>/**` to a context, or declare a new one |
| `cross-context` | `<home>-><other>` | medium (high without a relation) | the feature changed another context's code | plan it as the other context's backlog item, or record a partnership |
| `new-unit` | `<repository>:<unit root>` | high | a unit marker (`pom.xml`, `package.json`, `Dockerfile`, ...) added on the branch | declare it as a deployable, or move the code into the existing unit |
| `topology` | `<home>:undeclared`, `<home>:<repo>`, `<home>:<repo>:<unit>`, `repo:<repo>` | medium | the home context declares no deployable, is deployed from another repository, or its code changed in a unit it is not deployed in | declare the deployables of the context |
| `vocabulary` | `<home>:<term>` | low | an entity or contract name outside the glossary (the A0.4 logic) | add it to the glossary or as a synonym, or rename it |
| `domain-change` | `relation:<a>-><b>`, `published:<ctx>:<package>`, `waiver:<id>`, `rule:<id>:<home>`, `entity:<Entity>` | high with a waiver or deviation in force, else medium | an import the map does not allow, a package the other context does not publish, a waiver A4.4 applied, a deviation of a domain rule, an entity without a reachable owner | propose the relation, publish the package, or refactor before the waiver expires |
| `map-gap` | `<ctx>:no-code`, `<ctx>:no-owner`, `deployable:<name>:undefined`, `map:no-code-paths` | low | gaps in the map that limit what the gates can check | declare the code paths, name the owner, define the deployable |

## Topology: a new service or an existing one?

Every changed code file belongs to the nearest directory at or above it that holds a unit marker (its *unit*). A
unit is *new* when every marker in its root was added on the branch. The answer is `existing`, `new`, `mixed`,
`unknown` (no base branch, or no marker found) or `none` (no code changed). With the optional `deployable` and
`deployables:` keys of the domain map ([standards.md](standards.md#the-domain-map)) it also says whether each unit is
declared, and raises a `topology` item when the code landed somewhere the DMD does not deploy its context.

## What it looks like

At the end of `/speckit.implement` step B (from `examples/orders` with a new `services/notifications` unit, a
changed payments class and ARCH-301 under the waiver WVR-0001):

```text
archiGuard: PASS after 0 repair iteration(s).

FEEDBACK for the domain master design (not blocking, for the next iteration): 7 item(s) - 3 high, 2 medium, 2 low
  topology: mixed - existing unit '.' (orders, payments) + NEW unit 'services/notifications' (no context)
  [high]   LF-ef1129cf unmapped-code  services/notifications - Map services/notifications/** to a context in the next domain map version (…
  [high]   LF-2a2a5a3d new-unit       acme-shop:services/notifications - Decide in the domain master design whether services/notifications is a new …
  [high]   LF-42456a00 domain-change  waiver:WVR-0001 - Waived by WVR-0001 until 2026-12-31: refactor the code to meet ARCH-301, or change the domain map …
  ... 4 more: specs/001-place-order/gates/loop-feedback.md
```

The agent writes into its Completion Report:

```text
Loop feedback (not blocking): 7 item(s) for the domain master design - 3 high, 2 medium, 2 low
  topology: mixed - existing unit '.' (orders, payments) + NEW unit 'services/notifications' (no context)
  ... 4 more: specs/001-place-order/gates/loop-feedback.md
```

## Files

| File | What it is |
|---|---|
| `specs/<feature>/gates/loop-feedback.json` | authoritative: status, topology, items, `resolved[]` (the ids an earlier run raised that are gone), `skipped[]`; protected by the edit guard (`specs/*/gates/**/*.json`); it has no `step` key, so it is never read as a step verdict |
| `specs/<feature>/gates/loop-feedback.md` | the view: the topology answer and table, the items, each item in detail, the resolved ones |

The files are rewritten only when anything other than `computed_at`, `computed_by` and `commit` changed, so an
unchanged feedback leaves no new evidence. Commit them with the feature, like the other evidence.

## Configuration

```yaml
feedback:
  enabled: true
  kinds: [unmapped-code, cross-context, new-unit, topology, vocabulary, domain-change, map-gap]
  code: auto
  ignore: ["specs/**", ".specify/**", "audit/**", "docs/**", ".github/**"]
  unit_markers: [pom.xml, build.gradle, build.gradle.kts, package.json, go.mod, "*.csproj", pyproject.toml, setup.py, Cargo.toml, Dockerfile, Chart.yaml]
  group_depth: auto
  repository: auto
  domain_rules: auto
  max_items: 50
  print_items: 3
```

[configuration.md](configuration.md) explains every key. Unknown keys are errors, like everywhere in the config.

## What it does not do

- It does not change the domain map, the ledger or the code, and the agent is told not to act on it in the command
  that printed it: every item is for a person and the next iteration.
- It does not judge whether the code *should* be a new service. It reports the facts (a new unit, unmapped code, an
  undeclared topology) and who decides.
- It does not create tracker issues. auditGuard exports backlog candidates as CSV, Markdown or JSON
  (`auditguard backlog`), which trackers import.

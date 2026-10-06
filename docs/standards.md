# Standards: the rulebook, the lock and the domain map

archiGuard binds a project to its architecture standards through three files that live in the
**policy channel**, a standards repository that is released by tag and checked out per project at the
pinned tag (a git submodule at `.specify/standards` by default):

- the **rulebook**: architecture standards as skills, with every rule declared as data;
- the **domain map**: the domain master design (contexts, ownership, relations, code mapping);
- (in the project) the **decision ledger**: ADRs and waivers, hash-chained.

`archiguard scaffold rulebook` and `archiguard scaffold domain-map` write starting files.
`archiguard validate-standards [path]` lints a rulebook; run it in the standards repository's CI.

## Rulebook layout

```text
rulebook.yml                  name, version (= the tag), optional stack markers, not-applicable reasons
skills/<skill>/SKILL.md       the guidance the agent reads before it plans or codes against the rule
skills/<skill>/rules.yml      the rules of the skill (or any *.rules.yml next to a SKILL.md)
profiles/<name>.yml           a named rule set per stack, owned centrally
packs/<name>.yml              a rule set a domain-map context pulls in (contexts.<name>.packs)
```

```yaml
# rulebook.yml
name: acme-standards
version: v2026.10.1                     # equals the tag projects pin: acme-standards@v2026.10.1
stacks:                                 # optional: add or replace stack markers
  java: [pom.xml, build.gradle, build.gradle.kts]
not_applicable_reasons: [no-persistence, no-external-interface, no-ui, no-messaging, no-batch,
                         read-only, no-personal-data, no-new-component]

# profiles/java-service.yml               # packs/payments-pci.yml has the same shape (pack: <name>)
profile: java-service
extends: []                             # other profiles
skills: [api-contracts, layering, context-boundaries, secrets]   # every rule of these skills
rules: [ARCH-501]                       # and these rules
```

Default stack markers: `java` (Maven or Gradle files), `node` (`package.json`), `python`
(`pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt`, `Pipfile`), `dotnet` (`*.csproj`,
`*.sln`, `*.fsproj`), `go` (`go.mod`), `cobol` (`*.cbl`, `*.cob`).

## Rules

```yaml
rules:
  - id: ARCH-201                        # unique across the rulebook
    title: Layers depend downwards only (api -> application -> domain)
    level: must                         # must = blocking finding; should = advisory
    applies_when:
      stack: [java]                     # only in repositories with this stack; empty = every stack
      contexts: [orders]                # only for features whose home context is listed
    targets: [plan, code]               # where the rule must be accounted for (also taken from the checks)
    text: Each layer depends only on the layers below it.   # shown to the agent with a finding
    checks:                             # none = "agent judgement", reviewed by the design authority
      - target: code
        kind: layers
        ...
```

Each check names a **target**, and archiGuard maps the target to a gate. The mapping is fixed in the engine:

| Target | Gate | When |
|--------|------|------|
| `plan`, `contract` | A3.3 check-plan | `/speckit.plan` step B |
| `tasks` | A3.5 task guard | `/speckit.tasks` step B |
| `edit` | A4.2 edit guard | after every agent edit |
| `code` | A4.4 fitness functions | `/speckit.implement` step B, handover H3, CI |
| `runtime` | A7 architecture assessor | not run by archiGuard |

Every applicable rule that targets the plan or a contract (a rule without targets or checks counts as
a plan rule) must have a row in plan.md's `## Architecture Conformance` table: `satisfied` with the plan
reference, `not applicable` with one of the rulebook's reasons, or `deviation` with an approved ADR. A3.5 requires a `[FITNESS]` task in tasks.md for every rule with a
`code` check; A4.4 ticks it when the check passes.

### Check kinds

Every kind takes optional `message` (prefixed to the finding), `fix_hint`, and for file-based kinds
`files` / `except_files` globs. `root: repo | feature` overrides where files are searched (default: the
repository for `code` and `edit`, the feature directory otherwise).

| Kind | Targets | Parameters | Finding when |
|------|---------|------------|--------------|
| `require_file` | plan, contract, tasks, code | `files` | no file matches |
| `require_text` | plan, contract, tasks, code | `files`, `pattern` (regex), `mode: any \| each` | no matching file contains the pattern (`each`: a matching file lacks it) |
| `forbid_text` | plan, contract, tasks, code, edit | `files`, `pattern` | the pattern occurs (one finding per hit, with the line) |
| `require_section` | plan, contract, tasks | `heading` (regex), `file` (default plan.md / tasks.md) | the section is missing |
| `require_task` | tasks | `pattern` (default: the rule id) | no task matches |
| `forbid_import` | code, edit | `imports` (regexes), `files` | a file imports a matching module |
| `layers` | code, edit | `layers: [{name, files, modules}]`, `allow: {layer: [layers]}`, `scope: all \| context` | a layer imports a layer it may not depend on (`scope: context`: only inside one context) |
| `context_boundaries` | code, edit | `files`, `published_only` (default true) | a context imports another context without a domain-map relation, or outside its published interface |
| `contract_routes` | code | `sources` (globs), `contracts` (default `contracts/**/*.{yaml,yml,json}`) | an OpenAPI path of the feature's contracts is not found in the sources |
| `readonly` | edit | `files` | an agent tries to edit a matching file (blocked by the edit guard) |
| `command` | plan, contract, tasks, code | `run` (argv list, or a string with `shell: true`), `timeout` | the command exits non-zero (its output is shown to the agent) |

Imports are read for Java/Kotlin/Scala/Groovy, JavaScript/TypeScript, Python, C#, Go and COBOL
(`COPY` / `CALL`). A `command` check runs on developer machines and in CI with the project as working
directory: the standards repository's review process is what makes such a check trustworthy.

## The lock

`archiguard resolve` selects the rules for the project (profile + include + the packs of the domain-map
contexts − exclude), checks the rulebook name and tag, and writes `.specify/archiguard/standards.lock.yml`:
the rulebook identity (name, tag, commit when the standards are their own checkout), the config it
was resolved from, the domain map version and packs, and every selected rule with its checks and a
hash. Commit it. The agent, every checker and CI read the rules from the lock only.

- A gate whose lock no longer matches the `standards` section of the config exits `2` (run `resolve`).
- `archiguard resolve --check` and `archiguard ci` re-resolve and fail on any drift: a changed rule,
  a new tag, a changed profile.
- Excluding a `must` rule needs an approved, unexpired ledger entry that names the rule:
  `exclude: [{ rule: ARCH-118, waiver: ADR-0042 }]`.

For each feature, A3.1 filters the lock by the repository's stack and the feature's home context and
writes `specs/<feature>/gates/applicable-rules.json`: the rules the plan must meet, and the rules
filtered out with the reason. Rules that come only from a pack apply only to features whose home
context lists the pack.

## The domain map

```yaml
domain_map_version: "1.4.0"     # a released, semantic version; a pre-release cannot be pinned
status: released
contexts:
  orders:
    domain: commerce
    owner: Orders domain owner
    glossary: [Order, Order line, Customer, Basket]     # A0.4 vocabulary
    synonyms: { Purchase: Order }
    owns_entities: [Order, OrderLine]                   # A0.3 ownership
    publishes: [api:orders/orders.yaml]
    code: ["src/main/java/com/acme/orders/**"]          # A4.4 context boundaries
    modules: [com.acme.orders]
    published: [com.acme.orders.api]                    # what other contexts may import
    packs: []                                           # rulebook packs this context pulls in
relations:
  - { from: orders, to: payments, type: customer-supplier, via: [api:payments/payments.yaml] }
```

`from` is the consumer. The BA specification tool ingests the data model (a sub-product of the domain model), builds the
Data artefacts (D) and the context map (MAP) from it, and the formal handover stamps the domain map
version into the feature's `handover.yml`. A0.1 checks that version against the repository's pin
(`domain.pin`), A0.2 the home context, A0.3 that every data node is owned by the home context or reached
through an allowed relation, A0.5 that every integration point of the plan names a target context and a
relation type the map allows, and A0.4 that entity and contract names use the home context's glossary.
A0.5 reads plan.md's `## Integration Points` table; references inside `contracts/` are checked by rules with
a `contract` target (A3.3) and, in the code, by the context-boundary fitness function (A4.4).

## The handover record

`specs/<feature>/handover.yml` is written by the formal handover from the BA specification tool to Spec Kit and is read-only
for agents ([template](../templates/handover-template.yml)): the specification version and its sha256,
the domain map version, the use cases with their home context, the D artefacts with their entity and
context, and the in-scope ids that A3.5, H4 and the test loop trace.

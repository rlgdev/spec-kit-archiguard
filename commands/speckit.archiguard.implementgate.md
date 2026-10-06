---
description: "archiGuard step B of /speckit.implement (integration: hooks): fitness functions and traceability - resolve, re-check, escalate"
scripts:
  sh: bash scripts/bash/archiguard.sh run implement b --via hook
  ps: scripts/powershell/archiguard.ps1 run implement b --via hook
  py: scripts/python/archiguard.py run implement b --via hook
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Run archiGuard's step B gates for `/speckit.implement` and **resolve every finding** before the command reports
completion. This command is the `after_implement` hook when `integration: hooks` is configured; with
`integration: inline` the same step runs inside `/speckit.implement` and this command prints `skipped`.

The script decides; you resolve. Never re-interpret its verdict. Exit codes: **0** pass (or skipped), **1** resolve, **3** escalate, **2** cannot evaluate (fail-closed).

## Procedure

The runner counts the iterations itself; never pass an iteration number.

1. **Check.** From the repository root run `{SCRIPT}`. Append `--feature-dir <dir>` if the user input names a
   feature directory. Keep the exit code and the full output; its first line names the feature directory
   (`<FEATURE_DIR>` below).
2. **Exit 0 - pass or skipped.** If the output says `skipped`, say nothing more. Otherwise report one line, for
   example `archiGuard: PASS after N repair iteration(s)`, plus the advisory findings and waivers as printed. Done.
3. **Exit 1 - resolve.** The output lists every open item under `RESOLVE`, with where it is, the fix hint and the rule
   or specification text to work from. Resolve **all** of them, then go back to step 1.
   - **Fitness** (A4.4): fix the code that breaks a rule (layering, context boundaries, contracts, forbidden
     constructs). Never change `plan.md`, the contracts or the specification in step 4: a fix that needs a design change
     goes back to Design for a new sign-off - leave it open so the runner escalates.
   - **Traceability** (A4.6): commit messages name their task and requirement ids; test files carry the ids they verify.
   - **Scope** (scope gate): finish every task that carries an in-scope requirement.
   - Never edit `spec.md`, `handover.yml`, `ba/`, the standards (`.specify/standards/`), `standards.lock.yml`, the decision ledger, `archiguard-config.yml` or a verdict file under `<FEATURE_DIR>/gates/` to make a gate pass (the escalation note is the only file there you complete).
   - Never run `archiguard signoff`, `reopen`, `resolve`, `ledger add` or `ledger revoke`, and never write a ledger entry yourself: sign-offs, approvals, waivers and the standards lock are decisions of people (the design authority, the lead architect). The edit guard blocks these commands for agents.
   - Never mark a rule `not applicable` or `deviation`, and never defer a scope item, just to make the gate pass: `not applicable` needs a reason from the allowed list, `deviation` needs an approved, unexpired ADR in the decision ledger, a deferral is a scope change: it needs a reason the user approved (and, when the project requires it, the RFI or decision-ledger entry that approved it).
   - If an item can only be resolved with information or a decision that only a person can give (a specification change, a rule exception, a domain change), leave it open. The runner escalates with a problem report instead of you guessing.
   - Keep a short note of what you changed for each item in each iteration; you need it if the gate escalates.
4. **Exit 3 - escalate.** Stop resolving. Open the escalation note named in the output
   (`<FEATURE_DIR>/gates/escalation-implement-b.md`) and replace every `TODO(agent)` with what you attempted
   for that item in each iteration, the blocker, and the decision needed (fix the artefact, an RFI to the BA, or a
   waiver in the decision ledger). Report `archiGuard: ESCALATED - <n> item(s) could not be resolved` with each
   item and the note's path. **End the calling command here**: it is not complete.
5. **Exit 2 - cannot evaluate.** Show the message to the user and end the calling command (fail-closed, no repair).

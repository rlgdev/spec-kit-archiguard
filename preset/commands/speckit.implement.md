---
description: Execute the implementation plan by processing and executing all tasks defined in tasks.md, with archiGuard's entry pin check and the fitness functions at exit.
strategy: wrap
---
> **archiGuard is part of this command.** Besides the steps below, this command has two mandatory
> archiGuard steps, described at the end of this document:
>
> - **(A) Entry gates**: run them right after the prerequisites check (step 1 of the Outline), before you touch any code.
> - **(B) Exit gates**: run them after the Completion validation (step 9 of the Outline), and before the Mandatory Post-Execution Hooks and the Completion Report.
>
> The command is complete only when step B passes. If step A or B escalates or cannot evaluate, the command
> ends with that report instead of the Completion Report.

{CORE_TEMPLATE}

## archiGuard (A): entry gates (mandatory, right after the prerequisites check (step 1 of the Outline), before you touch any code)

Run the archiGuard runner from the repository root. Use the variant that matches the project's script type (`script` in `.specify/init-options.json`), and pass the FEATURE_DIR from Setup:

- `sh`: `bash .specify/extensions/archiguard/scripts/bash/archiguard.sh run implement a --via inline --feature-dir <FEATURE_DIR>`
- `ps`: `.specify/extensions/archiguard/scripts/powershell/archiguard.ps1 run implement a --via inline --feature-dir <FEATURE_DIR>`
- `py`: `python .specify/extensions/archiguard/scripts/python/archiguard.py run implement a --via inline --feature-dir <FEATURE_DIR>`

What to do with the result:

- **It prints `skipped`.** archiGuard runs through hooks in this project. Continue normally and skip step B.
- **Exit 0.** The contract is **binding** for this command: the rules in `<FEATURE_DIR>/gates/applicable-rules.json`
  (printed with their `SKILL.md` where step A lists them) and the scope inventory, if printed. Read the `SKILL.md` of
  every applicable rule before you work, and keep the contract in front of you.
- **Exit 1.** The listed findings are part of the contract. Continue; step B verifies them.
- **Exit 3.** A check no agent may repair is red. Open the escalation note named in the output, replace every
  `TODO(agent)` with what you found and the decision needed, report `archiGuard: ESCALATED` with the items and the
  note's path, and **end the command here**.
- **Exit 2.** archiGuard cannot evaluate (rulebook, lock, domain map or handover record missing or invalid). Show
  the message and **end the command here**: the gates fail closed.

## archiGuard (B): exit gates (mandatory, before the Mandatory Post-Execution Hooks and the Completion Report)

The script decides; you resolve. The runner counts the iterations itself; never pass an iteration number.
Exit codes: **0** pass, **1** resolve, **3** escalate, **2** cannot evaluate.

1. **Check.** Run the same runner for step `b`:

- `sh`: `bash .specify/extensions/archiguard/scripts/bash/archiguard.sh run implement b --via inline --feature-dir <FEATURE_DIR>`
- `ps`: `.specify/extensions/archiguard/scripts/powershell/archiguard.ps1 run implement b --via inline --feature-dir <FEATURE_DIR>`
- `py`: `python .specify/extensions/archiguard/scripts/python/archiguard.py run implement b --via inline --feature-dir <FEATURE_DIR>`

   Keep the exit code and the full output.
2. **Exit 0: pass.** Add one line to your Completion Report, for example `archiGuard: PASS after N repair iteration(s)`,
   plus the advisory findings and waivers as printed. Continue with the Mandatory Post-Execution Hooks and the Completion Report.
3. **Exit 1: resolve.** The output lists every open item under `RESOLVE`, with where it is, the fix hint and the rule
   or specification text to work from. Resolve **all** of them, then go back to step 1.
   - **Fitness** (A4.4): fix the code that breaks a rule (layering, context boundaries, contracts, forbidden
     constructs). Never change `plan.md`, the contracts or the specification in this command: a fix that needs a design
     change goes back to Design for a new sign-off - leave it open so the runner escalates.
   - **Traceability** (A4.6): commit messages name their task and requirement ids; test files carry the ids they verify.
   - **Scope** (scope gate): finish every task that carries an in-scope requirement.
   - Never edit `spec.md`, `handover.yml`, `ba/`, the standards (`.specify/standards/`), `standards.lock.yml`, the decision ledger, `archiguard-config.yml` or a verdict file under `<FEATURE_DIR>/gates/` to make a gate pass (the escalation note is the only file there you complete).
   - Never run `archiguard signoff`, `reopen`, `resolve`, `ledger add` or `ledger revoke`, and never write a ledger entry yourself: sign-offs, approvals, waivers and the standards lock are decisions of people (the design authority, the lead architect). The edit guard blocks these commands for agents.
   - Never mark a rule `not applicable` or `deviation`, and never defer a scope item, just to make the gate pass: `not applicable` needs a reason from the allowed list, `deviation` needs an approved, unexpired ADR in the decision ledger, a deferral is a scope change: it needs a reason the user approved (and, when the project requires it, the RFI or decision-ledger entry that approved it).
   - If an item can only be resolved with information or a decision that only a person can give (a specification change, a rule exception, a domain change), leave it open. The runner escalates with a problem report instead of you guessing.
   - Keep a short note of what you changed for each item in each iteration; you need it if the gate escalates.
4. **Exit 3: escalate.** Stop resolving. Open the escalation note named in the output
   (`<FEATURE_DIR>/gates/escalation-implement-b.md`) and replace every `TODO(agent)` with what you attempted
   for that item in each iteration, the blocker, and the decision needed (fix the artefact, an RFI to the BA, or a
   waiver in the decision ledger). Report `archiGuard: ESCALATED - <n> item(s) could not be resolved` with each item and
   the note's path. **The command ends here**: do not run the post-execution hooks and do not write the Completion Report.
5. **Exit 2: cannot evaluate.** Show the message and end the command here (fail-closed, no repair).

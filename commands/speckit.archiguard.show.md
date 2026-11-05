---
description: "archiGuard: show the setup in force and every skill of the rulebook it binds, without changing anything"
scripts:
  sh: bash scripts/bash/archiguard.sh show
  ps: scripts/powershell/archiguard.ps1 show
  py: scripts/python/archiguard.py show
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Show how archiGuard is set up in this project, read-only: integration, mode, the gates plugged into each command
and their budgets, the hooks in `.specify/extensions.yml`, the policy files (rulebook, lock, domain map, ledger, edit
guard), and the **skills**: every skill of the rulebook that has a rule in the standards lock, with its `SKILL.md`
and its rules, the skills the lock leaves out, the excluded rules, and whether the lock still equals the rulebook.

## Procedure

1. Run `{SCRIPT}` from the repository root. Append `--verbose` if the user wants every rule's text and checks,
   `--json` if they want the data.
2. Show the output as is. Do not change any file: this command only reads.
3. If the output names something to do, quote it and the command it gives, and leave it to the user:
   - hooks that differ from the config: `archiguard configure` applies them (`/speckit.archiguard.configure`);
   - no lock, a `STALE` lock or `rulebook drift`: `archiguard resolve` is reserved for people - the change of the
     lock must be reviewed and committed;
   - a `SKILL.md` marked `MISSING`: the standards checkout is incomplete - check out the pinned tag.

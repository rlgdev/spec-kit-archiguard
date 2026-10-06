---
description: "archiGuard: apply archiguard-config.yml (inline or hooks, budgets, plugged gates) and show what is in force"
scripts:
  sh: bash scripts/bash/archiguard.sh configure
  ps: scripts/powershell/archiguard.ps1 configure
  py: scripts/python/archiguard.py configure
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Apply `.specify/extensions/archiguard/archiguard-config.yml` to Spec Kit's hook registry and show the settings in
force: integration, the gates plugged into each command, the iteration budgets, the policy (rulebook, lock, domain
map, ledger) and the scope gate.

## Procedure

1. If the user input asks for a change (for example `use hooks`, `budget 2 for plan`, `A0.4 enforce`), edit
   `archiguard-config.yml` accordingly first. Budgets cannot exceed the ceiling the command prints; a gate's mode
   can only be lowered below the global mode, never raised above it. Tell the user that the change must go through
   a pull request, because CI reads only the committed file.
2. Run `{SCRIPT}` from the repository root and show its output.
3. If the output reports a missing or stale lock, suggest `archiguard resolve`; if it reports the scopeGuard preset,
   suggest removing it (`specify preset remove scopeguard-templates`).

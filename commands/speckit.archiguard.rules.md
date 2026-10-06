---
description: "archiGuard: the architecture rules that apply to the feature and the contract the plan must meet"
scripts:
  sh: bash scripts/bash/archiguard.sh rules
  ps: scripts/powershell/archiguard.ps1 rules
  py: scripts/python/archiguard.py rules
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Show which architecture rules apply to the active feature (from the pinned standards lock, filtered by the stack and
the feature's home context) and what the plan and the tasks must contain for them.

## Procedure

1. Run `{SCRIPT}` from the repository root (append `--feature-dir <dir>` if the user input names one).
2. Present the rule list and the contract. Read the `SKILL.md` of a rule before you design anything it covers.
3. Exit 2 means the standards are not set up (no lock, stale lock, no rulebook): show the message and stop.

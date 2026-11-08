---
description: "archiGuard loop feedback to the domain master design: what the feature did that the domain map does not describe (evidence, never a gate)"
scripts:
  sh: bash scripts/bash/archiguard.sh feedback --save
  ps: scripts/powershell/archiguard.ps1 feedback --save
  py: scripts/python/archiguard.py feedback --save
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Show the loop feedback of the feature: what it did that the domain master design (the domain map) does not
describe - code no context maps, a new build unit (a new service?), a deployment topology the map does not declare,
changes in another context's code, dependencies the map does not allow, terms outside the glossary and gaps in the
map - each with a short suggestion for the next iteration. The command writes
`<FEATURE_DIR>/gates/loop-feedback.json` and `<FEATURE_DIR>/gates/loop-feedback.md`. It is evidence, never a gate:
it always exits 0. archiGuard also computes it by itself at the end of `/speckit.implement` step B, at the handover
4 -> 5 and with the compliance report.

## Procedure

1. Run `{SCRIPT}` from the repository root (append `--feature-dir <dir>` if the user input names one).
2. Report the topology answer (`existing`, `new` or `mixed`: did the feature extend an existing unit or create a new
   one), the number of items by impact, and the path of the Markdown file. List the high-impact items with their
   suggestion as printed.
3. **Do not act on the items.** They are for the lead architect, the domain owners and the next iteration (a new
   domain map version, a refactoring before a waiver expires, a glossary term); a person triages them. Never edit the
   two files, the domain map, the ledger or the code because of the feedback.

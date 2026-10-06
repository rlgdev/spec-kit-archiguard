---
description: "archiGuard architecture compliance report for the feature (verdicts, waivers, sign-off, test loop)"
scripts:
  sh: bash scripts/bash/archiguard.sh report --save
  ps: scripts/powershell/archiguard.ps1 report --save
  py: scripts/python/archiguard.py report --save
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Produce the architecture compliance report from the verdict files of the feature and save it in the feature
directory as `<FEATURE_DIR>/gates/architecture-compliance.md` (the evidence for the Epic and the pull request).

## Procedure

1. Run `{SCRIPT}` from the repository root (append `--feature-dir <dir>` if the user input names one).
2. Show the report's overall status, the failing checks and the waivers with their expiry, and give the path of the
   saved report. Do not edit the report or the verdict files.

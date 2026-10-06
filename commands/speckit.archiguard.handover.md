---
description: "archiGuard handover 4->5: entry checks H1-H6 and the test-handover manifest for the deterministic test loop"
scripts:
  sh: bash scripts/bash/archiguard.sh handover
  ps: scripts/powershell/archiguard.ps1 handover
  py: scripts/python/archiguard.py handover
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Decide whether the code may enter the deterministic test loop. The handover writes the manifest
`<FEATURE_DIR>/gates/handover-4-5.json` in the feature directory (feature, commit, hashes, pins, task status,
requirement -> tests map, stack and test command, verdicts, waivers) and runs the entry checks: H1 tasks complete, H2 converged, H3 fitness green, H4 test
inventory, H5 builds, H6 pins intact.

Exit codes: **0** ready for the test loop, **1** back to implement (not a test-loop iteration), **3** a pin moved
after the sign-off (needs a person), **2** cannot evaluate.

## Procedure

1. Run `{SCRIPT}` from the repository root (append `--feature-dir <dir>` if the user input names one).
2. **Exit 0.** Report `archiGuard: handover 4->5 ready` and the manifest path.
3. **Exit 1.** Go back to implement and fix the listed entry checks: finish open tasks and the Convergence phase,
   repair the fitness findings, write the missing tests tagged with their ids, make the build green. Then run this
   command again.
4. **Exit 3 / 2.** Report the message and stop: a person decides (re-open Design and re-sign, or fix the setup).

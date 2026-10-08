---
description: Perform a non-destructive cross-artifact consistency and quality analysis across spec.md, plan.md, and tasks.md after task generation, and save the report as evidence for archiGuard's A3.6 gate.
strategy: wrap
---

{CORE_TEMPLATE}

## archiGuard: save the analysis report (A3.6)

This is the one exception to the read-only rule above: after you produced the Specification Analysis Report, write
it **verbatim** (the findings table with its Severity column and the metrics, including `Critical Issues Count`) to
`<FEATURE_DIR>/gates/analyze-report.md`, creating the `gates/` folder if needed. The report file is evidence for the
design authority, not a design artifact; do not change any other file.

Then run archiGuard's A3.6 check from the repository root (the variant that matches the project's script type):

- `sh`: `bash .specify/extensions/archiguard/scripts/bash/archiguard.sh check A3 A3.6 --feature-dir <FEATURE_DIR>`
- `ps`: `.specify/extensions/archiguard/scripts/powershell/archiguard.ps1 check A3 A3.6 --feature-dir <FEATURE_DIR>`
- `py`: `python .specify/extensions/archiguard/scripts/python/archiguard.py check A3 A3.6 --feature-dir <FEATURE_DIR>`

If the checker is not there (the shell finds no such file, for example exit `127`), archiGuard is not installed here:
report `archiGuard not installed - skipped (remove the preset: specify preset remove archiguard-templates)` and
skip this section (the report file is for archiGuard only).

Report its result in one line. Exit 1 means CRITICAL findings remain: the design authority will not sign the plan
until they are resolved (fix spec, plan or tasks and run this command again).

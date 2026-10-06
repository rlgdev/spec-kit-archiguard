---
description: "archiGuard step A of /speckit.tasks (integration: hooks): the step A gates of /speckit.tasks"
scripts:
  sh: bash scripts/bash/archiguard.sh run tasks a --via hook
  ps: scripts/powershell/archiguard.ps1 run tasks a --via hook
  py: scripts/python/archiguard.py run tasks a --via hook
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Run archiGuard's step A gates for `/speckit.tasks` before the command does its work. This command is the
`before_tasks` hook when `integration: hooks` is configured; with `integration: inline` the same step runs inside
`/speckit.tasks` and this command prints `skipped`.

Exit codes: **0** pass (or skipped), **1** findings that are part of the contract, **3** stop (escalated), **2** cannot evaluate.

## Procedure

1. From the repository root run `{SCRIPT}`. Append `--feature-dir <dir>` if the user input names a feature directory.
   Keep the exit code and the full output.
2. **Exit 0.** If the output says `skipped`, say nothing more and let the calling command continue. Otherwise the
   contract is **binding** for `/speckit.tasks`: the rules in `<FEATURE_DIR>/gates/applicable-rules.json` (printed where the step lists them;
   `<FEATURE_DIR>` is the feature directory on the output's first line) and the scope inventory, if printed. Read the
   `SKILL.md` of every applicable rule before you work, and keep the contract in front of you.
3. **Exit 1.** The listed findings are part of the contract for this command. Continue; step B verifies them.
4. **Exit 3 - stop.** A check that no agent may repair is red (for example the domain map pin, the home context or
   the design authority sign-off). Open the escalation note named in the output, replace every `TODO(agent)` with
   what you found and the decision needed, report `archiGuard: ESCALATED` with the items and the note's path to the
   user, and **end the calling command here**.
5. **Exit 2 - cannot evaluate.** Show the message to the user and **end the calling command**: the gates fail
   closed until the setup (rulebook, lock, domain map, handover record) is fixed.

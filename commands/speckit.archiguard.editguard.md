---
description: "(agent event, not for direct use) archiGuard A4.2 edit guard for PreToolUse / PostToolUse"
scripts:
  py: scripts/python/archiguard.py edit-guard
---

## Goal

This command is wired to the agent's `pre_tool_use` and `post_tool_use` events by Spec Kit (`events:` in
`extension.yml`). The agent's tool payload arrives on stdin; the script exits 2 with the reason on stderr when an
edit touches a read-only artefact (blocked on PreToolUse) or breaks an edit-level architecture rule (reported back
on PostToolUse). It is a convenience: the workflow shell gate and the CI required check are the guarantee.

Do not run this command by hand.

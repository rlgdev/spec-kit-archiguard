# Plug-in contract

archiGuard's runner knows a gate only through this contract. Its own gates (A0, A3, A4, H) follow it
internally, scopeGuard is plugged in through an adapter for its CLI, and any other gate (security,
data protection, a code-graph query) is plugged in by registering it. The binding to the host (the wrap
of the Spec Kit commands, the hooks, a workflow shell step, CI) is the runner's job, so a gate never
needs to know which of them called it.

## 1. Manifest

A manifest declares the gate's checks. It lives in a file (`gates.<id>.manifest`) or inline in the
registration (`gates.<id>.checks`):

```yaml
id: SEC                       # the gate id used in the pipeline
name: transport security
version: 1.2.0
protocol: archiguard          # archiguard (this contract) | scopeguard (the scopeGuard adapter)
checks:
  SEC.1: { name: TLS settings, target: code, repairable: true }
  SEC.2: { name: security headers, target: code }
```

- `target`: `spec`, `plan`, `contract`, `tasks`, `edit`, `code` or `tests`, i.e. what the check reads.
  It decides where the check may be plugged in and is recorded in the verdict.
- `repairable` (default `true`): `false` means no agent may repair a red result (a pin, a policy
  decision). The runner escalates at once instead of looping.

## 2. Registration

```yaml
# archiguard-config.yml
gates:
  SEC:
    command: tools/secgate.py          # relative to the project root, or to .specify/extensions/<extension>/
    extension: null                    # name an installed Spec Kit extension to resolve command inside it
    version: ">=1.0,<2"                # refused (exit 2) when the installed version does not satisfy it
    sha256: null                       # optional pin of the command file: sha256 with LF line endings, quoted
    config: tools/secgate.yml          # passed as --config
    timeout: 600
    checks:
      SEC.1: { name: TLS settings, target: code }
```

The installed version is read from the extension's `extension.yml` when `extension` is set, otherwise
from `<command> --version` (the last word of the output).

## 3. Invocation

```text
<command> <check...> [--feature-dir <dir>] [--iteration <n>] [--config <file>] --json
```

A `.py` command runs with the same Python as archiGuard; anything else is executed directly. The working
directory is the project root. The runner calls the gate once per pipeline entry with all the entry's
checks, on every iteration of the step.

## 4. Exit codes

| Code | Meaning | The runner |
|------|---------|------------|
| `0` | every check passed (or was waived) | continues |
| `1` | findings an agent can repair | lists them under `RESOLVE`, counts the iteration |
| `2` | cannot evaluate (setup, missing input) | stops the step, fail-closed, no repair |
| `3` | escalated by the gate itself | stops the step, writes the escalation note |

The runner trusts the verdicts on stdout for `0`, `1` and `3`, and the exit code for `2`.

## 5. Verdicts on stdout

```json
{"verdicts": [
  {"check": "SEC.1", "status": "violation",
   "findings": [{"rule": "SEC-007", "message": "TLS 1.0 enabled", "severity": "blocking",
                 "where": "src/main/resources/application.yml:12", "fix_hint": "require TLS 1.2+",
                 "excerpt": "the rule or specification text the agent should work from"}],
   "waived": [{"rule": "SEC-009", "waiver": "WVR-0012", "expires": "2027-03-31"}],
   "rules_skipped": [{"rule": "SEC-011", "reason": "no HTTP server in this repository"}]},
  {"check": "SEC.2", "status": "pass", "findings": []},
  {"check": "SEC.3", "status": "error", "error": "the scanner is not installed"}
]}
```

A bare list of verdicts, or a single verdict object, is accepted too. `severity` is `blocking`
(default) or `advisory`. A check without a verdict in the output is an error (exit `2`).

## 6. What the runner adds

For every check the runner writes `specs/<feature>/gates/<gate>/<check>.json`:

```json
{"gate": "SEC", "check": "SEC.1", "guardrail": "SEC.1-tls-settings", "guardrail_version": "0.1.0",
 "subject": {"feature": "specs/001-place-order", "commit": "…", "stage": "code"},
 "pins": {"spec": "3#…", "domain_map": "1.4.0", "rulebook": "acme-standards@v2026.10.1", "lock": "…"},
 "status": "violation", "mode": "enforce", "findings": […], "waived": […], "rules_skipped": […],
 "iteration": 1, "max_iterations": 3}
```

and one combined verdict per step (`gates/<command>-<a|b|verify>.json`) with the hashes of the
artefacts, the iteration history and the escalation, if any. `mode: report` turns blocking findings into
advisory ones in the verdict and never blocks.

## 7. The repair input

Under `RESOLVE` the runner prints, for every blocking finding: the check, the rule, the message, `where`,
the `fix_hint` and the `excerpt`. That is all the agent gets, so a gate should say exactly what to change
and where, and quote the rule or specification text the change must satisfy. A gate never asks the agent
to edit the specification, the standards, the ledger or the verdicts; the runner's commands forbid it and
the edit guard blocks it.

## The scopeGuard adapter

`protocol: scopeguard` calls `scopeguard.py <inventory|plan|tasks|implement> --root <root>
--feature-dir <dir> [--config <file>] --json` and maps each `violation` item to a finding (with the
spec excerpt and the fix row), each deferred item to a waiver, and scopeGuard's own findings by level.
`inventory` returns the scope contract as text for step A. archiGuard accepts scopeGuard
`>=0.3.0,<0.5` by default and switches scopeGuard's own hooks off when the scope gate is in the
pipeline, so every scope check runs once, inside archiGuard's budget.

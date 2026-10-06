# Security policy

archiGuard is part of the Guardians family for GitHub Spec Kit (scopeGuard, archiGuard, auditGuard and the
Guardians bundle). All four follow this policy.

## Supported versions

Only the latest release of each repository receives fixes. The Guardians bundle pins the versions that were
tested together; a fix in one tool is published as a new release of that tool and a new bundle version.

## Reporting a vulnerability

Report privately through GitHub's private vulnerability reporting for this repository:
https://github.com/rlgdev/spec-kit-archiguard/security/advisories/new

Do not open a public issue for a security problem. Include the version (`extension.yml` of the installed
extension, or the release tag), the host (operating system, Python, Spec Kit version), what you observed
and how to reproduce it. You will get an acknowledgement, a fix or a mitigation, and credit in the release
notes if you want it.

## What to look at

The tools run locally and in CI, with the Python standard library and no network access of their own. The
parts worth a second look are:

- the launchers (`scripts/bash`, `scripts/powershell`) and the interpreter search;
- everything that runs a configured command (plug-in gates, collectors, `tests.command`), which executes
  what the committed configuration names;
- hash chains, seals and evidence (auditGuard), the decision ledger and the standards lock (archiGuard):
  tampering must be detected, never silently accepted;
- the release archives: `tools/build.py` builds them reproducibly and `SHA256SUMS` is attached to every
  release, so a corporate catalog can pin them by hash.

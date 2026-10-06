# Contributing to archiGuard

archiGuard is one of the Guardians for GitHub Spec Kit. The four repositories (scopeGuard, archiGuard, auditGuard,
Guardians) share one layout, one toolchain and one release convention, so a change here usually looks the same
as in the siblings. Bugs and ideas go to the issues of this repository; the family-wide view (pins, the bundle,
the getting-started guide) lives in [spec-kit-guardians](https://github.com/rlgdev/spec-kit-guardians).

## Development loop

Python 3.9+ (the engine is standard library only), git, and for the end-to-end check a `specify` on PATH.

```bash
python -m pip install pytest pyflakes
python -m pytest -q                 # unit and integration tests (SCOPEGUARD_SRC=<scopeGuard checkout> for the integration test)
python -m pyflakes scripts/python tools tests
shellcheck scripts/bash/*.sh        # the bash launcher (and tools/*.sh where present)
python tools/build.py --check       # versions, manifests and catalogs agree; referenced files exist
python tools/build.py               # the release archives in dist/ (reproducible; SHA256SUMS)
```

CI runs the same on ubuntu, windows and macos with Python 3.9 and 3.13, installs the archive into a fresh Spec Kit
project (latest and the oldest supported `specify-cli`) and self-tests the GitHub Action. A pull request is
ready when all of it is green.

## Conventions

- **Layout.** Extension files at the repository root (`extension.yml`, `config-template.yml`, `commands/`,
  `scripts/`); everything else (`tests/`, `tools/`, `docs/`, `examples/`, `catalog/`, `action.yml`) is
  listed in `.extensionignore` so a `--dev` install does not carry it. The release archive is an allow-list in
  `tools/build.py`.
- **Launchers.** `scripts/bash/<id>.sh`, `scripts/powershell/<id>.ps1` and `scripts/python/<id>.py` stay
  functionally identical across the family: `<ID>_PYTHON`, then `python3` / `python` on PATH (the Windows
  Store stub is rejected by a marker check), then specify-cli's Python under `uv tool dir`, then `uv run`.
- **Line endings.** LF everywhere (`.gitattributes`); files the tools write are LF and UTF-8.
- **Configuration.** Unknown keys are errors. A new key gets a commented line in `config-template.yml`, a
  default in the code, a test and a line in the README.
- **Output.** Exit codes `0` ok, `1` findings, `2` cannot run (fail-closed), `3` escalated / reserved for people
  (where the tool defines it). Every finding names the file and the fix.
- **Changelog.** [Keep a Changelog](https://keepachangelog.com/en/1.1.0/): add your change under
  `## [Unreleased]`; the release moves it under the version.

## Releasing

1. Bump the version in `extension.yml`, `preset/preset.yml`, `workflows/archiguard-sdd/workflow.yml`, `scripts/python/archiguard_core/__init__.py` and `catalog/*.json` (`tools/build.py --check` fails while they disagree).
2. Move the `[Unreleased]` entries of `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD`; the release workflow
   uses that section as the release notes.
3. Update the `releases/download/vX.Y.Z/...` URLs in the README.
4. Merge to `main` with CI green, then push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`. The release
   workflow runs the tests, builds the archives and attaches `archiguard.zip`, `archiguard-preset.zip`, `archiguard-sdd.yml` and `SHA256SUMS` to the GitHub release.
5. The Guardians bundle pins exact versions: open a pull request in
   [spec-kit-guardians](https://github.com/rlgdev/spec-kit-guardians) that bumps the pin (bundle, catalogs,
   `action.yml`, the CI refs), runs its e2e against the new tag, and releases a new bundle version.

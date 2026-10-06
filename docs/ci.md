# CI: the required check

`archiguard ci` is the guarantee behind the agent-facing gates. It runs on the final commit of a
pull request and:

1. re-resolves the standards from the rulebook at the pinned tag and fails on any drift from the
   committed `standards.lock.yml`;
2. verifies the decision ledger's hash chain;
3. runs every gate plugged into `/speckit.plan` and `/speckit.tasks` once for every feature under
   `specs/` that has the artefact, and the `/speckit.implement` gates for every signed feature
   (`--implement`: for every feature).

It never loops, never repairs and never writes evidence. The test command and the requirement trace
are a separate required check: run `archiguard test` (it runs `tests.command`, reads the JUnit reports
and fails when an in-scope id has no passing test) in the same job or in your build job. Local overrides (`local-config.yml`,
`ARCHIGUARD_*`, `ARCHIGUARD_TODAY`) are ignored: CI reads only the committed config. Exit `0` pass,
`1` fail, `2` cannot evaluate.

```bash
python .specify/extensions/archiguard/scripts/python/archiguard.py ci \
  --junit reports/archiguard.xml --out reports/archiguard.md
```

The job needs the full history of the base branch for A4.6 traceability (`git.base`, default `main`),
the standards checkout (submodule) at the pinned tag, and the scopeGuard extension installed in the
project when the scope gate is in the pipeline. Commit `.specify/` with the project; it holds the
installed extensions, the config, the lock and the ledger.

## GitHub Actions

```yaml
name: architecture
on: [pull_request]
jobs:
  archiguard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0          # A4.6 reads the commits since the base branch
          submodules: true        # the standards repository at the pinned tag
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - uses: rlgdev/spec-kit-archiguard@v0.1.0
        with:
          features: all           # or specs/001-my-feature
          junit: reports/archiguard.xml
      # the test trace of a feature, as a required check (needs the build toolchain)
      - run: python .specify/extensions/archiguard/scripts/python/archiguard.py test --feature-dir specs/001-my-feature
```

By default (`engine: installed`) the action runs the archiGuard the project installed under
`.specify/extensions/archiguard`, so CI runs the same version as the developers, and falls back to its
own copy when the project has none; `engine: action` always uses the action's own copy.

## Bitbucket Pipelines

```yaml
image: python:3.12

definitions:
  steps:
    - step: &archiguard
        name: archiGuard required check
        clone:
          depth: full             # A4.6 reads the commits since the base branch
        script:
          - git submodule update --init --recursive
          - git fetch origin main:main || true
          - mkdir -p test-reports
          - python .specify/extensions/archiguard/scripts/python/archiguard.py ci --junit test-reports/archiguard.xml
          # the test trace of a feature (needs the build toolchain in the image):
          # - python .specify/extensions/archiguard/scripts/python/archiguard.py test --feature-dir specs/001-my-feature

pipelines:
  pull-requests:
    '**':
      - step: *archiguard
```

Bitbucket sets `CI=true`, and it picks up JUnit reports from `test-reports/` automatically. Make the step
a required check (merge check "minimum successful builds") on the protected branch.

## Other CI systems

Any runner with Python 3.9+ and git works: check out with history and submodules, set `CI=true` (most
systems do), and run the command above. The JUnit report has one test case per gate check and feature.

# archiGuard Templates (preset)

Pairs with the [archiGuard extension](https://github.com/rlgdev/spec-kit-archiguard).

- **Wraps `/speckit.plan`, `/speckit.tasks` and `/speckit.implement`** (strategy `wrap`) with two mandatory
  steps: the entry gates (step A) right after Setup, and the exit gates (step B) before the post-execution hooks and
  the Completion Report. Step B resolves findings in a bounded loop and escalates with a problem report when it
  cannot. Used when `integration: inline` (the default) is set in `archiguard-config.yml`; with `integration: hooks`
  the wrapped steps print `skipped` and the archiGuard hook commands do the work.
- **Wraps `/speckit.analyze`** to save its report as `gates/analyze-report.md` and run the A3.6 check.
- **Appends sections** (strategy `append`):
  - `plan-template`: Integration Points (A0.5), Architecture Conformance (A3.3), Scope Coverage (scope gate);
  - `tasks-template`: the Fitness phase (A3.5 / A4.4) and the Scope Coverage mapping.

This is the only preset that wraps these commands: do not install the scopeGuard preset next to it (Spec Kit would
compose both wraps). archiGuard runs the scope gate on the scopeGuard engine itself.

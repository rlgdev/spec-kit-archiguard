# Examples

## orders

`specs/001-place-order` is a feature of the `orders` context, handed over from the BA specification tool
(`handover.yml`: UC-001, AC-001/002, BR-001/002, D-001, domain map 1.4.0). The project is bound to the
example standards in `.specify/standards` (rulebook `acme-standards@v2026.10.1`, profile `java-service`,
domain map 1.4.0), with a resolved lock and a decision ledger in `.specify/archiguard/`.

The config ([`.specify/extensions/archiguard/archiguard-config.yml`](orders/.specify/extensions/archiguard/archiguard-config.yml))
leaves out the scope gate (it needs the scopeGuard extension installed) and A4.6 (it needs a git
history), so the example runs on its own. Three things are wrong on purpose:

- `plan.md` has no Architecture Conformance row for **ARCH-201** (layering): the A3.3 check-plan finds it.
- `Order.java` (domain layer) imports `OrderController` (api layer): **ARCH-201**, found by A4.4.
- `OrderController.java` imports `com.acme.payments.internal.PaymentGateway`, which the payments context
  does not publish: **ARCH-301**, found by A4.4 and by the edit guard.

`data-model.md` also names a `Shipment`, a term the orders glossary does not know: A0.4 reports it in
report mode, without blocking. With the scope gate plugged in (scopeGuard installed and
`scope-config-template.yml` in place), plan.md's Scope Coverage table misses **BR-002** on purpose.

```bash
cd examples/orders
A=../../scripts/bash/archiguard.sh
bash $A run plan a       # PASS: domain guard, the applicable rules and the contract the plan must meet
bash $A run plan b       # exit 1: ARCH-201 missing from Architecture Conformance (iteration 0 of 3)
bash $A run plan b       # exit 3: the same findings again - escalated, see gates/escalation-plan-b.md
bash $A run tasks b      # PASS
bash $A run implement a  # exit 3: no design sign-off yet
bash $A check A4 A4.4    # exit 1: the ARCH-201 and ARCH-301 violations in the code
bash $A rules            # what applies to the feature, and why
bash $A report           # the compliance report
```

The gates write their evidence into `specs/001-place-order/gates/` (ignored by git here), and A4.4 ticks
the `[FITNESS]` tasks in `tasks.md` whose checks pass. Delete the `gates/` folder and restore `tasks.md`
(`git checkout -- specs`) to start again.

To walk through the whole flow, copy the example into a git repository, fix the plan row, add the
analyze report (`gates/analyze-report.md`), sign the design (`archiguard signoff --by "<name>"`), then
fix the two imports and run `run implement b` and `handover`.

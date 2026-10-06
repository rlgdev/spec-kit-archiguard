## Integration Points

<!--
  ACTION REQUIRED (archiGuard A0.5): one row per integration of this feature with another bounded context of the
  domain map - the target context and the relation type the map allows between the home context and it
  (customer-supplier, conformist, anticorruption-layer, open-host-service, published-language, shared-kernel,
  partnership). When the feature has no integration, keep a single row: | none | - | - | - |
-->

| Integration point | Target context | Relation | Via |
|-------------------|----------------|----------|-----|

## Architecture Conformance

<!--
  ACTION REQUIRED (archiGuard A3.3): one row for EVERY architecture rule archiGuard listed at the start of this
  command (the rules that target the plan or a contract). Read each rule's SKILL.md first.

  Status:
    satisfied       -> Plan reference says where the plan meets the rule (section, contract, entity, decision)
    not applicable  -> ADR / reason holds a reason from the allowed list archiGuard printed
    deviation       -> ADR / reason holds the id of an approved, unexpired ADR in the decision ledger

  Declared checks of the rules run against plan.md, data-model.md and contracts/; a deviation is never a way to
  make a check pass.
-->

| Rule | Title | Status | Plan reference | ADR / reason |
|------|-------|--------|----------------|--------------|

## Scope Coverage

<!--
  ACTION REQUIRED (scope gate, scopeGuard engine): one row for EVERY user story (US1, US2, ...) and EVERY traced
  requirement ID defined in spec.md. No item may be left out, merged or renumbered.
    covered  -> Plan reference says where the plan handles it
    deferred -> ONLY when the user approved taking it out of scope (a scope change: cite the RFI or ledger entry); the Reason column is mandatory
-->

| ID | Title | Status | Plan reference | Reason (required if deferred) |
|----|-------|--------|----------------|-------------------------------|

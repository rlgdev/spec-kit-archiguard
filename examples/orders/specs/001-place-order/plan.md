# Implementation Plan: Place an order

**Branch**: `001-place-order` | **Spec**: [spec.md](spec.md)

## Technical Context

Java 21, Spring Boot 3, PostgreSQL.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] Test-first: every acceptance criterion has a test task (Principle I)
- [x] Contracts before code: contracts/orders.yaml (Principle II)

## Integration Points

| Integration point | Target context | Relation | Via |
|-------------------|----------------|----------|-----|
| Request payment of the order total | payments | customer-supplier | api:payments/payments.yaml |

## Architecture Conformance

| Rule | Title | Status | Plan reference | ADR / reason |
|------|-------|--------|----------------|--------------|
| ARCH-101 | HTTP APIs are published as OpenAPI 3 contracts | satisfied | contracts/orders.yaml | |
| ARCH-501 | Every aggregate is written only by its owning context | satisfied | data-model.md Order (owned by orders) | |
<!-- ARCH-201 (layering) is missing on purpose: the A3.3 check-plan finds it. -->

## Project Structure

src/main/java/com/acme/orders/{api,application,domain}

## Scope Coverage

| ID | Title | Status | Plan reference | Reason (required if deferred) |
|----|-------|--------|----------------|-------------------------------|
| US1 | Place an order (P1) | covered | contracts/orders.yaml POST /orders | |
| SC-001 | A customer places an order for the items in the basket | covered | contracts/orders.yaml POST /orders | |
| AC-001 | An order is created with one order line per item | covered | data-model.md Order, OrderLine | |
| AC-002 | The payments context receives a payment request | covered | Integration Points (payments) | |
| BR-001 | One order line per basket item | covered | data-model.md OrderLine | |
| D-001 | Order | covered | data-model.md Order | |
<!-- BR-002 (request the payment) is missing on purpose: the scope gate finds it when it is plugged in. -->

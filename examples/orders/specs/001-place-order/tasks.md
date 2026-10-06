# Tasks: Place an order

## Phase 1: Setup

- [x] T001 Create the module skeleton in src/main/java/com/acme/orders

## Phase 2: User Story 1 - Place an order (Priority: P1)

- [x] T002 [US1] Write the acceptance test for placing an order in src/test/java/com/acme/orders/PlaceOrderTest.java - Carries: AC-001, BR-001
- [x] T003 [US1] Write the test for the payment request in src/test/java/com/acme/orders/PlaceOrderTest.java - Carries: AC-002, BR-002
- [x] T004 [US1] Implement OrderController POST /orders and GET /orders/{orderId} - Carries: AC-001, BR-001
- [x] T005 [US1] Request the payment from the payments context - Carries: AC-002, BR-002

## Phase 3: Fitness

- [ ] T006 [FITNESS] Verify the OpenAPI contract is implemented - ARCH-101
- [ ] T007 [FITNESS] Verify the layering - ARCH-201
- [ ] T008 [FITNESS] Verify the context boundaries - ARCH-301
- [ ] T009 [FITNESS] Verify no credentials in code - ARCH-401

## Scope Coverage

| ID | Title | Status | Tasks | Reason (required if deferred) |
|----|-------|--------|-------|-------------------------------|
| SC-001 | A customer places an order for the items in the basket | covered | T002, T004 | |
| D-001 | Order | covered | T004 | |

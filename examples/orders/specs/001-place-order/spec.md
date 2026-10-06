# Feature Specification: Place an order

**Feature Branch**: `001-place-order`
**Source**: UC-001 @ v3 (formal handover from the BA specification tool)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Place an order (Priority: P1)

SC-001: a customer places an order for the items in the basket.

**Acceptance Scenarios**:

1. **AC-001**: **Given** a basket with items, **When** the customer places the order, **Then** an order is created with one order line per item.
2. **AC-002**: **Given** a placed order, **When** payment is requested, **Then** the payments context receives a payment request for the order total.

## Requirements *(mandatory)*

### Functional Requirements

- **BR-001**: The system shall create one order line per basket item.
- **BR-002**: The system shall request the payment of the order total from the payments context.

### Key Entities

- **D-001**: Order - order lines, total, status.

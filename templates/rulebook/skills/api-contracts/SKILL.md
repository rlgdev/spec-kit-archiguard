---
name: api-contracts
description: How services publish and evolve their HTTP APIs. Read before designing any endpoint.
---

# API contracts

- ARCH-101: every HTTP API is described by an OpenAPI 3 document in the feature's `contracts/`
  folder before it is implemented; the implementation follows the contract, never the reverse.
- ARCH-102: controllers depend on the application layer only, never on persistence classes.

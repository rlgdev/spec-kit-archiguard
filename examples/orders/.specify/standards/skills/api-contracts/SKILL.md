---
name: api-contracts
description: How services publish their HTTP APIs. Read before designing any endpoint.
---
# API contracts
Every HTTP API is described by an OpenAPI 3 document in the feature's `contracts/` folder before it is
implemented (ARCH-101). The implementation follows the contract, never the reverse.

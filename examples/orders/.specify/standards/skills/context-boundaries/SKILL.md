---
name: context-boundaries
description: How bounded contexts depend on each other in code. Read before calling another context.
---
# Context boundaries
Code of one bounded context may use another context only along a relation of the domain map, and only
through what that context publishes (ARCH-301). Everything else is internal.

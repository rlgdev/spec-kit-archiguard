---
name: data-ownership
description: Every aggregate has exactly one owning bounded context.
---
# Data ownership
An aggregate is written only by the context that owns it in the domain map (ARCH-501). Other contexts
keep read models fed by events or call the owner's API.

---
name: layering
description: Layered architecture inside a bounded context. Read before placing any class.
---
# Layering
api -> application -> domain; infrastructure implements ports of the application layer (ARCH-201).
The domain layer depends on nothing else.

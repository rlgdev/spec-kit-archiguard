Packs are rule sets a bounded context pulls in through the domain map (`contexts.<name>.packs`).
A pack file has the same shape as a profile: `pack: <name>`, `skills: [...]`, `rules: [...]`.
Rules that only come from a pack apply only to features whose home context lists the pack.

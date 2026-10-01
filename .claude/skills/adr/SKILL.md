---
name: adr
description: Create or supersede an Architecture Decision Record in docs/adr/. Use when making or recording a significant design choice (output pacing, session lifecycle, security, deployment, frontend/backend boundaries), or when the user says "write an ADR".
argument-hint: "<decision title>"
---

# Write an ADR

1. Read `docs/adr/README.md` (index) and skim ADRs related to the topic. If the new
   decision changes an accepted one, it must supersede it, not edit it.
2. Next number = highest existing `NNNN` + 1, zero-padded to 4. File:
   `docs/adr/NNNN-kebab-title.md`, copied from `docs/adr/0000-template.md`.
3. Fill Context, Decision, Alternatives considered, Consequences. State consequences
   concretely: which code or tests must keep behaving a certain way. Use today's date.
4. If superseding: set the old ADR's status to `superseded by [NNNN](file)`. That is the only
   edit allowed to an accepted ADR.
5. Add a row to the table in `docs/adr/README.md`.
6. Tell the user the number and one-line decision; ask for confirmation if the decision was
   inferred rather than stated by them. Mark it `proposed` until they confirm.

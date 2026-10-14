# Task Executable Allowlist Implementation Plan

> Use subagent-driven-development with backend implementation and independent final spec/quality review; root integrates the small settings UI change.

**Goal:** Preset Xorg exclusions and editable exact-path task monitoring allowlist.
**Architecture:** Agent filters task membership/authority while retaining native sampling and GPU metrics; global settings JSON holds exact paths; shared UI tags control edits the list.
**Tech Stack:** Python/FastAPI/SQLite, React/AntD, Pytest/Vitest/Playwright.

- [x] Backend failing tests then exact-path setting validation/matching, discovery/existing records/API exclusion and per-signal guards; run focused/full tests and Ruff.
- [x] Settings UI existing tags control, bilingual glossary/explanation, strict payload/empty-list component regression and browser save/cancel regression.
- [x] Independent specification and code quality review; Ubuntu/full frontend/browser verification.
- [x] Back up and deploy both trial entrances; actual Xorg unchanged and absent from tasks, metrics retained, other tasks unchanged; update contracts/test/deploy docs and commit.

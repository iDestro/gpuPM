# Manual Residual Cleanup Implementation Plan

> Use superpowers:subagent-driven-development task-by-task with spec and quality review.

**Goal:** Replace residual automatic execution with waiting reminders and administrator-confirmed termination.
**Architecture:** Existing confirmed process membership derives lifecycle; persisted timing and scoped operation tokens enforce manual-only cleanup. React uses the existing duration control and preview/operation dialog.
**Tech Stack:** Python/FastAPI/SQLite, React/AntD, Pytest/Vitest/Playwright.

- [x] Backend: add failing sequence/security/API tests; implement new defaults/strict schemas, finalization timing/state, active filters, disabled legacy cleanup, residual-only scoped preview/execute and demo parity. Files domain/settings.py, domain/schemas.py, agent/processes.py, agent/host.py, agent/demo.py, api/routes/tasks.py and corresponding tests. Run `.venv/bin/python -m pytest backend/tests -q` and Ruff; require green after observed failing regressions.
- [x] Backend spec review, then independent quality review; resolve concrete issues.
- [x] Frontend: add failing state/form/manual-preview tests; replace cleanup switch with reminder/wait controls, live task filter, list/detail notices and residual action, bilingual labels/terms; retain preview confirmation safety. Files pages.tsx, components.tsx only if required, messages/glossary and tests. Run `npm test` and `npm run test:e2e` in frontend; require real manual flow E2E.
- [x] Frontend spec and quality reviews; full Ubuntu backend validation. Verify failures, natural finish, clock boundaries and no implicit mutation.
- [x] Backup and deploy both trial services preserving old task policies apart from missing reminder defaults. Check native mutations remain false; native bilingual/mobile UI and API settings readback. Update API_CONTRACT, TEST_REPORT and TRIAL_DEPLOYMENT. Commit completed implementation.

# User task groups implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement and review this plan task-by-task.

**Goal:** Consolidate task-policy groups, explicit inheritance and persistent per-user custom policy without changing existing task execution or storage permissions.

**Architecture:** Reuse management_groups/managed_users and task_policies; store sparse overrides, resolve per-field sources and snapshot task policy at enrollment. Keep privileged agent validation authoritative and native groups unchanged.

**Tech Stack:** Existing FastAPI, SQLAlchemy/SQLite, pytest; React/Ant Design, React Query, Vitest and Playwright.

## Backend
- [x] Add regression tests in backend/tests/integration/test_user_task_groups.py and unit migration coverage: `assert group['effective_policy']['max_runtime_seconds'] is None` for explicit override, and switching user to default retains personal_policy but changes effective_policy.
- [x] Run `cd backend && uv run pytest tests/integration/test_user_task_groups.py -q` and confirm missing behavior.
- [x] Extend db/models.py and db/session.py with safe idempotent migration; schemas.py strict policy override validation; domain policy resolver; routes/management.py group and user mutations/audit/protection; context.py task snapshot handling; routes/tasks.py explicit edits preserve snapshot. Account creation/update callers must use unified policy semantics.
- [x] Run targeted tests then complete backend suite. Existing-task and native permission regressions must pass.

## Frontend
- [x] Add frontend/src/user-groups.test.tsx tests for inheritance versus explicit unlimited, assignment and custom-config preservation, built-in deletion disable, and error/cancel behavior. Run targeted Vitest to confirm missing behavior.
- [x] Add user-groups.tsx using existing EditDialog/RuntimeInput patterns. Replace BusinessGroups/BusinessUsers with unified component; integrate assignment in Accounts detail and creation. Update App navigation and legacy redirects, glossary/messages, task effective priority display and filters. No new dependency.
- [x] Update existing test callers/fixtures and E2E navigation. Run Vitest with --maxWorkers=1, build, and browser tests for English/Chinese, assignment, inheritance, deletion and narrow layout.

## Review and deployment
- [x] Review against spec, then independent quality review; resolve all material findings.
- [x] Back up trial services and databases; verify migration on copies, deploy to wzx-ubuntu with rollback; compare system accounts/groups and shared ACL before/after.
- [x] Read-only live health/policy/navigation verification; avoid altering real users' policy solely for testing. Append exact checks and limitations to TEST_REPORT.md and TRIAL_DEPLOYMENT.md.

Existing worktree has prior uncommitted product work: preserve it; do not reset, auto-commit unrelated changes or use a clean checkout missing these fixes.

执行完成：2026-10-16。完整测试与部署证据见 docs/TEST_REPORT.md、docs/TRIAL_DEPLOYMENT.md。未提交或重置既有工作区改动。

# Group management implementation plan

Goal: Separate task policy groups from native system groups and make membership convenient from either account or group detail.
Architecture: Keep existing native preview/execute guards. Add transactional task-group assignment with expected previous groups to reject stale dialogs. No native group or ACL synchronization for task policy changes.
Tech stack: Existing FastAPI/SQLAlchemy, React/Ant Design, pytest/Vitest/Playwright.

- [x] Add API tests for atomic bulk assignment, stale membership, protected account rejection, personal configuration retention and unchanged task snapshots.
- [x] Implement POST /groups/{id}/members with bounded strict UID and expected group list, validate all before transaction writes and audit each changed user.
- [x] Rename task UI to 任务策略组; expose /system-groups as 系统用户组, redirect old advanced path. Preserve native group protection and previews; explain shared internal group ownership and empty-group deletion risk.
- [x] Add searchable multi-user assignment and confirmed move to default inside group detail. Show source → target and new-tasks-only notice, preserve failed selections. Keep account assignment searchable.
- [x] Update translations, unit/browser fixtures and add membership interaction tests. Run backend suite, frontend suite, build and browser checks.
- [x] Deploy with existing backup/rehearsal/rollback script, verify health and native identity/ACL unchanged, record results.

Approved scope: preceding conversation. No new native group metadata/notes schema, no automatic migration of files or permissions, no ordinary-user self-service. Existing worktree changes preserved; no automatic commit.

Implementation notes: native group guards reused without relaxing protection. Sidebar grouping changed from positional indexes to route keys; tests assert all core navigation entries. Bulk assignment validates fresh native account eligibility and expected group inside the application lock, then writes all assignments and audit rows in one transaction. No new dependency or database migration.

Completed: backend 367 passed / 2 platform skips; frontend 117 cases covered with 42-case affected-file recheck; 17 distinct browser cases passed in isolated batches. Deployment and readonly native verification passed; see TEST_REPORT.md and TRIAL_DEPLOYMENT.md.

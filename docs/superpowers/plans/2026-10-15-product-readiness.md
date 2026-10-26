# Product readiness implementation plan

> Superseded quota scope: the user removed disk quotas on 2026-10-15. The maintenance-window gate is cancelled. See [quota removal completion](2026-10-15-remove-quotas.md) and [current acceptance](../../ACCEPTANCE_STATUS.md). Unchecked historical quota items below are not current requirements.

> Use superpowers:subagent-driven-development for bounded implementation and independent source review. Keep unrelated existing changes.

**Goal:** Complete the confirmed gap review with recoverable operations, clear management semantics, structured UI, actual storage setup and meaningful verification. Existing account directories/files are not migrated.

**Architecture:** Retain React/AntD and FastAPI/root agent. Root agent remains authoritative for host capability and policy; typed responses expose concrete reasons and operation effects. No new service or dependency is required for routine UI changes. Recovery persists non-secret provisioning state and validates identity/path ownership before continuing; credentials must be freshly supplied when resuming. Storage configuration must reflect real device and mount state, not simulated capability flags.

**Tech Stack:** Python/FastAPI/SQLite, React/TypeScript/AntD, pytest, Vitest, Playwright, Linux ext4/XFS quota and POSIX ACL.

## 1. Scope and evidence baseline
- [x] Read requirements gap review, current source and worktree. Preserve preceding uncommitted account page and shell fix.
- [x] Include user's additional requirement to complete actual storage configuration.
- [x] Inspect disks, mounts, capacity, root configuration and current accounts. Pick a supported, non-destructive setup for new accounts without moving old accounts. Any truly missing storage choice is requested while independent work continues.

## 2. Backend management contract and account recovery
Files: agent/accounts.py, agent/host.py, agent/demo.py, domain/schemas.py, api/routes/system.py, api/routes/auth.py, api/context.py; focused backend tests.
- [x] Tests first: interrupt create at native useradd/directory/files/credentials/login steps; retry resumes only same reserved request/UID/paths, refuses pre-existing accounts, swapped paths, reused identity and concurrent requests. Never store password/private key in checkpoints or audits.
- [x] Add durable creation checkpoints and explicit pending/recovery status. Provide preview + reason-bound continuation using fresh credentials; preserve existing files and keep partial accounts restricted. Tick must not unlock incomplete provisioning.
- [x] Expose concrete account protection/read-only reasons (maintenance, system, service, unmanaged, nonhuman, deleted, identity/recovery) and authoritative server mutation capability. Demo parity.
- [x] Persist lifecycle reason/time for disable/delete/expiry and their independent restoration; preserve historical unknown values honestly.
- [x] Add nonmutating adoption preflight diagnostics. No old-account directory migration or blanket chmod.
- [x] Add readable preview before/after/effects contract for account, group, quota/share operations, excluding secrets.
- [x] Run focused tests red/green, full backend regression, then independent spec and quality review.

## 3. Frontend operation flows and information hierarchy
Files: components.tsx (extract preview presentation when appropriate), pages.tsx, App.tsx, messages*.ts; Vitest/E2E.
- [x] Preview uses operation kind: process targets only for process operations; account/group/share/quota show affected identity, changes, directory and access impact. Empty targets must not hide changes. Keep token/revision/expiry/reason validation.
- [x] Show authoritative writable/read-only indicator and specific reason on disabled controls. Do not treat agent unavailability as writable.
- [x] Recovery UI with safe fresh credential entry and explicit preview, no duplicate account creation.
- [x] Error-code based zh/en user guidance with expandable original diagnostics; preserve raw user names, paths, command text.
- [x] Account detail displays login-policy applied/pending/error, effective expiry, lifecycle reasons/times, last confirmed login, storage measurement/quotas, structured processes/sessions/scheduled activities and scan coverage.
- [x] Build and meaningful component/navigation/preview/recovery/i18n/mobile tests; independent spec and quality review.

## 4. Storage configuration and native acceptance
Files: CLI/config/storage where needed, deploy templates, native acceptance scripts, DEPLOYMENT.md/TRIAL_DEPLOYMENT.md.
- [x] Verify actual mount and capacity for new-account roots, root ownership, disjoint paths, expected devices and API/agent configuration consistency. Old accounts/files stay in place.
- [ ] Deferred by user on 2026-10-15: enable root-filesystem user quotas in a separately arranged maintenance window, then verify byte/inode limits, readback and grace. Current /data setup must not modify the root filesystem or reboot.
- [x] Verify current-instance share creation, reader/writer/outsider ACL access and new file inheritance, revoked membership semantics, user private isolation.
- [x] Complete SSH/PAM matrix: password/key + forced initial change, interactive/noninteractive/SFTP before/after reset. Use isolated test accounts; leave gpu_trial available to user.
- [ ] Backup/restore and service upgrade/rollback rehearsal in isolated instance; actual singleton/service restart checks. Do not reboot active training server or claim nonexistent hardware combinations verified.

## 5. Final integration and delivery
- [x] Update PRD to final agreed runtime-only/manual-residual/maintenance rules; distinguish current configuration from historical deployment notes.
- [ ] Complete release testing sequentially to avoid CPU-related test flakiness; fresh Ubuntu full backend, frontend unit/type/build, Chrome full E2E and native acceptance.
- [x] Back up databases/config, deploy, verify real API/UI readback and protection invariants. No user tasks terminated by acceptance.
- [ ] Record requirement-by-requirement evidence and remaining physical constraints; mark goal complete only when required behavior and storage configuration are actually verified.

## Historical gate before storage choice (superseded below)

Backend 319 tests passed on Ubuntu; deployed with consistent backups and isolated release database rehearsal. Browser full 19 passed and affected 11 passed; post-deploy host/demo desktop/mobile/locale/deep-link checks passed. Current-instance ACL 13 checks passed. SSH native matrix passed 24 checks after correcting Chinese PAM prompt handling in its test driver. Data-volume selection remains pending; no root filesystem remount, partitioning or old-account directory migration performed. Storage initialization, native quota acceptance and final completion remain unchecked.

Final frozen frontend regression: 94/94 passed. Startup singleton ordering corrected and tested (Ubuntu focused 3/3 plus live held-lock check); agent restarted successfully with configuration preserved. Backup: /var/lib/gpupm-trial/backup-singleton-1791999380667280977. Remaining storage-volume decision is unchanged; automated continuation is not approval.

## Storage choice applied (2026-10-15 09:18 Asia/Shanghai)

User selected system-disk /data and deferred quota activation requiring root-filesystem changes/reboot to a maintenance window. New roots /home, /data, /data/shared are deployed with stable device checks; old identities and48 recorded directories remained unchanged. Native ACL13 and SSH24 checks passed on new roots. API readback confirms roots and quota_enabled=false. The earlier storage-choice blocker is resolved. Quota activation/acceptance remains an explicit maintenance follow-up; no maintenance time has been agreed.

## Current evidence index

See [current acceptance status](../../ACCEPTANCE_STATUS.md). Storage choice and new-root native SSH/ACL acceptance are complete. Quota activation is deferred by the user. Isolated database upgrade/restore and live service restart checks passed; full native-account rollback, host reboot and long-load acceptance have not been established. Unchecked broad gates must not be inferred complete from narrower tests.

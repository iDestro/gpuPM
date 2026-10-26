# Reliability fixes after independent audit

Goal: Fix six verified defects without adding product features or deleting historical records.

- [x] Task transport: replace oversized all-history RPC transfer with internally bounded snapshot retrieval; retain history, coherent snapshot and fresh active-task policy synchronization. Test >1 MiB histories and normal transport.
- [x] Task policy: preserve last applied policy on failures; reconcile ambiguous RPC outcomes against actual agent revision/policy rather than blindly replaying changes. Test rejection, response loss after application and later successful heartbeat, including existing failed records.
- [x] Frontend: prevent cancel/X/mask/Escape during writes (PreviewDialog and EditDialog). Retain drafts after preview/revision failure and return to editing with refreshed target; do not silently replay stale full membership sets.
- [x] Account policy: unify old system-users business-field update eligibility with current task policy eligibility, freezing existing task snapshots before supported updates; alternatively reject retired update fields while preserving creation/recovery profiles. Test disabled/expired/recovery and ordinary eligible accounts.
- [x] Storage: directory usage means allocated disk space; count st_blocks * 512 once per (device,inode) per scan root, preserve symlink/mount safety and partial errors. Test normal, sparse, hardlinked files.
- [x] Review every changed path and tests; run relevant and full backend/frontend checks, browser regressions, build. No dependency additions or broad refactor.
- [x] Backup/rehearse/deploy to wzx-ubuntu; verify health and readonly UI, native identities and shared ACL unchanged. Document limits and rollback.

Approved by user after audit. Existing uncommitted changes are baseline; do not reset, commit or overwrite other work. No production destructive tests. Current low-volume single-host administration is the scale assumption; task history grows over time.

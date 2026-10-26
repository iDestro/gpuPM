# System group membership experience

Goal: Match task-policy group member management while preserving native preview/revision/authorization guards.

- [x] Add focused interaction coverage for additive membership, primary/read-only protection and cancellation.
- [x] Add member dialog with searchable inventory, primary/supplementary labels and account links; independent add-member selector preserves original supplementary members. Removal submits a proposed member list through existing preview.
- [x] Wire group-name/member entry, keep rename separate and creation compatible; translate all labels.
- [x] Run related unit/browser tests and build. Deploy existing backup/rollback flow and perform native readonly UI validation.

Scope: frontend only. Existing API/root mutation validation remains authoritative. Candidate eligibility excludes protected, unmanaged, disabled and recovery accounts. Group revision snapshot accompanies proposed change. Primary-group changes stay in account details. No real user memberships changed during deployment validation.

Completed: 11 relevant unit tests and 5 browser tests passed; build passed. Frontend-only deployment and native readonly UI validation completed without restarting services. See TEST_REPORT.md and TRIAL_DEPLOYMENT.md.

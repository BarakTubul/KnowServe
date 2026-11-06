# ADR 0006: Daily Demo cleanup trigger and the SEC-14 exception

Status: accepted (OPEN-26 N4, N6). Date: 2026-11-06.

## Decision
- One QStash schedule (cron, once a day) calls `POST /internal/maintenance/demo-cleanup` on the Worker. No Cloud Scheduler and no new job framework.
- The endpoint verifies the QStash signature with the existing code, accepts no caller-controlled parameters (body and query are ignored; limits come from configuration) and runs one fixed, bounded, idempotent operation: delete `demo` users older than `KS_DEMO_RETENTION_SECONDS` (48 h), in batches of `KS_DEMO_CLEANUP_BATCH_SIZE`, and purge old counter rows. It needs no job row; this is the single exception to the signed-job rule of SEC-14, which stays in force for document processing.
- Safe under races: the delete re-checks `kind = 'demo'` in the same transaction, and conversion locks the user row, so exactly one of them wins and converted data is never deleted. Repeating a run changes nothing. Logs and the audit entry carry counts only.
- Creating the schedule is a cloud action and needs separate Owner approval, after confirming schedule availability and quotas. The schedule definition is prepared as code or a documented command in M1-07.
- Firebase anonymous accounts are not touched (N2).

## Consequences
- Between runs Demo rows can live up to about 72 hours; an expired Demo is inaccessible from 24 hours (AUTH-10, AUTH-16).
- The endpoint needs an independent security review (M1-11).

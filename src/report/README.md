# REPORT-v1.1.0-DRAFT R4 registration proposal

This module is intentionally independent from `app/backend` and the common Alembic chain.
`REPORT-v1.0.0` payloads and responses remain compatible; v1.1 adds layout, history and
manual-command contracts without registering a runtime.

R4 registration work:

1. wrap the framework-neutral `create_report_router(...)` route contract with an R4-owned FastAPI `APIRouter` behind the common authentication/authorization middleware;
2. replace `InMemoryReportRepository` with the application PostgreSQL repository;
3. preserve `migration_proposal.sql` and translate only `migration_proposal_v1_1.sql` into a new Alembic revision after the current R4 head;
4. keep approved definition versions insert-only and retain `definition_version`, `as_of`, policy, context, watermark, artifact, query and snapshot checksum on every run;
5. expose definition list/detail, draft block replacement and run list/detail only after repository contract tests pass;
6. expose `POST /reports/runs/manual` as the client trust boundary: accept only `definition_id`, `version`, `as_of`, `idempotency_key`, generate the command ID server-side and keep status/result/policy/context/watermark worker-owned;
7. keep the legacy full run-result ingestion contract trusted-internal rather than exposing it to an untrusted client.

Backend registration and persistent schedule queueing are implemented under `app/backend`.
Command consumption and analysis/Artifact execution workers are not implemented yet.

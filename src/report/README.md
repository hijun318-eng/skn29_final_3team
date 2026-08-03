# REPORT-v1.0.0 R4 registration proposal

This module is intentionally independent from `app/backend` and the common Alembic chain.
R4 registration work:

1. wrap the framework-neutral `create_report_router(...)` route contract with an R4-owned FastAPI `APIRouter` behind the common authentication/authorization middleware;
2. replace `InMemoryReportRepository` with the application PostgreSQL repository;
3. translate `migration_proposal.sql` into a new immutable Alembic revision with the current R4 head;
4. keep approved definition versions insert-only and retain `definition_version`, `as_of`, policy, context, watermark, artifact, query and snapshot checksum on every run;
5. publish the resulting endpoints in the R4-owned OpenAPI contract after consumer contract tests pass.

No worker, schedule runtime, authentication decision or common migration registration is implemented here.
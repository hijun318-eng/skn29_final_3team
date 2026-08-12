\set ON_ERROR_STOP on

-- psql variable apply must be exactly true. Default caller supplies false.
BEGIN;

CREATE TEMP TABLE retention_candidates AS
SELECT request_id
FROM chat.analysis_requests
WHERE completed_at < now() - interval '180 days';

CREATE TEMP TABLE artifact_retention_candidates AS
SELECT a.artifact_id
FROM artifact.analysis_artifacts a
JOIN chat.analysis_requests r USING (request_id)
WHERE r.completed_at < now() - interval '30 days'
  AND NOT EXISTS (
      SELECT 1 FROM report_v1.report_block_runs br
      WHERE br.artifact_id = a.artifact_id
  );

SELECT 'audit_requests_180d' AS policy, count(*) AS candidate_count
FROM retention_candidates;

SELECT 'artifacts_30d' AS policy, count(*) AS candidate_count
FROM artifact_retention_candidates;

\if :apply
DELETE FROM artifact.analysis_artifacts
WHERE artifact_id IN (SELECT artifact_id FROM artifact_retention_candidates);
DELETE FROM query.query_executions q
USING chat.analysis_requests r
WHERE q.request_id = r.request_id
  AND r.completed_at < now() - interval '30 days'
  AND NOT EXISTS (
      SELECT 1 FROM artifact.analysis_artifacts a
      WHERE a.query_execution_id = q.query_execution_id
  );
DELETE FROM governance.audit_events
WHERE request_id IN (SELECT request_id FROM retention_candidates);
DELETE FROM analysis_v1.analysis_run_links
WHERE request_id IN (SELECT request_id FROM retention_candidates);
DELETE FROM chat.analysis_state_transitions
WHERE request_id IN (SELECT request_id FROM retention_candidates);
DELETE FROM artifact.analysis_artifacts
WHERE request_id IN (SELECT request_id FROM retention_candidates)
  AND NOT EXISTS (
      SELECT 1 FROM report_v1.report_block_runs br
      WHERE br.artifact_id = artifact.analysis_artifacts.artifact_id
  );
DELETE FROM query.query_executions
WHERE request_id IN (SELECT request_id FROM retention_candidates)
  AND NOT EXISTS (
      SELECT 1 FROM artifact.analysis_artifacts a
      WHERE a.query_execution_id = query.query_executions.query_execution_id
  );
UPDATE chat.analysis_requests
SET context_package_id = NULL
WHERE request_id IN (SELECT request_id FROM retention_candidates);
DELETE FROM context.context_packages
WHERE request_id IN (SELECT request_id FROM retention_candidates);
DELETE FROM chat.analysis_requests
WHERE request_id IN (SELECT request_id FROM retention_candidates)
  AND NOT EXISTS (
      SELECT 1 FROM artifact.analysis_artifacts a
      WHERE a.request_id = chat.analysis_requests.request_id
  );
\endif

COMMIT;

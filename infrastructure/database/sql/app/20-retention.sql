\set ON_ERROR_STOP on

-- psql variable apply must be exactly true. Default caller supplies false.
BEGIN;

CREATE TEMP TABLE artifact_retention_candidates AS
SELECT a.artifact_id,
       CASE WHEN EXISTS (
           SELECT 1
           FROM report_v1.report_block_runs br
           JOIN report_v1.report_runs rr USING (run_id)
           JOIN report_v1.report_definition_versions rv
             ON rv.definition_id = rr.definition_id
            AND rv.version = rr.definition_version
           WHERE br.artifact_id = a.artifact_id
             AND rv.status = 'approved'
       ) THEN 'approved_report_snapshot_90d'
       ELSE 'artifact_snapshot_30d'
       END AS policy
FROM artifact.analysis_artifacts a
JOIN chat.analysis_requests r USING (request_id)
WHERE (
    r.completed_at < now() - interval '30 days'
    AND NOT EXISTS (
        SELECT 1 FROM report_v1.report_block_runs br
        WHERE br.artifact_id = a.artifact_id
    )
) OR (
    EXISTS (
        SELECT 1
        FROM report_v1.report_block_runs br
        JOIN report_v1.report_runs rr USING (run_id)
        JOIN report_v1.report_definition_versions rv
          ON rv.definition_id = rr.definition_id
         AND rv.version = rr.definition_version
        WHERE br.artifact_id = a.artifact_id
          AND rv.status = 'approved'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM report_v1.report_block_runs br
        JOIN report_v1.report_runs rr USING (run_id)
        WHERE br.artifact_id = a.artifact_id
          AND rr.created_at >= now() - interval '90 days'
    )
);

CREATE TEMP TABLE audit_retention_candidates AS
SELECT audit_event_id
FROM governance.audit_events
WHERE created_at < now() - interval '180 days';

SELECT policy, count(*) AS candidate_count
FROM artifact_retention_candidates
GROUP BY policy
ORDER BY policy;

SELECT 'audit_metadata_archive_180d' AS policy, count(*) AS candidate_count
FROM audit_retention_candidates;

\if :apply
UPDATE artifact.analysis_artifacts
SET data_snapshot_json = '{}'::jsonb,
    chart_spec_json = '{}'::jsonb,
    narrative_markdown = NULL
WHERE artifact_id IN (SELECT artifact_id FROM artifact_retention_candidates);

INSERT INTO governance.audit_events_archive
    (audit_event_id, request_id, actor_user_id, actor_role, action_code,
     object_type, object_id, context_release_id, model_version_id,
     sql_policy_version, query_execution_id, artifact_id, report_run_id,
     details_json_redacted, trace_id, created_at)
SELECT audit_event_id, request_id, actor_user_id, actor_role, action_code,
       object_type, object_id, context_release_id, model_version_id,
       sql_policy_version, query_execution_id, artifact_id, report_run_id,
       details_json_redacted, trace_id, created_at
FROM governance.audit_events
WHERE audit_event_id IN (SELECT audit_event_id FROM audit_retention_candidates)
ON CONFLICT (audit_event_id) DO NOTHING;

DELETE FROM governance.audit_events
WHERE audit_event_id IN (SELECT audit_event_id FROM audit_retention_candidates)
  AND EXISTS (
      SELECT 1 FROM governance.audit_events_archive archived
      WHERE archived.audit_event_id = governance.audit_events.audit_event_id
  );
\endif

COMMIT;

/** 보고서 artifact의 렌더 가능 근거 불변식을 한곳에서 판정하는 모듈이다. */
/** 서버가 공개한 artifact/period/source/gate 근거가 완전한 결과만 렌더 가능하다고 판정한다. */
export function reportEvidenceReady(artifact: any): boolean {
  const evidence = artifact?.evidence;
  const metricFields = new Set((evidence?.metrics ?? []).map((metric: any) => metric.result_field));
  const hasPeriod = Boolean(evidence?.period?.start && evidence?.period?.end_exclusive);
  const hasSnapshot = Boolean(
    evidence?.snapshot?.cutoff
    && evidence?.snapshot?.selection === "max_source_value_lt_as_of"
  );
  return Boolean(
    artifact?.artifact_id
    && evidence?.artifact_id === artifact.artifact_id
    && !artifact?.query_id
    && !evidence?.query_id
    && hasPeriod !== hasSnapshot
    && evidence?.sources?.length
    && evidence?.gates?.g1 === "PASSED"
    && evidence?.gates?.g2 === "PASSED"
    && evidence?.gates?.g3 === "PASSED"
    && (!artifact.chart || (
      artifact.table?.columns?.includes(artifact.chart.x_field)
      && artifact.chart.y_fields?.length
      && artifact.chart.y_fields.every((field: string) => (
        artifact.table.columns.includes(field) && metricFields.has(field)
      ))
    ))
  );
}

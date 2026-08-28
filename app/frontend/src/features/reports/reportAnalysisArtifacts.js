/** 저장 분석 실행과 보고서 artifact library 사이의 근거 보존 adapter 모듈이다. */
function analysisPeriodLabel(period = {}) {
  const start = String(period.start || period.period_start || "").slice(0, 10);
  const end = String(
    period.endExclusive || period.end_exclusive || period.period_end_exclusive || "",
  ).slice(0, 10);
  return start && end ? `${start}\u2013${end}` : "";
}

function analysisSnapshotLabel(snapshot = {}) {
  const cutoff = String(snapshot.cutoff || snapshot.snapshot_cutoff || "").slice(0, 10);
  const selection = snapshot.selection || snapshot.snapshot_selection;
  return cutoff && selection === "max_source_value_lt_as_of"
    ? `${cutoff} 이전 최신 스냅샷`
    : "";
}

/** 기간 또는 최신 snapshot 중 정확히 확인된 시간 근거 하나를 사용자용 문구로 만든다. */
export function analysisTimeLabel(evidence = {}, fallback = {}) {
  const period = analysisPeriodLabel(evidence.period || fallback);
  const snapshot = analysisSnapshotLabel(evidence.snapshot || fallback);
  if (period && snapshot) return "";
  return period || snapshot;
}

/** 저장 제목을 우선하고, 없을 때만 governed 지표·기간으로 일반 artifact 제목을 만든다. */
export function analysisArtifactTitle(artifact, preferredTitle = "", fallbackPeriod = {}) {
  const savedTitle = String(preferredTitle || "").trim();
  if (savedTitle) return savedTitle;
  const definitions = artifact?.metrics?.length ? artifact.metrics : artifact?.evidence?.metrics || [];
  const labels = [...new Set(definitions
    .map((metric) => String(metric.label || "").trim())
    .filter(Boolean))];
  const metricLabel = labels.length > 1
    ? `${labels[0]} \uc678 ${labels.length - 1}\uac1c \uc9c0\ud45c`
    : labels[0] || "\uc8fc\uc694 \uc9c0\ud45c";
  const timeLabel = analysisTimeLabel(artifact?.evidence, fallbackPeriod);
  return `${timeLabel ? `${timeLabel} ` : ""}${metricLabel} \ubd84\uc11d`;
}

/** 성공·부분 성공 실행에서 중복 artifact를 제거한 최신순 library source를 만든다. */
export function analysisRunArtifactSources(runs = [], definitions = []) {
  const exactTitles = new Map(definitions.map((definition) => [
    `${definition.definition_id}:${definition.version}`,
    String(definition.title || "").trim(),
  ]));
  const currentTitles = new Map(definitions.map((definition) => [
    definition.definition_id,
    String(definition.title || "").trim(),
  ]));
  const seen = new Set();
  return [...runs]
    .filter((run) => ["SUCCEEDED", "PARTIAL"].includes(run?.status) && run.request_id && run.artifact_id)
    .sort((left, right) => String(right.completed_at || right.started_at || "")
      .localeCompare(String(left.completed_at || left.started_at || "")))
    .flatMap((run) => {
      if (seen.has(run.artifact_id)) return [];
      seen.add(run.artifact_id);
      const definitionTitle = exactTitles.get(`${run.definition_id}:${run.definition_version}`)
        || currentTitles.get(run.definition_id)
        || "";
      return [{
        id: `analysis-run:${run.request_id}`,
        type: "artifact",
        sourceKind: "analysisRun",
        artifactId: run.artifact_id,
        queryId: run.query_id || undefined,
        requestId: run.request_id,
        analysisDefinitionId: run.definition_id,
        analysisDefinitionVersion: run.definition_version,
        definitionTitle,
        title: analysisArtifactTitle(null, definitionTitle, run),
        periodStart: run.period_start || undefined,
        periodEndExclusive: run.period_end_exclusive || undefined,
        snapshotCutoff: run.snapshot_cutoff || undefined,
        snapshotSelection: run.snapshot_selection || undefined,
      }];
    });
}

function analysisMetricToReport(metric) {
  return {
    metric_id: metric.metricId,
    result_field: metric.resultField,
    label: metric.label,
    definition: metric.definition,
    value: metric.value,
    unit: metric.unit ?? null,
  };
}

function analysisMetricReferenceToReport(metric) {
  const { value: _value, ...reference } = analysisMetricToReport(metric);
  return reference;
}

/** 근거 gate와 artifact/query identity가 일치한 분석 실행만 보고서 wire artifact로 변환한다. */
export function adaptAnalysisRunArtifact(run) {
  if (!["success", "partial"].includes(run?.status) || run.evidenceReady !== true) return null;
  const artifactId = run.artifact?.artifactId;
  const queryId = run.artifact?.queryId;
  const evidence = run.evidence;
  if (!artifactId || !queryId || evidence?.artifactId !== artifactId || evidence?.queryId !== queryId) return null;
  return {
    contract_version: run.meta?.contractVersion,
    request_id: run.requestId,
    trace_id: run.traceId,
    status: run.status.toUpperCase(),
    artifact_id: artifactId,
    query_id: queryId,
    summary: run.summary || "",
    metrics: (run.metrics || []).map(analysisMetricToReport),
    table: run.table
      ? { columns: [...run.table.columns], rows: run.table.rows.map((row) => ({ ...row })) }
      : null,
    chart: run.chart ? {
      chart_type: run.chart.chartType,
      type: run.chart.chartType,
      x_field: run.chart.xField,
      y_fields: [...run.chart.yFields],
    } : null,
    evidence: {
      artifact_id: evidence.artifactId,
      query_id: evidence.queryId,
      as_of: evidence.asOf,
      timezone: evidence.timezone,
      period: evidence.period
        ? { start: evidence.period.start, end_exclusive: evidence.period.endExclusive }
        : null,
      snapshot: evidence.snapshot
        ? { cutoff: evidence.snapshot.cutoff, selection: evidence.snapshot.selection }
        : null,
      filters: { ...(evidence.filters || {}) },
      context_release: evidence.contextRelease,
      product_release_id: evidence.productReleaseId,
      evidence_cutoff: evidence.evidenceCutoff,
      policy_version: evidence.policyVersion,
      model_version: evidence.modelVersion,
      metrics: (evidence.metrics || []).map(analysisMetricReferenceToReport),
      models: (evidence.models || []).map((model) => ({
        node: model.node,
        model_version: model.modelVersion,
        prompt_id: model.promptId,
        prompt_version: model.promptVersion,
      })),
      gates: evidence.gates ? { ...evidence.gates } : null,
      gate_history: evidence.gateHistory ? {
        g1: [...evidence.gateHistory.g1],
        g2: [...evidence.gateHistory.g2],
        g3: [...evidence.gateHistory.g3],
      } : null,
      cached: Boolean(evidence.cached),
      sampling: evidence.sampling ? {
        applied: Boolean(evidence.sampling.applied),
        returned_rows: evidence.sampling.returnedRows,
        total_rows: evidence.sampling.totalRows,
      } : null,
      masking: evidence.masking ? {
        applied: Boolean(evidence.masking.applied),
        fields: [...evidence.masking.fields],
      } : null,
      sources: (run.sources || []).map((source) => ({
        name: source.name,
        urn: source.urn,
        fqn: source.fqn,
        schema_version: source.schemaVersion,
        seed_version: source.seedVersion,
        synthetic: typeof source.synthetic === "boolean" ? source.synthetic : undefined,
      })),
    },
  };
}

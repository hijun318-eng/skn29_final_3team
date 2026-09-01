/** 동일한 표시 내용의 분석 결과를 최근 실행 하나로 묶는 순수 library 표시 정책이다. */
function artifactContentKey(source, artifact) {
  if (!artifact?.table || !Array.isArray(artifact.table.rows)) {
    return `artifact:${source.artifactId}`;
  }
  return JSON.stringify({
    title: String(source.title || "").trim(),
    summary: artifact.summary || "",
    metrics: artifact.metrics || artifact.evidence?.metrics || [],
    table: artifact.table,
    chart: artifact.chart || null,
    period: artifact.evidence?.period || null,
    comparisonPeriod: artifact.evidence?.comparison_period || null,
    timeGranularity: artifact.evidence?.time_granularity || null,
    timeField: artifact.evidence?.time_field || null,
    sources: artifact.evidence?.sources || [],
  });
}

/** exact content가 같은 실행만 묶고 현재 선택된 실행이 있으면 그 실행을 대표로 유지한다. */
export function compactReportArtifactOptions(options = [], artifacts = {}, selectedArtifactId = "") {
  const groups = [];
  const groupByKey = new Map();
  for (const source of options) {
    const key = artifactContentKey(source, artifacts[source.artifactId]);
    let group = groupByKey.get(key);
    if (!group) {
      group = { sources: [] };
      groupByKey.set(key, group);
      groups.push(group);
    }
    group.sources.push(source);
  }
  return groups.map((group) => {
    const representative = group.sources.find((source) => source.artifactId === selectedArtifactId)
      || group.sources[0];
    return group.sources.length > 1
      ? { ...representative, duplicateCount: group.sources.length }
      : representative;
  });
}

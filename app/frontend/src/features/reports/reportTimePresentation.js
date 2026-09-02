/** 서버가 확정한 시간 granularity를 보고서용 locale 표현으로 바꾸는 순수 helper다. */
const SUPPORTED_TIME_GRANULARITIES = new Set(["day", "week", "month", "quarter", "year"]);
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$/;

function dateParts(value) {
  const match = ISO_DATE.exec(String(value ?? "").trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return { year, month, day };
}

function dateFromParts(parts) {
  return new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
}

function previousDate(value) {
  const parts = dateParts(value);
  if (!parts) return null;
  const date = dateFromParts(parts);
  date.setUTCDate(date.getUTCDate() - 1);
  return {
    year: date.getUTCFullYear(),
    month: date.getUTCMonth() + 1,
    day: date.getUTCDate(),
  };
}

function evidenceGranularity(artifact) {
  const value = String(
    artifact?.evidence?.time_granularity
      ?? artifact?.evidence?.timeGranularity
      ?? "",
  ).trim().toLowerCase();
  return SUPPORTED_TIME_GRANULARITIES.has(value) ? value : "";
}

function evidenceRange(artifact) {
  const range = artifact?.evidence?.time_range ?? artifact?.evidence?.period;
  const start = dateParts(range?.start);
  const end = previousDate(range?.end_exclusive ?? range?.endExclusive);
  return start && end ? { start, end } : null;
}

function configuredTimeField(artifact) {
  const configured = String(
    artifact?.evidence?.time_field
      ?? artifact?.evidence?.timeField
      ?? artifact?.chart?.x_field
      ?? "",
  ).trim();
  if (configured) return configured;
  const columns = Array.isArray(artifact?.table?.columns) ? artifact.table.columns : [];
  const rows = Array.isArray(artifact?.table?.rows) ? artifact.table.rows : [];
  const dateColumns = columns.filter((column) => {
    const values = rows
      .map((row) => row?.[column])
      .filter((value) => value !== null && value !== undefined && value !== "");
    return values.length > 0 && values.every((value) => dateParts(value));
  });
  return dateColumns.length === 1 ? dateColumns[0] : "";
}

/** 선언값이 없는 과거 결과는 canonical 날짜 category의 표시 정밀도만 판정한다. */
function inferredDisplayGranularity(artifact, field) {
  const timeField = configuredTimeField(artifact);
  if (!timeField || field !== timeField) return "";
  const rows = Array.isArray(artifact?.table?.rows) ? artifact.table.rows : [];
  const values = rows
    .map((row) => row?.[field])
    .filter((value) => value !== null && value !== undefined && value !== "");
  const parsed = values.map(dateParts);
  if (!values.length || parsed.some((item) => !item)) return "";
  const allYearStarts = parsed.every((item) => item.month === 1 && item.day === 1);
  const distinctYears = new Set(parsed.map((item) => item.year)).size;
  if (allYearStarts && distinctYears > 1) return "year";
  if (parsed.every((item) => item.day === 1)) return "month";
  return "day";
}

function presentationGranularity(artifact, field = configuredTimeField(artifact)) {
  return evidenceGranularity(artifact) || inferredDisplayGranularity(artifact, field);
}

function monthRangeLabel(start, end) {
  if (start.year === end.year && start.month === end.month) {
    return `${start.year}년 ${start.month}월`;
  }
  if (start.year === end.year) {
    return `${start.year}년 ${start.month}월~${end.month}월`;
  }
  return `${start.year}년 ${start.month}월~${end.year}년 ${end.month}월`;
}

function dayRangeLabel(start, end) {
  if (start.year === end.year && start.month === end.month && start.day === end.day) {
    return `${start.year}년 ${start.month}월 ${start.day}일`;
  }
  if (start.year === end.year && start.month === end.month) {
    return `${start.year}년 ${start.month}월 ${start.day}~${end.day}일`;
  }
  if (start.year === end.year) {
    return `${start.year}년 ${start.month}월 ${start.day}일~${end.month}월 ${end.day}일`;
  }
  return `${start.year}년 ${start.month}월 ${start.day}일~${end.year}년 ${end.month}월 ${end.day}일`;
}

function quarter(parts) {
  return Math.floor((parts.month - 1) / 3) + 1;
}

function rangeLabel(granularity, range) {
  if (!range) return "";
  const { start, end } = range;
  if (granularity === "month") return monthRangeLabel(start, end);
  if (granularity === "year") {
    return start.year === end.year ? `${start.year}년` : `${start.year}~${end.year}년`;
  }
  if (granularity === "quarter") {
    const startQuarter = quarter(start);
    const endQuarter = quarter(end);
    if (start.year === end.year && startQuarter === endQuarter) {
      return `${start.year}년 ${startQuarter}분기`;
    }
    if (start.year === end.year) {
      return `${start.year}년 ${startQuarter}~${endQuarter}분기`;
    }
    return `${start.year}년 ${startQuarter}분기~${end.year}년 ${endQuarter}분기`;
  }
  return dayRangeLabel(start, end);
}

function categoryLabels(granularity, values) {
  const parsed = values.map(dateParts);
  if (!values.length || parsed.some((item) => !item)) return null;
  const years = new Set(parsed.map((item) => item.year));
  const axis = (value) => {
    const item = dateParts(value);
    if (!item) return String(value ?? "—");
    if (granularity === "month") {
      return years.size > 1 ? `${item.year}년 ${item.month}월` : `${item.month}월`;
    }
    if (granularity === "year") return `${item.year}년`;
    if (granularity === "quarter") {
      return years.size > 1 ? `${item.year}년 ${quarter(item)}분기` : `${quarter(item)}분기`;
    }
    return `${item.month}/${item.day}`;
  };
  const detail = (value) => {
    const item = dateParts(value);
    if (!item) return String(value ?? "—");
    if (granularity === "month") return `${item.year}년 ${item.month}월`;
    if (granularity === "year") return `${item.year}년`;
    if (granularity === "quarter") return `${item.year}년 ${quarter(item)}분기`;
    return `${item.year}년 ${item.month}월 ${item.day}일`;
  };
  return { axis, detail };
}

/** 선언된 granularity를 우선하고, 과거 결과는 canonical 날짜값의 표시 정밀도만 보완한다. */
export function reportTimeCategoryPresentation(artifact, field) {
  const granularity = presentationGranularity(artifact, field);
  const timeField = configuredTimeField(artifact);
  if (!granularity || !timeField || field !== timeField) return null;
  const rows = Array.isArray(artifact?.table?.rows) ? artifact.table.rows : [];
  const values = rows.map((row) => row?.[field]).filter((value) => value !== null && value !== undefined && value !== "");
  const labels = categoryLabels(granularity, values);
  return labels ? { granularity, ...labels } : null;
}

/** 시간 열의 사용자 표시명을 내부 field명 대신 집계 단위로 만든다. */
export function reportTimeColumnLabel(artifact, field) {
  const presentation = reportTimeCategoryPresentation(artifact, field);
  if (!presentation) return "";
  return {
    day: "일자",
    week: "주",
    month: "월",
    quarter: "분기",
    year: "연도",
  }[presentation.granularity] || "기간";
}

/** canonical [start,end)와 표시 granularity로 보고서 제목에 쓸 기간을 만든다. */
export function reportTimeRangeLabel(artifact) {
  const granularity = presentationGranularity(artifact);
  return granularity ? rangeLabel(granularity, evidenceRange(artifact)) : "";
}

function primaryMetricLabel(artifact) {
  const fields = artifact?.chart?.y_fields?.length
    ? artifact.chart.y_fields
    : (artifact?.evidence?.metrics ?? []).map((metric) => metric.result_field);
  const metrics = artifact?.evidence?.metrics ?? [];
  const labels = fields.map((field) => (
    metrics.find((metric) => metric.result_field === field)?.label
  )).filter((label) => typeof label === "string" && label.trim()).map((label) => label.trim());
  if (!labels.length) return "주요 지표";
  return labels.length === 1 ? labels[0] : `${labels[0]} 외 ${labels.length - 1}개 지표`;
}

/** 새 분석 view를 추가할 때만 사용하는 질문 답변형 기본 제목을 만든다. */
export function reportArtifactDefaultTitle(artifact, type = "artifact") {
  const time = reportTimeRangeLabel(artifact);
  if (!time) return "";
  const suffix = type === "chart" ? "비교" : type === "table" ? "상세" : "분석";
  return `${time} ${primaryMetricLabel(artifact)} ${suffix}`;
}

function metricPhraseFromGeneratedTitle(title) {
  const core = String(title ?? "").replace(/\s*·\s*(?:차트|표)\s*$/, "");
  const analysisAt = core.lastIndexOf(" 분석");
  if (analysisAt < 0) return "";
  const descriptor = core.slice(0, analysisAt).trim();
  const koreanRange = /^\d{4}년\s+\d{1,2}월(?:\s+\d{1,2}일)?부터\s+.+?까지\s+/.exec(descriptor);
  if (koreanRange) return descriptor.slice(koreanRange[0].length).trim();
  const isoRange = /^\d{4}[-.]\d{2}[-.]\d{2}\s*[–~]\s*\d{4}[-.]\d{2}[-.]\d{2}\s+/.exec(descriptor);
  return isoRange ? descriptor.slice(isoRange[0].length).trim() : "";
}

/** 과거 자동 생성 차트·표 제목만 월 단위 표시 정책으로 정리하고 사용자 제목은 보존한다. */
export function normalizeGeneratedArtifactViewTitle(title, artifact, type) {
  const current = String(title ?? "").trim();
  const internalTitle = /^analysis result(?:\s*·\s*(요약|핵심 지표|차트|표))?$/i.exec(current);
  if (internalTitle) {
    const view = internalTitle[1]
      || (type === "chart" ? "차트" : type === "table" ? "표" : "요약");
    const time = reportTimeRangeLabel(artifact);
    const metric = primaryMetricLabel(artifact);
    const label = view === "차트" ? "비교" : view === "표" ? "상세" : view;
    return `${time ? `${time} ` : ""}${metric} ${label}`;
  }
  if (!["chart", "table"].includes(type)) return current;
  const expectedSuffix = type === "chart" ? "차트" : "표";
  if (!/^\d{4}/.test(current) || !new RegExp(`·\\s*${expectedSuffix}\\s*$`).test(current)) {
    return current;
  }
  const time = reportTimeRangeLabel(artifact);
  if (!time) return current;
  const metric = metricPhraseFromGeneratedTitle(current) || primaryMetricLabel(artifact);
  return `${time} ${metric} ${type === "chart" ? "비교" : "상세"}`;
}

/** 과거 날짜 범위형 자동 보고서 제목만 locale 기간과 사용자 지표 표현으로 정리한다. */
export function normalizeGeneratedReportTitle(title, artifact) {
  const current = String(title ?? "").trim();
  if (!/^\d{4}/.test(current) || !/\s분석\s보고서$/.test(current)) return current;
  const time = reportTimeRangeLabel(artifact);
  if (!time) return current;
  const core = current.replace(/\s분석\s보고서$/, "");
  const koreanRange = /^\d{4}년\s+\d{1,2}월(?:\s+\d{1,2}일)?부터\s+.+?까지\s+/.exec(core);
  const isoRange = /^\d{4}[-.]\d{2}[-.]\d{2}\s*[–~]\s*\d{4}[-.]\d{2}[-.]\d{2}\s+/.exec(core);
  const rangePrefix = koreanRange?.[0] || isoRange?.[0] || "";
  if (!rangePrefix) return current;
  const metric = core.slice(rangePrefix.length).trim() || primaryMetricLabel(artifact);
  const timeField = configuredTimeField(artifact);
  const distinctPeriods = new Set(
    (artifact?.table?.rows ?? [])
      .map((row) => row?.[timeField])
      .filter((value) => value !== null && value !== undefined && value !== ""),
  ).size;
  return `${time} ${metric} ${distinctPeriods > 1 ? "비교" : "분석"} 보고서`;
}

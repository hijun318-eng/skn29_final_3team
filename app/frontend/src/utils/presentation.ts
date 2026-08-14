export const ENTERPRISE_SERIES_COLORS = [
  "#5b9df5",
  "#d3a45c",
  "#6bc49b",
  "#b58cf2",
  "#ef7d72",
  "#55b9c5",
  "#df8fba",
  "#9aa9bd",
] as const;

type MetricLike = {
  readonly label?: string | null;
  readonly resultField?: string | null;
  readonly result_field?: string | null;
  readonly unit?: string | null;
};

type PresentationRun = {
  readonly metrics?: readonly MetricLike[];
  readonly chart?: { readonly xField?: string | null } | null;
  readonly table?: { readonly columns?: readonly string[] } | null;
  readonly evidence?: {
    readonly period?: { readonly start?: string | null; readonly endExclusive?: string | null } | null;
    readonly filters?: Readonly<Record<string, unknown>> | null;
    readonly metrics?: readonly MetricLike[];
  } | null;
};

type PeriodLike = { readonly start?: string | null; readonly endExclusive?: string | null };
type DataSourceLike = { readonly synthetic?: boolean | null };

const NUMERIC_TEXT = /^-?\d+(?:\.\d+)?$/;

export function numericValue(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !NUMERIC_TEXT.test(value.trim())) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function isNumericValue(value: unknown): boolean {
  return numericValue(value) !== null;
}

export function formatMetricValue(
  value: unknown,
  options: { readonly unit?: string | null; readonly includeUnit?: boolean; readonly maximumFractionDigits?: number } = {},
): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = numericValue(value);
  if (numeric === null) return String(value);
  const rendered = numeric.toLocaleString("ko-KR", { maximumFractionDigits: options.maximumFractionDigits ?? 2 });
  if (options.includeUnit === false || !options.unit) return rendered;
  return `${rendered} ${options.unit}`;
}

export function formatCompactNumber(value: unknown): string {
  const numeric = numericValue(value);
  if (numeric === null) return "—";
  return numeric.toLocaleString("ko-KR", { notation: "compact", maximumFractionDigits: 1 });
}

export function metricUnitLabel(label: string, unit?: string | null): string {
  return unit ? `${label} (${unit})` : label;
}

export function seriesColor(index: number): string {
  return ENTERPRISE_SERIES_COLORS[Math.abs(index) % ENTERPRISE_SERIES_COLORS.length];
}

export function dataProvenanceLabel(sources: readonly DataSourceLike[] = []): string | null {
  if (sources.length > 0 && sources.every((source) => source.synthetic === true)) return "합성 데모 데이터";
  if (sources.some((source) => source.synthetic === true)) return "합성 데모 데이터 포함";
  return null;
}

function monthTitle(period?: PeriodLike | null): string {
  if (!period?.start || !period?.endExclusive) return "";
  const start = /^(\d{4})-(\d{2})-(\d{2})$/.exec(period.start);
  const end = /^(\d{4})-(\d{2})-(\d{2})$/.exec(period.endExclusive);
  if (!start || !end) return "";
  const startYear = Number(start[1]);
  const startMonth = Number(start[2]);
  const expectedEndYear = startMonth === 12 ? startYear + 1 : startYear;
  const expectedEndMonth = startMonth === 12 ? 1 : startMonth + 1;
  if (start[3] === "01" && end[3] === "01" && Number(end[1]) === expectedEndYear && Number(end[2]) === expectedEndMonth) {
    return `${startYear}년 ${startMonth}월`;
  }
  return `${period.start.replaceAll("-", ".")}–${period.endExclusive.replaceAll("-", ".")}`;
}

function explicitAudience(filters: Readonly<Record<string, unknown>> = {}): string {
  const grade = Object.entries(filters).find(([field]) => {
    const key = field.split(".").at(-1);
    return key === "membership_grade_code" || key === "grade_code";
  })?.[1];
  if (grade === null || grade === undefined || grade === "") return "";
  const rendered = Array.isArray(grade) ? grade.filter(Boolean).join("·") : String(grade);
  return rendered ? `${rendered} 고객` : "";
}

function resultDimension(run: PresentationRun): string {
  const fields = new Set([run.chart?.xField, ...(run.table?.columns ?? [])].filter(Boolean));
  if (fields.has("month")) return "월별";
  if (fields.has("business_date") || fields.has("date") || fields.has("actual_checkout_at") || fields.has("ordered_at")) return "일별";
  return "";
}

export function analysisTitle(run: PresentationRun): string {
  const period = monthTitle(run.evidence?.period);
  const audience = explicitAudience(run.evidence?.filters ?? {});
  const metrics = [...new Set((run.metrics?.length ? run.metrics : run.evidence?.metrics ?? [])
    .map((metric) => metric.label?.trim())
    .filter((label): label is string => Boolean(label)))]
    .slice(0, 2)
    .join("·");
  const structured = [period, audience, metrics, resultDimension(run)].filter(Boolean).join(" ");
  return `${structured || "호텔 운영"} 분석`;
}

export function reportTitleForAnalysis(run: PresentationRun): string {
  return `${analysisTitle(run)} 보고서`;
}

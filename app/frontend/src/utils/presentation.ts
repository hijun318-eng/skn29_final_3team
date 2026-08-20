/** governed 분석 값을 도메인 추론 없이 제목·숫자·색상으로 표현하는 유틸리티 모듈이다. */
/** 차트 계열 순번에만 의존하는 접근성 검토 완료 색상 팔레트다. */
export const ENTERPRISE_SERIES_COLORS = [
  "#3d8ef0",
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
  readonly evidence?: {
    readonly period?: { readonly start?: string | null; readonly endExclusive?: string | null } | null;
    readonly metrics?: readonly MetricLike[];
  } | null;
};

type PeriodLike = { readonly start?: string | null; readonly endExclusive?: string | null };
type DataSourceLike = { readonly synthetic?: boolean | null };

const NUMERIC_TEXT = /^-?\d+(?:\.\d+)?$/;

/** 유한 숫자 또는 엄격한 숫자 문자열만 변환하고 그 밖의 입력은 null로 닫는다. */
export function numericValue(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !NUMERIC_TEXT.test(value.trim())) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** 프레젠테이션 입력이 안전하게 수치화 가능한지 판별한다. */
export function isNumericValue(value: unknown): boolean {
  return numericValue(value) !== null;
}

/** 지표 값을 한국어 숫자 형식으로 표시하며 비수치 값은 원문을 보존한다. */
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

/** 유한 숫자만 compact 표기로 줄이고 유효하지 않은 값은 대시로 표시한다. */
export function formatCompactNumber(value: unknown): string {
  const numeric = numericValue(value);
  if (numeric === null) return "—";
  return numeric.toLocaleString("ko-KR", { notation: "compact", maximumFractionDigits: 1 });
}

/** 서버 지표 라벨과 선택적 단위를 손실 없이 결합한다. */
export function metricUnitLabel(label: string, unit?: string | null): string {
  return unit ? `${label} (${unit})` : label;
}

/** 계열 순번을 고정 팔레트에 순환 매핑해 렌더 간 색상 안정성을 보장한다. */
export function seriesColor(index: number): string {
  return ENTERPRISE_SERIES_COLORS[Math.abs(index) % ENTERPRISE_SERIES_COLORS.length];
}

/** 서버가 명시한 synthetic provenance만 표시하고 출처가 없으면 추정 라벨을 만들지 않는다. */
export function dataProvenanceLabel(sources: readonly DataSourceLike[] = []): string | null {
  if (sources.length > 0 && sources.every((source) => source.synthetic === true)) return "합성 데이터";
  if (sources.some((source) => source.synthetic === true)) return "합성 데이터 포함";
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

/** 승인된 기간·지표 메타데이터만으로 제목을 만들고, 부족하면 일반 결과 제목으로 닫는다. */
export function analysisTitle(run: PresentationRun): string {
  const period = monthTitle(run.evidence?.period);
  const metrics = [...new Set((run.metrics?.length ? run.metrics : run.evidence?.metrics ?? [])
    .map((metric) => metric.label?.trim())
    .filter((label): label is string => Boolean(label)))]
    .slice(0, 2)
    .join("·");
  const structured = [period, metrics].filter(Boolean).join(" ");
  return structured ? `${structured} 분석` : "분석 결과";
}

/** 분석 제목을 보고서 제목 계약으로 확장하며 별도의 도메인 문구를 추론하지 않는다. */
export function reportTitleForAnalysis(run: PresentationRun): string {
  return `${analysisTitle(run)} 보고서`;
}

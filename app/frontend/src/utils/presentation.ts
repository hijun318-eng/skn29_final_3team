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
  readonly metricId?: string | null;
  readonly metric_id?: string | null;
  readonly label?: string | null;
  readonly displayLabel?: string | null;
  readonly display_label?: string | null;
  readonly resultField?: string | null;
  readonly result_field?: string | null;
  readonly unit?: string | null;
  readonly displayUnit?: string | null;
  readonly display_unit?: string | null;
};

type PresentationRun = {
  readonly metrics?: readonly MetricLike[];
  readonly evidence?: {
    readonly period?: { readonly start?: string | null; readonly endExclusive?: string | null } | null;
    readonly comparisonPeriod?: { readonly start?: string | null; readonly endExclusive?: string | null } | null;
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
  const ratio = options.unit?.trim().toLowerCase() === "ratio";
  const rendered = (ratio ? numeric * 100 : numeric).toLocaleString("ko-KR", {
    maximumFractionDigits: options.maximumFractionDigits ?? 2,
  });
  if (options.includeUnit === false || !options.unit) return rendered;
  return ratio ? `${rendered}%` : `${rendered} ${options.unit}`;
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

/** 서버가 승인한 표시명을 우선하고 canonical label은 증거 호환 fallback으로만 사용한다. */
export function metricDisplayLabel(metric: MetricLike): string {
  return String(metric.displayLabel ?? metric.display_label ?? metric.label ?? "").trim()
    || "분석 지표";
}

/** 내부 단위 코드는 계산 계약에 남기고 사용자 화면에는 한국어 단위만 표시한다. */
export function metricDisplayUnit(unit?: string | null, approvedDisplayUnit?: string | null): string | null {
  const supplied = String(approvedDisplayUnit ?? "").trim();
  if (supplied) return supplied;
  if (!unit) return null;
  const normalized = unit.trim().toLowerCase();
  if (normalized === "krw" || normalized.startsWith("krw_per_")) return "원";
  if (normalized === "ratio" || normalized === "%") return "%";
  if (normalized === "room_night" || normalized === "room_nights") return "객실박";
  if (normalized === "room" || normalized === "rooms") return "실";
  if (normalized === "hour" || normalized === "hours") return "시간";
  if (normalized === "point" || normalized === "points") return "점";
  if (normalized === "count") return "건";
  return unit;
}

/** 계산용 원본 단위로 수치를 해석하고 승인된 화면 단위만 사용자에게 붙인다. */
export function formatMetricDisplayValue(value: unknown, metric: MetricLike = {}): string {
  const rendered = formatMetricValue(value, {
    includeUnit: false,
    unit: metric.unit,
  });
  if (numericValue(value) === null) return rendered;
  const displayUnit = metricDisplayUnit(
    metric.unit,
    metric.displayUnit ?? metric.display_unit,
  );
  if (!displayUnit) return rendered;
  return `${rendered}${displayUnit === "%" ? "" : " "}${displayUnit}`;
}

function escapedPattern(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function koreanDateLabel(value?: string | null): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? "");
  return match
    ? `${Number(match[1])}년 ${Number(match[2])}월 ${Number(match[3])}일`
    : "";
}

/** 서버의 `[start, endExclusive)` 기간을 사용자 화면에서만 포함 종료일로 표현한다. */
export function userFacingPeriodLabel(
  start?: string | null,
  endExclusive?: string | null,
): string {
  const startMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(start ?? "");
  const endMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(endExclusive ?? "");
  if (!startMatch || !endMatch) return "";
  const startDate = new Date(Date.UTC(Number(startMatch[1]), Number(startMatch[2]) - 1, Number(startMatch[3])));
  const endInclusive = new Date(Date.UTC(Number(endMatch[1]), Number(endMatch[2]) - 1, Number(endMatch[3])));
  endInclusive.setUTCDate(endInclusive.getUTCDate() - 1);
  if (endInclusive < startDate) return "";

  const startYear = startDate.getUTCFullYear();
  const startMonth = startDate.getUTCMonth() + 1;
  const startDay = startDate.getUTCDate();
  const endYear = endInclusive.getUTCFullYear();
  const endMonth = endInclusive.getUTCMonth() + 1;
  const endDay = endInclusive.getUTCDate();
  if (startYear === endYear && startMonth === endMonth) {
    return `${startYear}년 ${startMonth}월 ${startDay}일부터 ${endDay}일까지`;
  }
  if (startYear === endYear) {
    return `${startYear}년 ${startMonth}월 ${startDay}일부터 ${endMonth}월 ${endDay}일까지`;
  }
  return `${startYear}년 ${startMonth}월 ${startDay}일부터 ${endYear}년 ${endMonth}월 ${endDay}일까지`;
}

/** 서버 요약의 배타 종료일 문구만 같은 기간 계약의 사용자용 표현으로 치환한다. */
export function localizeAnalysisPeriod(
  text: string,
  start?: string | null,
  endExclusive?: string | null,
): string {
  const label = userFacingPeriodLabel(start, endExclusive);
  const startKorean = koreanDateLabel(start);
  const endKorean = koreanDateLabel(endExclusive);
  if (!label || !start || !endExclusive || !startKorean || !endKorean) return text;
  const patterns = [
    `${start}부터 ${endExclusive} 전까지`,
    `${start}부터 ${endExclusive} 이전`,
    `${start} ~ ${endExclusive} 미포함`,
    `${start}–${endExclusive} 미포함`,
    `${startKorean} 전부터 ${endKorean} 전까지`,
    `${startKorean}부터 ${endKorean} 전까지`,
    `${startKorean}부터 ${endKorean} 이전`,
    `${startKorean} ~ ${endKorean} 미포함`,
  ];
  return patterns.reduce(
    (current, pattern) => current.replace(new RegExp(escapedPattern(pattern), "g"), label),
    text,
  );
}

function hasKoreanFinalConsonant(label: string): boolean {
  const lastHangul = [...label].reverse().find((character) => /[가-힣]/.test(character));
  return Boolean(lastHangul && (lastHangul.charCodeAt(0) - 0xac00) % 28 !== 0);
}

function normalizeKoreanParticles(text: string, label: string): string {
  const hasFinal = hasKoreanFinalConsonant(label);
  return [
    ["은", "는"],
    ["이", "가"],
    ["을", "를"],
    ["과", "와"],
  ].reduce((current, [withFinal, withoutFinal]) => current.replace(
    new RegExp(`${escapedPattern(label)}(?:${withFinal}|${withoutFinal})`, "g"),
    `${label}${hasFinal ? withFinal : withoutFinal}`,
  ), text);
}

/** 정의의 의미는 변경하지 않고 사용자 단위 코드만 화면 표기로 바꾼다. */
export function localizeMetricDefinition(definition?: string | null): string {
  if (!definition) return "";
  return definition.replace(/\bKRW\b/gi, "원");
}

/** 서버 서술의 의미는 보존하면서 catalog 영문 label·단위 코드와 기계적인 문장을 화면용 한국어로 정리한다. */
export function localizeAnalysisSummary(summary: string, metrics: readonly MetricLike[] = []): string {
  let localized = localizeMetricDefinition(summary);
  for (const metric of metrics) {
    const sourceLabel = String(metric.label ?? "").trim();
    const displayLabel = metricDisplayLabel(metric);
    if (sourceLabel && sourceLabel !== displayLabel) {
      localized = localized.replace(new RegExp(escapedPattern(sourceLabel), "gi"), displayLabel);
    }
    const sourceUnit = String(metric.unit ?? "").trim();
    const displayUnit = metricDisplayUnit(
      sourceUnit,
      metric.displayUnit ?? metric.display_unit,
    );
    if (sourceUnit && displayUnit && sourceUnit !== displayUnit) {
      localized = localized.replace(new RegExp(escapedPattern(sourceUnit), "gi"), displayUnit);
    }
    localized = normalizeKoreanParticles(localized, displayLabel);
  }
  localized = localized
    .replace(/\bKRW\b/gi, "원")
    .replace(/(\d{4}년\s*\d{1,2}월)의\s+/g, "$1 ")
    .replace(/\s+합계\s+계산\s+결과는/g, " 합계는");
  return localized;
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
  const endInclusive = new Date(Date.UTC(Number(end[1]), Number(end[2]) - 1, Number(end[3])));
  endInclusive.setUTCDate(endInclusive.getUTCDate() - 1);
  if (Number.isNaN(endInclusive.getTime())) return "";
  const inclusiveEnd = [
    endInclusive.getUTCFullYear(),
    String(endInclusive.getUTCMonth() + 1).padStart(2, "0"),
    String(endInclusive.getUTCDate()).padStart(2, "0"),
  ].join(".");
  return `${period.start.replaceAll("-", ".")}–${inclusiveEnd}`;
}

/** 승인된 기간·지표 메타데이터만으로 제목을 만들고, 부족하면 일반 결과 제목으로 닫는다. */
export function analysisTitle(run: PresentationRun): string {
  const period = [
    monthTitle(run.evidence?.period),
    monthTitle(run.evidence?.comparisonPeriod),
  ].filter(Boolean).join("·");
  const metrics = [...new Set((run.metrics?.length ? run.metrics : run.evidence?.metrics ?? [])
    .map((metric) => metricDisplayLabel(metric).trim())
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

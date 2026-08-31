/** 보고서 편집 화면의 배율 선택과 실제 A4 scale 계산을 결정론적으로 제공한다. */

/** 편집기에서 지원하는 UI-only 배율 모드다. */
export const REPORT_EDITOR_SCALE_OPTIONS = [
  { value: "fit-width", label: "읽기 편한 너비" },
  { value: "fit-page", label: "페이지 맞춤" },
  { value: "0.55", label: "55%" },
  { value: "0.72", label: "72%" },
  { value: "0.9", label: "90%" },
  { value: "1", label: "100%" },
] as const;

/** 고정 A4 편집 화면이 모바일에서 축소되어 본문과 조작점이 사라지지 않는 하한이다. */
export const REPORT_EDITOR_MIN_READABLE_SCALE = 0.9;

/** 알 수 없는 저장값이나 URL 입력을 서버 상태로 전파하지 않고 너비 맞춤으로 닫는다. */
export function normalizeReportEditorScale(value: unknown): string {
  return REPORT_EDITOR_SCALE_OPTIONS.some((option) => option.value === value)
    ? value as string
    : "fit-width";
}

/** 자연 A4 크기 대비 가용 폭·높이 비율에서 화면 scale을 계산한다. */
export function resolveReportEditorScale(
  mode: unknown,
  widthRatio: number,
  heightRatio: number,
): number {
  const normalized = normalizeReportEditorScale(mode);
  const safeWidth = Number.isFinite(widthRatio) ? Math.max(0.1, widthRatio) : 1;
  const safeHeight = Number.isFinite(heightRatio) ? Math.max(0.1, heightRatio) : 1;
  if (normalized === "fit-page") return Math.min(1, safeWidth, safeHeight);
  if (normalized === "fit-width") {
    return Math.min(1, Math.max(REPORT_EDITOR_MIN_READABLE_SCALE, safeWidth));
  }
  return Math.min(1, Math.max(0.25, Number(normalized)));
}

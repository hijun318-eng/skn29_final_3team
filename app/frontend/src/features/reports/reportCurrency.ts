/** 보고서 통화 metric의 배율 선택과 손실 없는 표시를 담당하는 모듈이다. */
import type { CurrencyDisplayPolicy, CurrencyDisplayUnit } from "./reportDocument";

type CurrencyUnitDefinition = {
  readonly divisor: number;
  readonly label: string;
};

const CURRENCY_UNITS: Record<Exclude<CurrencyDisplayUnit, "auto">, CurrencyUnitDefinition> = Object.freeze({
  one: Object.freeze({ divisor: 1, label: "원" }),
  thousand: Object.freeze({ divisor: 1_000, label: "천 원" }),
  million: Object.freeze({ divisor: 1_000_000, label: "백만 원" }),
  hundredMillion: Object.freeze({ divisor: 100_000_000, label: "억 원" }),
  billion: Object.freeze({ divisor: 1_000_000_000, label: "십억 원" }),
});

/** 통화 배율 선택 UI가 사용하는 값·라벨 계약이다. */ export const REPORT_CURRENCY_OPTIONS = Object.freeze([
  Object.freeze({ value: "auto", label: "자동" }),
  Object.freeze({ value: "one", label: "원" }),
  Object.freeze({ value: "thousand", label: "천 원" }),
  Object.freeze({ value: "million", label: "백만 원" }),
  Object.freeze({ value: "hundredMillion", label: "억 원" }),
] as const);

/** 서버 metric unit이 지원 통화 단위인지 엄격히 판별한다. */
export function isCurrencyMetricUnit(unit?: string | null): boolean {
  const normalized = String(unit ?? "").replaceAll(" ", "").toLocaleUpperCase("en-US");
  return normalized === "원" || normalized === "₩" || normalized === "KRW" || normalized === "KORWON";
}

/** auto 정책을 실제 값 규모로 결정하며 비수치 입력은 원 단위로 닫는다. */
export function resolveCurrencyDisplayUnit(
  values: readonly unknown[],
  policy: Pick<CurrencyDisplayPolicy, "displayUnit">,
): Exclude<CurrencyDisplayUnit, "auto"> {
  if (policy.displayUnit !== "auto") return policy.displayUnit;
  const maximum = values.reduce<number>((current, value) => {
    const numeric = typeof value === "number" ? value : Number(value);
    return Number.isFinite(numeric) ? Math.max(current, Math.abs(numeric)) : current;
  }, 0);
  if (maximum >= 100_000_000) return "hundredMillion";
  if (maximum >= 1_000_000) return "million";
  if (maximum >= 1_000) return "thousand";
  return "one";
}

/** 확정 통화 배율의 한국어 표시 라벨을 반환한다. */
export function currencyDisplayLabel(unit: Exclude<CurrencyDisplayUnit, "auto">): string {
  return CURRENCY_UNITS[unit].label;
}

/** 원본 금액을 선택 배율로 표시하며 유효하지 않은 값은 대시로 반환한다. */
export function formatCurrencyAmount(
  value: unknown,
  unit: Exclude<CurrencyDisplayUnit, "auto">,
  policy: Pick<CurrencyDisplayPolicy, "maximumFractionDigits">,
  includeUnit = false,
): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  const definition = CURRENCY_UNITS[unit];
  const maximumFractionDigits = unit === "one" ? 0 : policy.maximumFractionDigits;
  const rendered = (numeric / definition.divisor).toLocaleString("ko-KR", {
    maximumFractionDigits,
    minimumFractionDigits: 0,
  });
  return includeUnit ? `${rendered} ${definition.label}` : rendered;
}

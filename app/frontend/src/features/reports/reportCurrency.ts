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

export const REPORT_CURRENCY_OPTIONS = Object.freeze([
  Object.freeze({ value: "auto", label: "자동" }),
  Object.freeze({ value: "one", label: "원" }),
  Object.freeze({ value: "thousand", label: "천 원" }),
  Object.freeze({ value: "million", label: "백만 원" }),
  Object.freeze({ value: "hundredMillion", label: "억 원" }),
] as const);

export function isCurrencyMetricUnit(unit?: string | null): boolean {
  const normalized = String(unit ?? "").replaceAll(" ", "").toLocaleUpperCase("en-US");
  return normalized === "원" || normalized === "₩" || normalized === "KRW" || normalized === "KORWON";
}

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

export function currencyDisplayLabel(unit: Exclude<CurrencyDisplayUnit, "auto">): string {
  return CURRENCY_UNITS[unit].label;
}

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

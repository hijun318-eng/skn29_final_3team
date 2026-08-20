/**
 * 분석 결과 화면(KPI 카드·차트·상세 표)에서 같은 지표가 언제나 같은 통화 배율·같은 단위 라벨로 보이도록 결정하는 모듈이다.
 * 권위 있는 배율 계약은 보고서와 동일한 `features/reports/reportCurrency`이며, 여기서 규칙을 다시 정의하지 않는다.
 *
 * 배율은 지표(resultField) 단위로 정한다. 화면 전체를 하나의 배율로 묶으면
 * `객실 매출 58.4억`과 함께 있는 `평균 객실 단가 284,730원`이 `0억 원`으로 무너지기 때문이다.
 * 지표별로 합계와 항목별 값을 함께 보고 배율을 정하므로, 한 지표가 카드에서는 `28.2억`,
 * 표에서는 `2,820,671,143`으로 갈라지는 문제는 닫힌다.
 */
import {
  currencyDisplayLabel,
  formatCurrencyAmount,
  isCurrencyMetricUnit,
} from "../../features/reports/reportCurrency";
import { formatMetricValue } from "../../utils/presentation";

type ResolvedUnit = "hundredMillion" | "one";

/**
 * 카드·표 한 칸에 들어가야 하므로 배율은 `억 원`과 `원` 두 가지만 쓴다.
 * 보고서의 auto 규칙은 `천 원`·`백만 원`까지 고르지만, 객단가 284,730원이 `284.7천 원`으로 보이는 편이
 * 원문보다 읽기 어려워 분석 화면에서는 채택하지 않는다. 라벨과 포맷터는 보고서 계약을 그대로 쓴다.
 */
function chooseDisplayUnit(values: readonly unknown[]): ResolvedUnit {
  const maximum = values.reduce<number>((current, value) => {
    const numeric = typeof value === "number" ? value : Number(value);
    return Number.isFinite(numeric) ? Math.max(current, Math.abs(numeric)) : current;
  }, 0);
  return maximum >= 100_000_000 ? "hundredMillion" : "one";
}

type ScaleMetricInput = {
  readonly resultField?: string | null;
  readonly unit?: string | null;
  readonly value?: unknown;
};

/** 분석 결과 한 건에 적용되는 지표별 표시 배율과, 그 배율을 쓰는 표시 함수 묶음이다. */
export interface AnalysisValueScale {
  /** 서버 unit이 통화인지 판별한다. 통화가 아니면 배율을 적용하지 않는다. */
  isCurrency(unit?: string | null): boolean;
  /** 값을 해당 지표의 확정 배율로 표시한다. 통화가 아니면 기존 숫자 표기를 그대로 쓴다. */
  format(value: unknown, unit?: string | null, field?: string | null): string;
  /** 화면에 붙일 단위 문자열을 반환한다. 통화는 해당 지표의 확정 배율 라벨로 치환한다. */
  unitLabel(unit?: string | null, field?: string | null): string | null;
  /** 손실 없는 원본 금액 표기(툴팁·title 용). 배율을 적용하지 않는다. */
  exact(value: unknown, unit?: string | null): string;
  /** 주어진 통화 field들이 모두 같은 배율이면 그 배율 라벨을, 아니면 null을 반환한다(차트 축 통일 판정용). */
  sharedCurrencyLabel(fields: readonly string[]): string | null;
}

/**
 * 지표별 통화 배율 표를 만든다. `rows`는 항목별 분해 값이며, 합계와 함께 넣어야
 * 전체 합계 카드와 항목 카드·표 셀이 같은 배율로 읽힌다.
 */
export function createAnalysisValueScale(
  metrics: readonly ScaleMetricInput[],
  rows: ReadonlyArray<Record<string, unknown>>,
): AnalysisValueScale {
  const unitByField = new Map<string, ResolvedUnit>();
  for (const metric of metrics) {
    const field = metric.resultField;
    if (!field || !isCurrencyMetricUnit(metric.unit) || unitByField.has(field)) continue;
    const values: unknown[] = [];
    if (metric.value !== undefined && metric.value !== null) values.push(metric.value);
    for (const row of rows) {
      const cell = row[field];
      if (cell !== undefined && cell !== null) values.push(cell);
    }
    unitByField.set(field, chooseDisplayUnit(values));
  }

  // field를 특정할 수 없는 호출(차트 축 등)을 위한 기본 배율. 통화 지표가 하나뿐일 때 그 배율을 그대로 쓴다.
  const distinct = new Set(unitByField.values());
  const fallbackUnit: ResolvedUnit = distinct.size === 1 ? [...distinct][0] : "one";
  const unitFor = (field?: string | null): ResolvedUnit => (
    field && unitByField.has(field) ? unitByField.get(field)! : fallbackUnit
  );

  return {
    isCurrency: (unit) => isCurrencyMetricUnit(unit),
    format(value, unit, field) {
      if (!isCurrencyMetricUnit(unit)) return formatMetricValue(value, { includeUnit: false });
      return formatCurrencyAmount(value, unitFor(field), { maximumFractionDigits: 1 });
    },
    unitLabel(unit, field) {
      if (!unit) return null;
      return isCurrencyMetricUnit(unit) ? currencyDisplayLabel(unitFor(field)) : unit;
    },
    exact: (value, unit) => formatMetricValue(value, { unit: unit ?? undefined }),
    sharedCurrencyLabel(fields) {
      if (fields.length === 0) return null;
      const units = fields.map((field) => (unitByField.has(field) ? unitByField.get(field)! : null));
      if (units.some((unit) => unit === null)) return null;
      return new Set(units).size === 1 ? currencyDisplayLabel(units[0]!) : null;
    },
  };
}

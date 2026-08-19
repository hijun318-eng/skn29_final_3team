import assert from "node:assert/strict";

import {
  REPORT_CURRENCY_OPTIONS,
  currencyDisplayLabel,
  formatCurrencyAmount,
  isCurrencyMetricUnit,
  resolveCurrencyDisplayUnit,
} from "../../app/frontend/src/features/reports/reportCurrency.ts";

const policy = { displayUnit: "auto", maximumFractionDigits: 1 };

assert.equal(isCurrencyMetricUnit("원"), true);
assert.equal(isCurrencyMetricUnit(" KRW "), true);
assert.equal(isCurrencyMetricUnit("%"), false);
assert.equal(resolveCurrencyDisplayUnit([1_260_000_000, 1_300_000_000], policy), "hundredMillion");
assert.equal(resolveCurrencyDisplayUnit([84_000], policy), "thousand");
assert.equal(resolveCurrencyDisplayUnit([12.4, null, "—"], policy), "one");
assert.equal(resolveCurrencyDisplayUnit([1_260_000_000], { displayUnit: "million" }), "million");
assert.equal(currencyDisplayLabel("hundredMillion"), "억 원");
assert.equal(formatCurrencyAmount(1_260_000_000, "hundredMillion", policy), "12.6");
assert.equal(formatCurrencyAmount(1_260_000_000, "hundredMillion", policy, true), "12.6 억 원");
assert.equal(formatCurrencyAmount(84_000, "one", policy, true), "84,000 원");
assert.equal(formatCurrencyAmount(null, "one", policy), "—");
assert.deepEqual(REPORT_CURRENCY_OPTIONS.map(({ value }) => value), ["auto", "one", "thousand", "million", "hundredMillion"]);

console.log("frontend report currency tests passed");

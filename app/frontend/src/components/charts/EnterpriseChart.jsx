/** 검증된 분석 표 field를 접근 가능한 Recharts 시각화로 표현하는 모듈이다. */
import { useId, useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Label, LabelList, Line,
  LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { formatCompactNumber, formatMetricValue, seriesColor } from "../../utils/presentation";

const ISO_PERIOD = /^\d{4}-\d{2}(?:-\d{2})?$/;
const MAX_CIRCULAR_ITEMS = 8;
const CATEGORY_AXIS_TICK = { className: "enterprise-chart-axis-tick enterprise-chart-axis-tick--category" };
const VALUE_AXIS_TICK = { className: "enterprise-chart-axis-tick enterprise-chart-axis-tick--value" };
const CHART_TYPES = new Set(["bar", "horizontal-bar", "line", "area", "stacked-bar", "donut", "pie"]);
const CHART_TYPE_LABELS = {
  area: "영역",
  bar: "세로 막대",
  donut: "도넛",
  "horizontal-bar": "가로 막대",
  line: "선",
  pie: "원형",
  "stacked-bar": "누적 막대",
};

/** 서버 차트 타입의 표기 차이만 정규화하며 미지원 타입은 null로 fail-closed 처리한다. */
export function normalizeChartType(value) {
  const normalized = String(value ?? "").trim().toLocaleLowerCase("en-US").replaceAll("_", "-");
  return CHART_TYPES.has(normalized) ? normalized : null;
}

/** 막대 계열의 실제 최솟값·최댓값을 기준으로 0 기준선이 항상 domain에 포함되도록 한다. */
export function resolveBarValueDomain(rows, series) {
  const values = rows.flatMap((row) => series
    .map((item) => chartNumber(row?.[item.key]))
    .filter((value) => value !== null));
  if (!values.length) return [0, "auto"];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  if (minimum >= 0) return [0, "auto"];
  if (maximum <= 0) return ["auto", 0];
  return ["auto", "auto"];
}

function orderedRows(data, xKey) {
  if (!data.length || !xKey || !data.every((row) => row && typeof row === "object" && ISO_PERIOD.test(String(row[xKey] ?? "")))) return data;
  return [...data].sort((left, right) => String(left[xKey]).localeCompare(String(right[xKey])));
}

function categoryLabel(value, maximumLength = 14) {
  const text = String(value ?? "—");
  const characters = [...text];
  return characters.length > maximumLength ? `${characters.slice(0, maximumLength - 1).join("")}…` : text;
}

function chartNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

/** 차트 계약을 충족하지 못한 입력을 임의 시각화하지 않고 상태 설명으로 닫는다. */
function ChartFallback({ title = "차트를 표시할 수 없습니다.", children }) {
  return <div className="enterprise-chart-fallback" role="status"><b>{title}</b><span>{children}</span></div>;
}

/** 활성 payload의 검증된 series만 값 formatter와 함께 표시한다. */
function ChartTooltip({ active, label, payload, series, valueFormatter, categoryDetailFormatter }) {
  if (!active || !payload?.length) return null;
  const visible = payload.filter((item) => item.value !== undefined && item.value !== null);
  if (!visible.length) return null;
  const rawHeading = label ?? visible[0]?.payload?.category;
  const heading = categoryDetailFormatter ? categoryDetailFormatter(rawHeading) : rawHeading;
  return <div className="enterprise-chart-tooltip" role="status">
    <small>{heading}</small>
    {visible.map((item) => {
      const definition = item.payload?.definition ?? series.find((entry) => entry.key === String(item.dataKey));
      return <div key={`${String(item.dataKey)}-${definition?.key ?? item.name}`}><i style={{ background: item.payload?.fill || definition?.color || item.color }} /><span>{definition?.label || item.name}</span><strong>{valueFormatter(item.value, definition)}</strong></div>;
    })}
  </div>;
}

/** Recharts가 제공한 중심 좌표가 있을 때만 donut 합계 라벨을 렌더링한다. */
function DonutCenterLabel({ viewBox, value, unit }) {
  if (!viewBox || !("cx" in viewBox) || !("cy" in viewBox)) return null;
  return <g aria-hidden="true">
    <text className="enterprise-chart-total-label" x={viewBox.cx} y={viewBox.cy - 3} textAnchor="middle">합계</text>
    <text className="enterprise-chart-total-value" x={viewBox.cx} y={viewBox.cy + 17} textAnchor="middle">{value}{unit ? ` ${unit}` : ""}</text>
  </g>;
}

/** 검증된 필드·수치 계열만 렌더링하고 계약 불일치 시 원본 표를 가리키는 상태 UI를 반환한다. */
export function EnterpriseChart({
  data = [],
  xKey,
  xLabel,
  series = [],
  type = "bar",
  height = 280,
  showLegend = true,
  interactiveLegend = false,
  valueFormatter = (value, item) => formatMetricValue(value, { unit: item?.unit }),
  axisFormatter = formatCompactNumber,
  labelFormatter = formatCompactNumber,
  categoryFormatter,
  categoryDetailFormatter,
  ariaLabel,
  description,
}) {
  const chartId = useId().replaceAll(":", "");
  const chartType = normalizeChartType(type);
  const [hiddenSeries, setHiddenSeries] = useState(() => new Set());
  const sourceRows = Array.isArray(data) ? data : [];
  const sourceSeries = Array.isArray(series) ? series : [];
  const rows = useMemo(() => orderedRows(sourceRows, xKey), [data, xKey]);
  const normalizedSeries = useMemo(() => sourceSeries.map((item, index) => ({ ...item, color: item.color || seriesColor(index) })), [series]);
  const descriptionId = `${chartId}-description`;
  const visibleSeriesCount = normalizedSeries.filter((item) => !hiddenSeries.has(item.key)).length;

  const toggleSeries = (key) => {
    setHiddenSeries((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else if (visibleSeriesCount > 1) next.add(key);
      return next;
    });
  };

  if (!chartType) {
    return <ChartFallback title="지원하지 않는 차트 형식입니다.">차트 형식을 확인하거나 연결된 데이터 표에서 값을 확인해 주세요.</ChartFallback>;
  }
  if (!rows.length || !normalizedSeries.length) {
    return <ChartFallback>연결된 데이터 표와 분석 조건을 확인해 주세요.</ChartFallback>;
  }
  const keys = normalizedSeries.map((item) => String(item?.key ?? "").trim());
  if (!xKey || rows.some((row) => !row || typeof row !== "object" || !Object.hasOwn(row, xKey)) || keys.some((key) => !key) || new Set(keys).size !== keys.length) {
    return <ChartFallback title="차트 필드 정보를 확인할 수 없습니다.">원본 필드 이름을 임의로 해석하지 않고 데이터 표를 유지합니다.</ChartFallback>;
  }
  const invalidValue = rows.some((row) => normalizedSeries.some((item) => {
    const value = row[item.key];
    return value !== null && value !== undefined && value !== "" && chartNumber(value) === null;
  }));
  if (invalidValue) {
    return <ChartFallback title="수치가 아닌 값은 차트로 표시할 수 없습니다.">원본 값은 연결된 데이터 표에서 확인해 주세요.</ChartFallback>;
  }

  const chartRows = rows.map((row) => ({
    ...row,
    ...Object.fromEntries(normalizedSeries.map((item) => [item.key, chartNumber(row[item.key])])),
  }));
  const hasNumericValue = chartRows.some((row) => normalizedSeries.some((item) => row[item.key] !== null));
  if (!hasNumericValue) {
    return <ChartFallback>선택한 계열에 표시할 수치가 없습니다.</ChartFallback>;
  }

  const isCircular = chartType === "donut" || chartType === "pie";
  if (isCircular && (normalizedSeries.length !== 1 || rows.length > MAX_CIRCULAR_ITEMS)) {
    return <ChartFallback title="원형 차트에 맞지 않는 데이터입니다.">원형 차트는 최대 {MAX_CIRCULAR_ITEMS}개 항목의 단일 수치 계열에 사용해 주세요. 여러 계열은 막대 차트가 더 정확합니다.</ChartFallback>;
  }
  const circularValues = isCircular ? chartRows.map((row) => row[normalizedSeries[0].key]) : [];
  if (isCircular && (circularValues.some((value) => value === null || value < 0) || !circularValues.some((value) => value > 0))) {
    return <ChartFallback title="원형 차트는 전체 대비 비중을 계산할 수 없습니다.">누락값·음수만 있거나 합계가 0인 경우 막대 차트 또는 데이터 표를 사용해 주세요.</ChartFallback>;
  }

  const circularData = isCircular ? chartRows.map((row, index) => ({
    category: String(categoryFormatter ? categoryFormatter(row[xKey]) : row[xKey] ?? "—"),
    definition: normalizedSeries[0],
    fill: seriesColor(index),
    value: row[normalizedSeries[0].key],
  })) : [];
  const commonUnits = [...new Set(normalizedSeries.map((item) => item.unit).filter(Boolean))];
  const commonUnit = commonUnits.length === 1 ? commonUnits[0] : "";
  if (chartType === "stacked-bar" && commonUnits.length > 1) {
    return <ChartFallback title="서로 다른 단위는 누적할 수 없습니다.">같은 단위의 계열만 선택하거나 묶은 막대 차트로 비교해 주세요.</ChartFallback>;
  }
  const showLabels = chartRows.length <= 8;
  const isBar = chartType === "bar" || chartType === "horizontal-bar" || chartType === "stacked-bar";
  const isHorizontal = chartType === "horizontal-bar";
  const isStacked = chartType === "stacked-bar";
  const compactCategoryChart = !isHorizontal && chartRows.length <= 4;
  const barValueDomain = isBar ? resolveBarValueDomain(chartRows, normalizedSeries) : undefined;
  const categoryLength = isHorizontal ? 18 : chartRows.length > 8 ? 8 : chartRows.length > 4 ? 10 : 14;
  const formatCategory = (value) => categoryLabel(
    categoryFormatter ? categoryFormatter(value) : value,
    categoryLength,
  );
  const margin = isHorizontal
    ? { top: commonUnit ? 26 : 16, right: showLabels && normalizedSeries.length === 1 ? 82 : 28, bottom: 10, left: 8 }
    : { top: showLabels && chartType === "bar" ? 32 : commonUnit ? 26 : 16, right: 16, bottom: 10, left: compactCategoryChart ? 0 : 12 };
  const categoryAxisWidth = Math.min(160, Math.max(76, Math.max(...chartRows.map((row) => [...formatCategory(row[xKey])].length)) * 7.4));
  const axes = isHorizontal ? <>
    <XAxis className="enterprise-chart-axis enterprise-chart-axis--value" type="number" axisLine={{ stroke: "var(--chart-axis)" }} tick={VALUE_AXIS_TICK} tickLine={false} tickMargin={11} tickFormatter={axisFormatter} domain={barValueDomain} />
    <YAxis className="enterprise-chart-axis enterprise-chart-axis--category" type="category" dataKey={xKey} name={xLabel} width={categoryAxisWidth} axisLine={false} tick={CATEGORY_AXIS_TICK} tickLine={false} tickMargin={11} interval={0} tickFormatter={formatCategory} />
  </> : <>
    <XAxis className="enterprise-chart-axis enterprise-chart-axis--category" dataKey={xKey} name={xLabel} height={40} axisLine={{ stroke: "var(--chart-axis)" }} tick={CATEGORY_AXIS_TICK} tickLine={false} tickMargin={12} minTickGap={chartRows.length > 8 ? 34 : 24} interval={compactCategoryChart ? 0 : "preserveStartEnd"} tickFormatter={formatCategory} padding={{ left: 8, right: 8 }} />
    <YAxis className="enterprise-chart-axis enterprise-chart-axis--value" width={compactCategoryChart ? 54 : 72} axisLine={false} tick={VALUE_AXIS_TICK} tickLine={false} tickMargin={8} tickFormatter={axisFormatter} domain={barValueDomain} />
  </>;
  const common = <>
    <CartesianGrid strokeDasharray="2 6" horizontal={!isHorizontal} vertical={isHorizontal} />
    {axes}
    <Tooltip cursor={isBar ? { fill: "var(--chart-cursor-fill)" } : { stroke: "var(--chart-cursor-stroke)", strokeDasharray: "3 4" }} content={<ChartTooltip series={normalizedSeries} valueFormatter={valueFormatter} categoryDetailFormatter={categoryDetailFormatter || categoryFormatter} />} />
  </>;

  let chart;
  if (chartType === "line") {
    chart = <LineChart data={chartRows} margin={margin} accessibilityLayer>{common}{normalizedSeries.map((item) => <Line key={item.key} type="monotone" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={3} connectNulls={false} dot={chartRows.length <= 12 ? { r: 3, fill: "var(--chart-dot-fill)", stroke: item.color, strokeWidth: 2 } : false} activeDot={{ r: 6, stroke: "var(--chart-active-dot-stroke)", strokeWidth: 2 }} hide={hiddenSeries.has(item.key)} isAnimationActive={false} />)}</LineChart>;
  } else if (chartType === "area") {
    chart = <AreaChart data={chartRows} margin={margin} accessibilityLayer>
      <defs>{normalizedSeries.map((item, index) => <linearGradient id={`${chartId}-area-${index}`} x1="0" y1="0" x2="0" y2="1" key={item.key}><stop offset="0%" stopColor={item.color} stopOpacity=".34" /><stop offset="100%" stopColor={item.color} stopOpacity=".035" /></linearGradient>)}</defs>
      {common}{normalizedSeries.map((item, index) => <Area key={item.key} type="monotone" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={2.5} fill={`url(#${chartId}-area-${index})`} connectNulls={false} dot={chartRows.length <= 10 ? { r: 2.5, fill: "var(--chart-dot-fill)", stroke: item.color, strokeWidth: 2 } : false} activeDot={{ r: 6, fill: item.color, stroke: "var(--chart-active-dot-stroke)", strokeWidth: 2 }} hide={hiddenSeries.has(item.key)} isAnimationActive={false} />)}
    </AreaChart>;
  } else if (isCircular) {
    const total = circularValues.reduce((sum, value) => sum + value, 0);
    chart = <PieChart accessibilityLayer>
      <Tooltip content={<ChartTooltip series={normalizedSeries} valueFormatter={valueFormatter} />} />
      <Pie data={circularData} dataKey="value" nameKey="category" cx="50%" cy="50%" innerRadius={chartType === "donut" ? "52%" : 0} outerRadius="78%" paddingAngle={chartType === "donut" ? 2 : 1} stroke="var(--chart-surface)" strokeWidth={2} isAnimationActive={false}>
        {circularData.map((item, index) => <Cell key={`${item.category}-${index}`} fill={item.fill} />)}
        {chartType === "donut" && <Label position="center" content={(props) => <DonutCenterLabel {...props} value={labelFormatter(total)} unit={commonUnit} />} />}
      </Pie>
    </PieChart>;
  } else {
    chart = <BarChart data={chartRows} margin={margin} layout={isHorizontal ? "vertical" : "horizontal"} barCategoryGap="26%" accessibilityLayer>
      <defs>{normalizedSeries.map((item, index) => <linearGradient id={`${chartId}-bar-${index}`} x1="0" y1="0" x2={isHorizontal ? "1" : "0"} y2={isHorizontal ? "0" : "1"} key={item.key}><stop offset="0%" stopColor={item.color} /><stop offset="100%" stopColor={item.color} stopOpacity=".72" /></linearGradient>)}</defs>
      {common}{normalizedSeries.map((item, index) => <Bar key={item.key} dataKey={item.key} name={item.label} stackId={isStacked ? "total" : undefined} fill={`url(#${chartId}-bar-${index})`} maxBarSize={64} radius={isStacked ? 0 : isHorizontal ? [2, 7, 7, 2] : [7, 7, 2, 2]} hide={hiddenSeries.has(item.key)} isAnimationActive={false}>{showLabels && !isStacked && normalizedSeries.length === 1 && <LabelList dataKey={item.key} position={isHorizontal ? "right" : "top"} formatter={(value) => chartNumber(value) === null ? "" : labelFormatter(chartNumber(value))} fill="var(--chart-label)" fontSize={11} fontWeight={750} />}</Bar>)}
    </BarChart>;
  }

  const legendItems = isCircular
    ? circularData.map((item, index) => ({ key: `${item.category}-${index}`, label: item.category, color: item.fill, value: valueFormatter(item.value, normalizedSeries[0]) }))
    : normalizedSeries;
  const canToggleLegend = interactiveLegend && !isCircular && normalizedSeries.length > 1;
  const legendClassName = [
    "enterprise-chart-legend",
    isCircular ? "is-category-legend" : "",
    canToggleLegend ? "is-interactive" : "",
  ].filter(Boolean).join(" ");
  const resolvedDescription = description || `${chartRows.length.toLocaleString("ko-KR")}개 항목의 ${normalizedSeries.map((item) => item.label).join(", ")}을 ${CHART_TYPE_LABELS[chartType]} 차트로 표시합니다.`;
  const resolvedAriaLabel = ariaLabel || `${xLabel || "항목"}별 ${normalizedSeries.map((item) => item.label).join(", ")} ${CHART_TYPE_LABELS[chartType]} 차트`;

  return <div className={`enterprise-chart enterprise-chart--${chartType}`} role="group" tabIndex={0} aria-label={resolvedAriaLabel} aria-describedby={descriptionId}>
    <span id={descriptionId} className="sr-only">{resolvedDescription}</span>
    {showLegend && <div className={legendClassName} role="list" aria-label="차트 범례">{legendItems.map((item) => {
      const hidden = hiddenSeries.has(item.key);
      const content = <><i style={{ background: item.color }} /><b>{item.label}</b>{item.value !== undefined ? <em>{item.value}</em> : item.unit && !commonUnit ? <em>{item.unit}</em> : null}</>;
      return <span role="listitem" key={item.key} className={hidden ? "is-hidden" : ""}>{canToggleLegend
        ? <button type="button" aria-pressed={!hidden} disabled={!hidden && visibleSeriesCount === 1} onClick={() => toggleSeries(item.key)} title={`${item.label} 계열 ${hidden ? "표시" : "숨기기"}`}>{content}</button>
        : content}</span>;
    })}</div>}
    <div className="enterprise-chart-plot">{commonUnit && <span className="enterprise-chart-axis-unit">단위: {commonUnit}</span>}<ResponsiveContainer width="100%" height={height} minWidth={0}>{chart}</ResponsiveContainer></div>
  </div>;
}

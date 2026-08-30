/** governed artifact의 summary·KPI·chart·table과 Markdown block을 렌더링하는 모듈이다. */
import { memo, useState } from "react";
import { AlertTriangle, ArrowUpDown, Inbox, LoaderCircle, RotateCcw, ShieldAlert } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { EnterpriseChart } from "../../../components/charts/EnterpriseChart";
import {
  dataProvenanceLabel,
  formatMetricDisplayValue,
  formatMetricValue,
  isNumericValue,
  metricDisplayUnit,
  metricUnitLabel,
  seriesColor,
} from "../../../utils/presentation";
import { frontendTextBlockLayout } from "../reportDraftV2";
import {
  formatCurrencyAmount,
  isCurrencyMetricUnit,
} from "../reportCurrency";
import { ReportWholeArtifactBlock } from "../ReportWholeArtifactBlock";
import { reportEvidenceLabel } from "../../../contracts/report";
import { sampleReportTableRows } from "../reportTableRows";
import {
  artifactMetric,
  blockSettings,
  reportColumnLabel,
  REPORT_CHART_OPTIONS,
} from "./reportPresentation";

const MARKDOWN_COMPONENTS = {
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
  input: ({ node: _node, ...props }) => <input {...props} disabled />,
};

function nextTableSort(current, column) {
  if (current.column !== column) return { column, direction: "asc" };
  if (current.direction === "asc") return { column, direction: "desc" };
  return { column: "", direction: "" };
}

function sortedTableRows(rows, sorting) {
  if (!sorting.column) return rows;
  return [...rows].sort((left, right) => {
    const leftValue = left[sorting.column];
    const rightValue = right[sorting.column];
    const leftNumber = Number(leftValue);
    const rightNumber = Number(rightValue);
    const comparison = Number.isFinite(leftNumber) && Number.isFinite(rightNumber)
      ? leftNumber - rightNumber
      : String(leftValue ?? "").localeCompare(
        String(rightValue ?? ""),
        "ko",
        { numeric: true },
      );
    return sorting.direction === "desc" ? -comparison : comparison;
  });
}

/** 허용된 Markdown 토큰만 React 요소로 렌더링하고 raw HTML은 해석하지 않는다. */
export const MarkdownText = memo(function MarkdownText({ content }) {
  return (
    <div className="generated-report-copy markdown-copy">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={MARKDOWN_COMPONENTS}
      >
        {content || ""}
      </ReactMarkdown>
    </div>
  );
});

/** 서버 source provenance에 synthetic 표시가 있을 때만 배지를 렌더링하는 memo 컴포넌트다. */
export const DataProvenanceBadge = memo(function DataProvenanceBadge({ artifact }) {
  const label = dataProvenanceLabel(artifact?.evidence?.sources ?? []);
  if (!label) return null;
  return (
    <span
      className="report-data-provenance"
      role="note"
      title="실제 호텔 운영 데이터가 아닌 교육·시연용 결과입니다."
    >
      <ShieldAlert size={12} aria-hidden="true" />
      <b>{label}</b>
      <span className="sr-only">실제 호텔 운영 데이터로 해석하지 마세요.</span>
    </span>
  );
});

/** artifact hydration의 loading/error/empty 상태와 허용된 재시도 명령을 표시한다. */
function ArtifactState({ artifactState, onRetry }) {
  if (!artifactState || artifactState.status === "loading") {
    return (
      <div className="report-artifact-state is-loading" role="status" aria-busy="true">
        <span className="report-artifact-skeleton" aria-hidden="true" />
        <LoaderCircle className="spin" size={16} aria-hidden="true" />
        <span>분석 데이터를 불러오는 중입니다.</span>
      </div>
    );
  }
  if (artifactState.status === "error") {
    return (
      <div className="report-artifact-state is-error" role="alert">
        <AlertTriangle size={17} aria-hidden="true" />
        <div>
          <b>이 블록의 분석 데이터를 불러오지 못했습니다.</b>
          <p>{artifactState.message || "다른 블록은 계속 확인할 수 있습니다."}</p>
          {onRetry && artifactState.requiredAction === "RETRY" && (
            <button type="button" onClick={onRetry}>
              <RotateCcw size={13} aria-hidden="true" />다시 불러오기
            </button>
          )}
        </div>
      </div>
    );
  }
  if (artifactState.status === "empty") {
    return (
      <div className="report-artifact-state is-empty" role="status">
        <Inbox size={17} aria-hidden="true" />
        <div>
          <b>조건에 맞는 데이터가 없습니다.</b>
          <p>오류가 아니라 유효한 빈 분석 결과입니다.</p>
        </div>
      </div>
    );
  }
  return null;
}

/** 지원되지 않거나 상세 표가 없는 artifact를 데이터 합성 없이 명시적으로 표시한다. */
function UnsupportedArtifact({ missingTable = false }) {
  return (
    <div className="report-artifact-state is-error" role="alert">
      <AlertTriangle size={missingTable ? 17 : 16} aria-hidden="true" />
      <div>
        <b>{missingTable ? "지원할 수 없는 분석 데이터 형식입니다." : "이 블록으로 표시할 데이터가 없습니다."}</b>
        <p>{missingTable ? "원본을 임의로 해석하지 않았습니다." : "표 블록으로 원본 데이터를 확인하거나 블록 설정을 검토해 주세요."}</p>
      </div>
    </div>
  );
}

/** 근거가 준비된 artifact view만 렌더링하며 memo 경계가 다른 블록의 편집을 격리한다. */
export const ReportArtifactContent = memo(function ReportArtifactContent({
  block,
  artifact,
  artifactState,
  currency,
  editor = false,
  paper = false,
  onRetry,
}) {
  const [sorting, setSorting] = useState({ column: "", direction: "" });
  const state = <ArtifactState artifactState={artifactState} onRetry={onRetry} />;
  if (!artifactState || ["loading", "error", "empty"].includes(artifactState.status)) {
    return state;
  }
  if (!artifact?.table) return <UnsupportedArtifact missingTable />;

  if (block.type === "table") {
    const settings = blockSettings(block);
    const showRowNumbers = settings.showRowNumbers === true;
    const mobileFit = artifact.table.columns.length + Number(showRowNumbers) <= 3;
    const rows = sortedTableRows(artifact.table.rows, sorting);
    const visibleRows = sampleReportTableRows(rows);
    const tableClass = [
      "analysis-table generated-report-table",
      editor ? "editor-artifact-table" : "",
      mobileFit ? "mobile-fit-table" : "",
      settings.density === "compact" ? "is-compact" : "",
    ].filter(Boolean).join(" ");
    return (
      <div
        tabIndex={0}
        aria-label={`${block.title} 데이터 표. 표가 넓으면 좌우로 스크롤할 수 있습니다.`}
        className={tableClass}
      >
        <table>
          <caption className="sr-only">{block.title}</caption>
          <thead>
            <tr>
              {showRowNumbers && <th scope="col">#</th>}
              {artifact.table.columns.map((column) => {
                const label = reportColumnLabel(artifact, column);
                const metric = artifactMetric(artifact, column);
                const sourceUnit = metric?.unit;
                const unit = isCurrencyMetricUnit(sourceUnit)
                  ? currency.label
                  : metricDisplayUnit(sourceUnit, metric?.display_unit ?? metric?.displayUnit);
                const numeric = artifact.table.rows.some((row) => isNumericValue(row[column]));
                return (
                  <th
                    scope="col"
                    aria-sort={sorting.column === column
                      ? (sorting.direction === "asc" ? "ascending" : "descending")
                      : "none"}
                    className={numeric ? "is-numeric" : ""}
                    key={column}
                  >
                    <button
                      type="button"
                      className="report-table-sort"
                      aria-label={`${metricUnitLabel(label, unit)} 열 정렬`}
                      onClick={() => setSorting((current) => nextTableSort(current, column))}
                    >
                      <span>{label}{unit && <small className="analysis-column-unit">{unit}</small>}</span>
                      <ArrowUpDown size={12} aria-hidden="true" />
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map(({ row, sourceIndex }) => (
              <tr key={sourceIndex}>
                {showRowNumbers && <th scope="row">{sourceIndex + 1}</th>}
                {artifact.table.columns.map((column) => {
                  const sourceUnit = artifactMetric(artifact, column)?.unit;
                  const value = isCurrencyMetricUnit(sourceUnit)
                    ? formatCurrencyAmount(row[column], currency.unit, currency.policy)
                    : formatMetricValue(row[column], { includeUnit: false });
                  return (
                    <td className={isNumericValue(row[column]) ? "is-numeric" : ""} key={column}>
                      {value}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > visibleRows.length && (
          <p className="report-table-sample-note" role="note">
            전체 {rows.length}행 중 {visibleRows.length}개 대표 행을 첫·마지막 포함 균등 표시합니다.
            전체 값은 원본 Artifact에서 확인할 수 있습니다.
          </p>
        )}
      </div>
    );
  }

  if (block.type === "chart" && artifact.chart && artifact.table.rows.length) {
    const settings = blockSettings(block);
    const chartType = settings.chartType || artifact.chart.chart_type || artifact.chart.type || "bar";
    const showLegend = settings.showLegend !== false;
    const series = artifact.chart.y_fields.map((field, index) => {
      const metric = artifactMetric(artifact, field);
      const sourceUnit = metric?.unit;
      const currencyMetric = isCurrencyMetricUnit(sourceUnit);
      const displayUnit = currencyMetric
        ? currency.label
        : metricDisplayUnit(sourceUnit, metric?.display_unit ?? metric?.displayUnit);
      return {
        key: field,
        label: reportColumnLabel(artifact, field),
        color: seriesColor(index),
        sourceUnit,
        displayUnit,
        currencyMetric,
        unit: displayUnit,
      };
    });
    const allCurrency = series.every((item) => item.currencyMetric);
    const chartLabel = REPORT_CHART_OPTIONS.find(([value]) => value === chartType)?.[1] || "차트";
    const description = `${artifact.table.rows.length}개 데이터 행을 ${chartLabel}로 표시합니다. 같은 Artifact의 표 보기에서 원본 값을 확인할 수 있습니다.`;
    const chartHeight = paper
      ? Math.max(112, Math.min(210, (block.h ?? 7) * 19))
      : editor ? 240 : 280;
    const currencyFormatters = allCurrency ? {
      axisFormatter: (value) => formatCurrencyAmount(value, currency.unit, currency.policy),
      labelFormatter: (value) => formatCurrencyAmount(value, currency.unit, currency.policy),
    } : {};
    return (
      <figure
        className={`generated-report-chart-live ${editor ? "editor-artifact-chart" : ""} ${paper ? "is-paper-chart" : ""}`}
        aria-label={`${block.title} 차트`}
      >
        <EnterpriseChart
          data={artifact.table.rows}
          xKey={artifact.chart.x_field}
          xLabel={reportColumnLabel(artifact, artifact.chart.x_field)}
          series={series}
          type={chartType}
          height={chartHeight}
          showLegend={showLegend}
          valueFormatter={(value, item) => item?.currencyMetric
            ? formatCurrencyAmount(value, currency.unit, currency.policy)
            : formatMetricDisplayValue(value, {
                unit: item?.sourceUnit,
                displayUnit: item?.displayUnit,
              })}
          {...currencyFormatters}
          ariaLabel={`${block.title} ${chartLabel}`}
          description={description}
        />
        <figcaption className="sr-only">{description}</figcaption>
      </figure>
    );
  }

  return <UnsupportedArtifact />;
});

/** 최종/미리보기 블록을 표시 정책에 맞춰 렌더링하고 입력 객체가 같으면 재사용한다. */
export const GeneratedReportBlock = memo(function GeneratedReportBlock({
  block,
  number,
  rowOffset,
  artifact,
  artifactState,
  currency,
  orientation,
  onRetry,
}) {
  const isArtifactView = block.type === "table" || block.type === "chart";
  const textLayout = frontendTextBlockLayout(block, orientation);
  let content = <MarkdownText content={block.content} />;
  if (isArtifactView) {
    content = (
      <ReportArtifactContent
        block={block}
        artifact={artifact}
        artifactState={artifactState}
        currency={currency}
        paper
        onRetry={onRetry}
      />
    );
  }
  if (block.type === "artifact") {
    content = (
      <ReportWholeArtifactBlock
        block={block}
        artifact={artifact}
        artifactState={artifactState}
        currency={currency}
        renderView={(type, options = {}) => (
          <ReportArtifactContent
            block={{ ...block, type, h: options.height ?? block.h }}
            artifact={options.artifact || artifact}
            artifactState={artifactState}
            currency={currency}
            paper
            onRetry={onRetry}
          />
        )}
      />
    );
  }
  return (
    <article
      className={`card generated-report-block ${block.type === "artifact" ? "is-whole-artifact" : ""} ${textLayout.overflow ? "has-content-overflow" : ""}`}
      style={{
        "--report-block-width": block.w ?? block.columns,
        "--block-x": (block.x ?? 0) + 1,
        "--block-y": Math.max(0, (block.y ?? 0) - rowOffset) + 1,
        "--block-w": block.w ?? block.columns,
        "--block-h": block.h ?? 1,
      }}
    >
      <header>
        <span>{String(number).padStart(2, "0")}</span>
        <div><small>보고서 섹션</small><h2>{block.title}</h2></div>
        {block.type !== "text" && <DataProvenanceBadge artifact={artifact} />}
      </header>
      {content}
      {block.type === "text" && block.evidenceRefs?.length ? (
        <p className="report-text-evidence" role="note">
          근거 · {block.evidenceRefs.map(reportEvidenceLabel).join(" · ")}
        </p>
      ) : null}
      {textLayout.overflow && (
        <p className="report-content-overflow-note" role="note">
          내용이 한 페이지를 초과합니다. 편집 화면에서 문단을 나누어 전체 내용을 표시하세요.
        </p>
      )}
    </article>
  );
});

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ArrowUpDown, Bold, Check,
  ChevronRight, Clock3, Columns2, Copy, Download, ExternalLink, Eye, FileBarChart, FilePlus2,
  GripVertical, Heading2, Inbox, Italic, Link2, List, ListChecks, LoaderCircle,
  LockKeyhole, Maximize2, Minimize2, Minus, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Plus,
  Quote, Redo2, RotateCcw, Save, Send, ShieldAlert, Sparkles, Table2, Trash2,
  Type, Undo2,
} from "lucide-react";
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, TouchSensor, useDraggable,
  useSensor, useSensors,
} from "@dnd-kit/core";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { createAnalysisClient } from "../api/analysisClient";
import { createReportClient, ReportApiError } from "../api/reportClient";
import { EnterpriseChart } from "../components/charts/EnterpriseChart";
import { ReportPageCanvas } from "../features/reports/ReportPageCanvas";
import { ReportArtifactLibraryTile, ReportWholeArtifactBlock } from "../features/reports/ReportWholeArtifactBlock";
import {
  DEFAULT_FRONTEND_CURRENCY_POLICY, WHOLE_ARTIFACT_VIEWS, adaptAnalysisRunArtifact, analysisArtifactTitle,
  analysisRunArtifactSources, createFrontendDraftSnapshot, deleteFrontendBlock,
  artifactMetricCards, artifactViewBlockSettings, estimateArtifactBlockLayout, estimateArtifactViewBlockLayout,
  fitFrontendArtifactBlock, fitFrontendArtifactViewBlock, frontendTextBlockLayout, insertFrontendArtifact,
  keyboardEndDropPosition, loadFrontendDraft, moveFrontendBlock, orientFrontendBlocks,
  reportArtifactLibrarySources, saveFrontendDraft, wholeArtifactSettings,
} from "../features/reports/reportDraftV2";
import {
  REPORT_CURRENCY_OPTIONS, currencyDisplayLabel, formatCurrencyAmount, isCurrencyMetricUnit,
  resolveCurrencyDisplayUnit,
} from "../features/reports/reportCurrency";
import { compactDraftLayout, placeDraftBlock, restoreDraftLayout, seoulWallClockToIso, toReportBlockRequest } from "../contracts/report";
import { createUuid } from "../utils/createUuid";
import { dataProvenanceLabel, formatMetricValue, isNumericValue, metricUnitLabel, seriesColor } from "../utils/presentation";

function apiError(error) {
  if (error instanceof ReportApiError) return error.message;
  if (error instanceof TypeError) return "서버에 연결할 수 없습니다. 네트워크 연결을 확인한 뒤 다시 시도해 주세요.";
  return error instanceof Error ? error.message : "보고서 요청을 처리하지 못했습니다.";
}

function apiRequiredAction(error) {
  if (error instanceof ReportApiError) return error.requiredAction;
  if (error && typeof error.requiredAction === "string") return error.requiredAction;
  if (error instanceof TypeError) return "RETRY";
  return "NONE";
}

function formatSeoulTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(value));
}

function statusLabel(status) {
  return status === "approved" ? "확정" : "초안";
}

function runStatusLabel(status) {
  return ({ queued: "대기 중", running: "실행 중", success: "완료", partial: "일부 완료", failed: "실패", cancelled: "취소됨" })[String(status || "").toLowerCase()] || "확인 필요";
}

function MarkdownText({ content }) {
  return <div className="generated-report-copy markdown-copy"><ReactMarkdown
    remarkPlugins={[remarkGfm]}
    skipHtml
    components={{
      a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
      input: ({ node: _node, ...props }) => <input {...props} disabled />,
    }}
  >{content || ""}</ReactMarkdown></div>;
}

function artifactMetric(artifact, resultField) {
  return artifact?.evidence?.metrics?.find((metric) => metric.result_field === resultField);
}

const REPORT_DIMENSION_LABELS = {
  month: "월", business_date: "일자", date: "일자", actual_checkout_at: "체크아웃 시점",
  ordered_at: "주문 시점", property_id: "호텔", membership_grade_code: "회원 등급", room_type_code: "객실 유형",
};

function reportColumnLabel(artifact, column) {
  return artifactMetric(artifact, column)?.label || REPORT_DIMENSION_LABELS[column] || "구분";
}

function artifactCurrencyValues(artifact) {
  const fields = new Set((artifact?.evidence?.metrics ?? [])
    .filter((metric) => isCurrencyMetricUnit(metric.unit))
    .map((metric) => metric.result_field));
  const tableValues = (artifact?.table?.rows ?? []).flatMap((row) => [...fields].map((field) => row[field]));
  const cardValues = artifactMetricCards(artifact)
    .filter((metric) => isCurrencyMetricUnit(metric.unit))
    .map((metric) => metric.value);
  return [...tableValues, ...cardValues];
}

function ReportCurrencyControl({ value, onChange, disabled = false }) {
  return <label className="report-currency-control"><span>금액 단위</span><select aria-label="보고서 금액 단위" value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>{REPORT_CURRENCY_OPTIONS.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label>;
}

function reportEvidenceReady(artifact) {
  const evidence = artifact?.evidence;
  const metricFields = new Set((evidence?.metrics ?? []).map((metric) => metric.result_field));
  return Boolean(
    artifact?.artifact_id
    && artifact?.query_id
    && evidence?.artifact_id === artifact.artifact_id
    && evidence?.query_id === artifact.query_id
    && evidence?.period?.start
    && evidence?.period?.end_exclusive
    && evidence?.sources?.length
    && evidence?.gates?.g1 === "PASSED"
    && evidence?.gates?.g2 === "PASSED"
    && evidence?.gates?.g3 === "PASSED"
    && (!artifact.chart || (
      artifact.table?.columns?.includes(artifact.chart.x_field)
      && artifact.chart.y_fields?.length
      && artifact.chart.y_fields.every((field) => artifact.table.columns.includes(field) && metricFields.has(field))
    ))
  );
}

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
      : String(leftValue ?? "").localeCompare(String(rightValue ?? ""), "ko", { numeric: true });
    return sorting.direction === "desc" ? -comparison : comparison;
  });
}

const REPORT_RUN_PAGE_SIZE = 10;

const REPORT_TEMPLATES = [
  { id: "text", title: "텍스트", description: "문단·목록·Markdown", icon: Type, blockTitle: "새 텍스트", content: "새 문단을 작성하세요.", w: 12, h: 4 },
  { id: "section", title: "섹션", description: "소제목이 있는 문단", icon: Heading2, blockTitle: "새 섹션", content: "## 새 섹션\n섹션 내용을 입력하세요.", w: 12, h: 4 },
  { id: "executive", title: "경영진 요약", description: "결론과 비즈니스 영향", icon: Sparkles, blockTitle: "경영진 요약", content: "## 핵심 결론\n가장 중요한 결과를 한 문장으로 정리하세요.\n\n## 비즈니스 영향\n의사결정에 미치는 영향을 작성하세요.", w: 12, h: 5 },
  { id: "kpi", title: "핵심 지표", description: "수치와 의미를 한눈에", icon: Columns2, blockTitle: "핵심 지표", content: "| 지표 | 값 | 의미 |\n| --- | ---: | --- |\n| 핵심 지표 | 값 입력 | 의미를 작성하세요 |", w: 6, h: 5 },
  { id: "insight", title: "핵심 인사이트", description: "해석을 강조하는 콜아웃", icon: Quote, blockTitle: "핵심 인사이트", content: "> 데이터가 말하는 핵심 변화와 그 의미를 간결하게 작성하세요.", w: 6, h: 4 },
  { id: "actions", title: "권고 사항", description: "실행 항목과 후속 조치", icon: List, blockTitle: "권고 사항", content: "- [ ] 우선 실행할 조치\n- [ ] 담당자와 기한 확인\n- [ ] 후속 지표 모니터링", w: 6, h: 4 },
];

const ARTIFACT_TEMPLATES = [
  { id: "artifact-table", title: "표 보기만", description: "Artifact의 상세 행만 삽입", icon: Table2, w: 12, h: 5 },
  { id: "artifact-chart", title: "차트 보기만", description: "Artifact의 차트만 삽입", icon: FileBarChart, w: 12, h: 7 },
];

const WHOLE_ARTIFACT_TEMPLATE = {
  id: "artifact-whole", title: "Artifact 전체", description: "요약·KPI·차트·표를 한 블록으로", icon: FileBarChart,
};

const REPORT_CHART_OPTIONS = [
  ["bar", "세로 막대"], ["horizontal-bar", "가로 막대"], ["line", "선"],
  ["area", "영역"], ["stacked-bar", "누적 막대"], ["donut", "도넛"], ["pie", "원형"],
];

const REPORT_PAGE_ROWS = { landscape: 18, portrait: 30 };

function paginateReportBlocks(blocks, orientation, documentId = "report") {
  const rowLimit = REPORT_PAGE_ROWS[orientation] || REPORT_PAGE_ROWS.landscape;
  const rows = [...blocks]
    .sort((left, right) => (left.y ?? 0) - (right.y ?? 0) || (left.x ?? 0) - (right.x ?? 0))
    .reduce((groups, block) => {
      const y = block.y ?? 0;
      const current = groups.at(-1);
      if (current?.sourceY === y) current.blocks.push(block);
      else groups.push({ sourceY: y, blocks: [block] });
      return groups;
    }, []);
  const pages = [];
  let page = null;
  let cursorY = 0;
  const startPage = (sourceY = 0) => {
    page = {
      id: `${documentId}:page:${pages.length + 1}`,
      index: pages.length,
      orientation,
      offsetY: sourceY,
      blocks: [],
    };
    pages.push(page);
    cursorY = 0;
  };
  for (const row of rows) {
    const height = Math.min(rowLimit, Math.max(...row.blocks.map((block) => block.h ?? 1)));
    if (!page || (page.blocks.length && cursorY + height > rowLimit)) startPage(row.sourceY);
    for (const sourceBlock of row.blocks) {
      page.blocks.push({ ...sourceBlock, y: cursorY, h: height, sourceBlock });
    }
    cursorY += height;
  }
  if (!pages.length) startPage(0);
  return pages;
}

const REPORT_TEMPLATE_MAP = new Map([...REPORT_TEMPLATES, ...ARTIFACT_TEMPLATES].map((template) => [template.id, template]));

const MARKDOWN_INSERT_COMMANDS = [
  { id: "heading", title: "소제목", description: "내용을 구분하는 2단계 제목", aliases: ["제목", "heading", "h2"], group: "텍스트", shortcut: "##", icon: Heading2, content: "## 소제목" },
  { id: "list", title: "글머리 목록", description: "항목을 빠르게 나열", aliases: ["목록", "list", "bullet"], group: "텍스트", shortcut: "-", icon: List, content: "- 목록 항목" },
  { id: "checklist", title: "체크리스트", description: "실행 항목과 후속 조치", aliases: ["할 일", "todo", "check"], group: "텍스트", shortcut: "[]", icon: ListChecks, content: "- [ ] 할 일" },
  { id: "quote", title: "인사이트", description: "핵심 해석을 강조", aliases: ["인용", "quote", "callout"], group: "텍스트", shortcut: ">", icon: Quote, content: "> 핵심 인사이트" },
  { id: "table", title: "Markdown 표", description: "간단한 비교 표 삽입", aliases: ["표", "table", "grid"], group: "구조", shortcut: "|", icon: Table2, content: "| 항목 | 값 |\n| --- | ---: |\n| 지표 | 값 입력 |" },
  { id: "divider", title: "구분선", description: "문서 흐름을 시각적으로 분리", aliases: ["선", "divider", "rule"], group: "구조", shortcut: "---", icon: Minus, content: "---" },
];

function markdownSlashContext(content, cursor) {
  const from = content.lastIndexOf("\n", Math.max(0, cursor - 1)) + 1;
  const line = content.slice(from, cursor);
  const match = line.match(/^\/([^\s/]*)$/);
  return match ? { from, to: cursor, query: match[1].toLocaleLowerCase("ko-KR") } : null;
}

function blockSettings(block) {
  if (block.type === "text" || !block.content) return {};
  try {
    const parsed = JSON.parse(block.content);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function DataProvenanceBadge({ artifact }) {
  const label = dataProvenanceLabel(artifact?.evidence?.sources ?? []);
  if (!label) return null;
  return <span className="report-data-provenance" role="note" title="실제 호텔 운영 데이터가 아닌 교육·시연용 결과입니다."><ShieldAlert size={12} aria-hidden="true" /><b>{label}</b><span className="sr-only">실제 호텔 운영 데이터로 해석하지 마세요.</span></span>;
}

function ReportArtifactContent({ block, artifact, artifactState, currency, editor = false, paper = false, onRetry }) {
  const [sorting, setSorting] = useState({ column: "", direction: "" });
  if (!artifactState || artifactState.status === "loading") {
    return <div className="report-artifact-state is-loading" role="status" aria-busy="true"><span className="report-artifact-skeleton" aria-hidden="true" /><LoaderCircle className="spin" size={16} aria-hidden="true" /><span>분석 데이터를 불러오는 중입니다.</span></div>;
  }
  if (artifactState.status === "error") {
    return <div className="report-artifact-state is-error" role="alert"><AlertTriangle size={17} aria-hidden="true" /><div><b>이 블록의 분석 데이터를 불러오지 못했습니다.</b><p>{artifactState.message || "다른 블록은 계속 확인할 수 있습니다."}</p>{onRetry && artifactState.requiredAction === "RETRY" && <button type="button" onClick={onRetry}><RotateCcw size={13} aria-hidden="true" />다시 불러오기</button>}</div></div>;
  }
  if (artifactState.status === "empty") {
    return <div className="report-artifact-state is-empty" role="status"><Inbox size={17} aria-hidden="true" /><div><b>조건에 맞는 데이터가 없습니다.</b><p>오류가 아니라 유효한 빈 분석 결과입니다.</p></div></div>;
  }
  if (!artifact?.table) {
    return <div className="report-artifact-state is-error" role="alert"><AlertTriangle size={17} aria-hidden="true" /><div><b>지원할 수 없는 분석 데이터 형식입니다.</b><p>원본을 임의로 해석하지 않았습니다.</p></div></div>;
  }
  if (block.type === "table") {
    const settings = blockSettings(block);
    const showRowNumbers = settings.showRowNumbers === true;
    const mobileFit = artifact.table.columns.length + Number(showRowNumbers) <= 3;
    const rows = sortedTableRows(artifact.table.rows, sorting);
    return <div tabIndex={0} aria-label={`${block.title} 데이터 표. 표가 넓으면 좌우로 스크롤할 수 있습니다.`} className={`analysis-table generated-report-table ${editor ? "editor-artifact-table" : ""} ${mobileFit ? "mobile-fit-table" : ""} ${settings.density === "compact" ? "is-compact" : ""}`}><table><caption className="sr-only">{block.title}</caption><thead><tr>{showRowNumbers && <th scope="col">#</th>}{artifact.table.columns.map((column) => { const label = reportColumnLabel(artifact, column); const sourceUnit = artifactMetric(artifact, column)?.unit; const currencyMetric = isCurrencyMetricUnit(sourceUnit); const unit = currencyMetric ? currency.label : sourceUnit; return <th scope="col" aria-sort={sorting.column === column ? (sorting.direction === "asc" ? "ascending" : "descending") : "none"} className={artifact.table.rows.some((row) => isNumericValue(row[column])) ? "is-numeric" : ""} key={column}><button type="button" className="report-table-sort" aria-label={`${metricUnitLabel(label, unit)} 열 정렬`} onClick={() => setSorting((current) => nextTableSort(current, column))}><span>{label}{unit && <small className="analysis-column-unit">{unit}</small>}</span><ArrowUpDown size={12} aria-hidden="true" /></button></th>; })}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{showRowNumbers && <th scope="row">{index + 1}</th>}{artifact.table.columns.map((column) => { const sourceUnit = artifactMetric(artifact, column)?.unit; const value = isCurrencyMetricUnit(sourceUnit) ? formatCurrencyAmount(row[column], currency.unit, currency.policy) : formatMetricValue(row[column], { includeUnit: false }); return <td className={isNumericValue(row[column]) ? "is-numeric" : ""} key={column}>{value}</td>; })}</tr>)}</tbody></table></div>;
  }
  if (block.type === "chart" && artifact.chart && artifact.table.rows.length) {
    const settings = blockSettings(block);
    const chartType = settings.chartType || artifact.chart.chart_type || artifact.chart.type || "bar";
    const yFields = artifact.chart.y_fields;
    const showLegend = settings.showLegend !== false;
    const series = yFields.map((field, index) => ({
      key: field,
      label: reportColumnLabel(artifact, field),
      color: seriesColor(index),
      sourceUnit: artifactMetric(artifact, field)?.unit,
      currencyMetric: isCurrencyMetricUnit(artifactMetric(artifact, field)?.unit),
      unit: isCurrencyMetricUnit(artifactMetric(artifact, field)?.unit) ? currency.label : artifactMetric(artifact, field)?.unit,
    }));
    const allCurrency = series.every((item) => item.currencyMetric);
    const chartLabel = REPORT_CHART_OPTIONS.find(([value]) => value === chartType)?.[1] || "차트";
    const description = `${artifact.table.rows.length}개 데이터 행을 ${chartLabel}로 표시합니다. 같은 Artifact의 표 보기에서 원본 값을 확인할 수 있습니다.`;
    const chartHeight = paper ? Math.max(112, Math.min(210, (block.h ?? 7) * 19)) : editor ? 240 : 280;
    return <figure className={`generated-report-chart-live ${editor ? "editor-artifact-chart" : ""} ${paper ? "is-paper-chart" : ""}`} aria-label={`${block.title} 차트`}><EnterpriseChart data={artifact.table.rows} xKey={artifact.chart.x_field} xLabel={reportColumnLabel(artifact, artifact.chart.x_field)} series={series} type={chartType} height={chartHeight} showLegend={showLegend} valueFormatter={(value, item) => item?.currencyMetric ? formatCurrencyAmount(value, currency.unit, currency.policy) : formatMetricValue(value, { unit: item?.unit })} {...(allCurrency ? { axisFormatter: (value) => formatCurrencyAmount(value, currency.unit, currency.policy), labelFormatter: (value) => formatCurrencyAmount(value, currency.unit, currency.policy) } : {})} ariaLabel={`${block.title} ${chartLabel}`} description={description} /><figcaption className="sr-only">{description}</figcaption></figure>;
  }
  return <div className="report-artifact-state is-error" role="alert"><AlertTriangle size={16} aria-hidden="true" /><div><b>이 블록으로 표시할 데이터가 없습니다.</b><p>표 블록으로 원본 데이터를 확인하거나 블록 설정을 검토해 주세요.</p></div></div>;
}

function prepareEditorLayout(blocks, orientation = "landscape") {
  return compactDraftLayout(restoreDraftLayout(blocks).map((block) => (
    block.type === "text" ? { ...block, h: frontendTextBlockLayout(block, orientation).height } : block
  )));
}

function draftLayoutSignature(blocks) {
  return JSON.stringify(compactDraftLayout(restoreDraftLayout(blocks)).map((block) => ({
    id: block.id,
    title: block.title,
    artifactId: block.artifactId,
    queryId: block.queryId,
    type: block.type,
    content: block.content ?? "",
    x: block.x,
    y: block.y,
    w: block.w,
    h: block.h,
  })));
}

function GeneratedReportBlock({ block, number, rowOffset, artifact, artifactState, currency, orientation, onRetry }) {
  const isArtifact = block.type === "table" || block.type === "chart";
  const textLayout = frontendTextBlockLayout(block, orientation);
  let content = <MarkdownText content={block.content} />;
  if (isArtifact) content = <ReportArtifactContent block={block} artifact={artifact} artifactState={artifactState} currency={currency} paper onRetry={onRetry} />;
  if (block.type === "artifact") content = <ReportWholeArtifactBlock block={block} artifact={artifact} artifactState={artifactState} currency={currency} renderView={(type, options = {}) => <ReportArtifactContent block={{ ...block, type, h: options.height ?? block.h }} artifact={options.artifact || artifact} artifactState={artifactState} currency={currency} paper onRetry={onRetry} />} />;
  return <article className={`card generated-report-block ${block.type === "artifact" ? "is-whole-artifact" : ""} ${textLayout.overflow ? "has-content-overflow" : ""}`} style={{
    "--report-block-width": block.w ?? block.columns,
    "--block-x": (block.x ?? 0) + 1,
    "--block-y": Math.max(0, (block.y ?? 0) - rowOffset) + 1,
    "--block-w": block.w ?? block.columns,
    "--block-h": block.h ?? 1,
  }}>
    <header><span>{String(number).padStart(2, "0")}</span><div><small>보고서 섹션</small><h2>{block.title}</h2></div>{block.type !== "text" && <DataProvenanceBadge artifact={artifact} />}</header>
    {content}{textLayout.overflow && <p className="report-content-overflow-note" role="note">내용이 한 페이지를 초과합니다. 편집 화면에서 문단을 나누어 전체 내용을 표시하세요.</p>}
  </article>;
}

function MarkdownBlockEditor({ block, disabled, onUpdate }) {
  const textareaRef = useRef(null);
  const slashMenuRef = useRef(null);
  const typingTimerRef = useRef(null);
  const typingTransactionRef = useRef(false);
  const [mode, setMode] = useState("edit");
  const [slash, setSlash] = useState(null);
  const [slashIndex, setSlashIndex] = useState(0);
  const slashCommands = slash ? MARKDOWN_INSERT_COMMANDS.filter((command) => (
    !slash.query || `${command.title} ${command.description} ${command.aliases.join(" ")}`.toLocaleLowerCase("ko-KR").includes(slash.query)
  )) : [];
  useEffect(() => {
    setSlash(null); setSlashIndex(0); typingTransactionRef.current = false;
    window.clearTimeout(typingTimerRef.current);
    return () => window.clearTimeout(typingTimerRef.current);
  }, [block.id, mode]);
  useEffect(() => {
    slashMenuRef.current?.querySelector(`[data-slash-index="${slashIndex}"]`)?.scrollIntoView({ block: "nearest" });
  }, [slashIndex, slashCommands.length]);
  const updateSlash = (content, cursor) => {
    const next = markdownSlashContext(content, cursor);
    setSlash(next); setSlashIndex(0);
  };
  const insertSlashCommand = (command) => {
    if (!slash) return;
    const content = block.content || "";
    const next = `${content.slice(0, slash.from)}${command.content}${content.slice(slash.to)}`;
    const cursor = slash.from + command.content.length;
    onUpdate({ content: next }, true);
    setSlash(null); setSlashIndex(0);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(cursor, cursor);
    });
  };
  const handleTextareaKeyDown = (event) => {
    if (!slash) return;
    if (event.key === "Escape") { event.preventDefault(); setSlash(null); return; }
    if (!slashCommands.length) return;
    if (event.key === "Home") {
      event.preventDefault(); setSlashIndex(0);
    } else if (event.key === "End") {
      event.preventDefault(); setSlashIndex(slashCommands.length - 1);
    } else if (event.key === "ArrowDown") {
      event.preventDefault(); setSlashIndex((index) => (index + 1) % slashCommands.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault(); setSlashIndex((index) => (index - 1 + slashCommands.length) % slashCommands.length);
    } else if (event.key === "Enter") {
      event.preventDefault(); insertSlashCommand(slashCommands[slashIndex] || slashCommands[0]);
    }
  };
  const apply = (command) => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const content = block.content || "";
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selected = content.slice(start, end);
    const wrappers = {
      bold: ["**", "**", "강조할 내용"], italic: ["*", "*", "기울임"],
      link: ["[", "](https://)", "링크 텍스트"],
    };
    let from = start;
    let to = end;
    let replacement;
    if (wrappers[command]) {
      const [before, after, fallback] = wrappers[command];
      replacement = `${before}${selected || fallback}${after}`;
    } else {
      const prefix = { heading: "## ", list: "- ", quote: "> " }[command];
      from = content.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
      const lineEnd = content.indexOf("\n", end);
      to = lineEnd < 0 ? content.length : lineEnd;
      replacement = content.slice(from, to).split("\n").map((line) => `${prefix}${line}`).join("\n");
    }
    const next = `${content.slice(0, from)}${replacement}${content.slice(to)}`;
    onUpdate({ content: next }, true);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(from, from + replacement.length);
    });
  };
  return <div className="report-markdown-editor">
    {!disabled && <div className="report-markdown-toolbar" aria-label={`${block.title} Markdown 도구`}>
      <div><button type="button" title="굵게" aria-label="굵게" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("bold")}><Bold size={14} /></button><button type="button" title="기울임" aria-label="기울임" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("italic")}><Italic size={14} /></button><button type="button" title="소제목" aria-label="소제목" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("heading")}><Heading2 size={14} /></button><button type="button" title="목록" aria-label="목록" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("list")}><List size={14} /></button><button type="button" title="인용" aria-label="인용" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("quote")}><Quote size={14} /></button><button type="button" title="링크" aria-label="링크" onMouseDown={(event) => event.preventDefault()} onClick={() => apply("link")}><Link2 size={14} /></button></div>
      <div className="report-markdown-mode"><button type="button" className={mode === "edit" ? "active" : ""} onClick={() => setMode("edit")}>편집</button><button type="button" className={mode === "preview" ? "active" : ""} onClick={() => setMode("preview")}>미리보기</button></div>
    </div>}
    {mode === "preview" && !disabled
      ? <div className="report-markdown-preview"><MarkdownText content={block.content} /></div>
      : <><textarea ref={textareaRef} className="notion-markdown-input" aria-label={`${block.title} 내용`} aria-expanded={Boolean(slash)} aria-controls={slash ? `${block.id}-slash-menu` : undefined} aria-activedescendant={slash && slashCommands.length ? `${block.id}-slash-option-${slashCommands[slashIndex]?.id}` : undefined} disabled={disabled} value={block.content || ""} onChange={(event) => { const record = !typingTransactionRef.current; typingTransactionRef.current = true; window.clearTimeout(typingTimerRef.current); typingTimerRef.current = window.setTimeout(() => { typingTransactionRef.current = false; }, 700); onUpdate({ content: event.target.value }, record); updateSlash(event.target.value, event.target.selectionStart); }} onClick={(event) => updateSlash(event.currentTarget.value, event.currentTarget.selectionStart)} onKeyUp={(event) => { if (!["ArrowDown", "ArrowUp", "Home", "End", "Enter", "Escape"].includes(event.key)) updateSlash(event.currentTarget.value, event.currentTarget.selectionStart); }} onKeyDown={handleTextareaKeyDown} placeholder="내용을 입력하세요. Markdown 표·목록·체크박스·링크를 사용할 수 있습니다." />{slash && <div ref={slashMenuRef} id={`${block.id}-slash-menu`} className="report-slash-menu" role="listbox" aria-label="Markdown 블록 삽입"><header><b>블록 삽입</b><span>↑↓·Home·End 선택 · Enter 삽입 · Esc 닫기</span></header>{slashCommands.length ? slashCommands.map((command, index) => { const Icon = command.icon; return <button id={`${block.id}-slash-option-${command.id}`} data-slash-index={index} type="button" role="option" aria-selected={index === slashIndex} className={index === slashIndex ? "active" : ""} onMouseDown={(event) => event.preventDefault()} onClick={() => insertSlashCommand(command)} key={command.id}><Icon size={15} aria-hidden="true" /><span><small>{command.group}</small><b>{command.title}</b><small>{command.description}</small></span><kbd>{command.shortcut}</kbd></button>; }) : <p role="status">일치하는 블록이 없습니다.</p>}</div>}<small className="report-markdown-hint"><kbd>/</kbd> 입력으로 제목·목록·표를 바로 삽입할 수 있습니다.</small></>}
  </div>;
}

function ReportBlockMenu({ block, artifact, onMove, onResize, onSetting, onDuplicate, onDelete }) {
  const detailsRef = useRef(null);
  const settings = blockSettings(block);
  const viewSizing = artifactViewBlockSettings(block);
  const widths = block.type === "text" ? [[4, "좁게"], [6, "절반"], [12, "전체"]] : [[6, "절반"], [12, "전체"]];
  const chartType = settings.chartType || artifact?.chart?.chart_type || "bar";
  const handleMenuKeyDown = (event) => {
    const details = detailsRef.current;
    if (!details?.open) return;
    if (event.key === "Escape") {
      event.preventDefault(); event.stopPropagation(); details.open = false;
      details.querySelector("summary")?.focus();
      return;
    }
    if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    const controls = [...details.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled)")];
    if (!controls.length) return;
    event.preventDefault(); event.stopPropagation();
    const current = controls.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0
      : event.key === "End" ? controls.length - 1
        : event.key === "ArrowDown" || event.key === "ArrowRight" ? (current + 1 + controls.length) % controls.length
          : (current - 1 + controls.length) % controls.length;
    controls[next]?.focus();
  };
  return <details ref={detailsRef} className="report-block-menu" name="report-block-menu" onClick={(event) => event.stopPropagation()} onKeyDown={handleMenuKeyDown}>
    <summary aria-label={`${block.title} 블록 메뉴`} aria-haspopup="true" title="블록 메뉴"><MoreHorizontal size={17} /></summary>
    <div className="report-block-menu-popover" aria-label={`${block.title} 블록 설정`}>
      <section><span>블록 너비</span><div className="report-block-widths">{widths.map(([width, label]) => <button type="button" className={(block.w ?? block.columns) === width ? "active" : ""} onClick={() => onResize(width)} key={width}>{label}</button>)}</div></section>
      <section><span>블록 높이</span><div className="report-block-height"><button type="button" aria-label="높이 줄이기" onClick={() => onResize(block.w ?? block.columns, (block.h ?? 4) - 1)}>−</button><output>{block.h ?? 4}단</output><button type="button" aria-label="높이 늘리기" onClick={() => onResize(block.w ?? block.columns, (block.h ?? 4) + 1)}>+</button></div></section>
      <section><span>위치 이동</span><div className="report-block-moves"><button type="button" aria-label="왼쪽으로 이동" title="왼쪽으로 이동" onClick={() => onMove(-1, 0)}><ArrowLeft size={14} /></button><button type="button" aria-label="위로 이동" title="위로 이동" disabled={(block.y ?? 0) === 0} onClick={() => onMove(0, -1)}><ArrowUp size={14} /></button><button type="button" aria-label="아래로 이동" title="아래로 이동" onClick={() => onMove(0, 1)}><ArrowDown size={14} /></button><button type="button" aria-label="오른쪽으로 이동" title="오른쪽으로 이동" onClick={() => onMove(1, 0)}><ArrowRight size={14} /></button></div></section>
      {block.type === "chart" && <section><span>차트 표현</span><label className="report-chart-type"><span className="sr-only">차트 유형</span><select aria-label={`${block.title} 차트 유형`} value={chartType} onChange={(event) => onSetting("chartType", event.target.value)}>{REPORT_CHART_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><small>데이터 구조에 맞지 않는 표현은 안전 안내로 대체됩니다.</small><label><input type="checkbox" checked={settings.showLegend !== false} onChange={(event) => onSetting("showLegend", event.target.checked)} />범례 표시</label><button type="button" className={viewSizing?.sizeMode === "auto" ? "active" : ""} onClick={() => onSetting("sizeMode", "auto")}>내용에 맞춤</button></section>}
      {block.type === "table" && <section><span>표 표현</span><div className="report-block-widths"><button type="button" className={settings.density !== "compact" ? "active" : ""} onClick={() => onSetting("density", "comfortable")}>보통</button><button type="button" className={settings.density === "compact" ? "active" : ""} onClick={() => onSetting("density", "compact")}>간결</button></div><label><input type="checkbox" checked={settings.showRowNumbers === true} onChange={(event) => onSetting("showRowNumbers", event.target.checked)} />행 번호 표시</label><button type="button" className={viewSizing?.sizeMode === "auto" ? "active" : ""} onClick={() => onSetting("sizeMode", "auto")}>내용에 맞춤</button></section>}
      {block.type === "artifact" && <section><span>Artifact 전체</span><small>요약·KPI·차트·표가 함께 이동하고 미리보기에 같은 순서로 표시됩니다.</small><button type="button" className={settings.sizeMode === "auto" ? "active" : ""} onClick={() => onSetting("sizeMode", "auto")}>내용에 맞춤</button></section>}
      <div className="report-block-menu-actions"><button type="button" onClick={onDuplicate}><Copy size={14} />복제</button><button type="button" className="danger" onClick={onDelete}><Trash2 size={14} />삭제</button></div>
    </div>
  </details>;
}

function ReportTemplateTile({ template, disabled = false, onAdd }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, isDragging } = useDraggable({
    id: `template:${template.id}`,
    disabled,
    data: { kind: "template", templateId: template.id },
  });
  const Icon = template.icon;
  return <div
    ref={setNodeRef}
    className={`report-template-tile ${isDragging ? "is-dragging" : ""}`}
    aria-disabled={disabled || undefined}
  ><button type="button" className="report-template-add" disabled={disabled} onClick={() => onAdd(template.id)} title={`${template.title} 블록 바로 추가`}><Icon size={15} /><span>{template.title}<small>{template.description}</small></span></button><button ref={setActivatorNodeRef} type="button" className="report-template-drag" disabled={disabled} aria-label={`${template.title} 블록 끌어서 추가`} title="Space 또는 Enter로 들어 캔버스 위치를 선택하세요" {...listeners} {...attributes}><GripVertical className="report-template-grip" size={14} aria-hidden="true" /></button></div>;
}

function ReportEditorBlock({ block, rowOffset, artifact, artifactState, currency, isDraft, selected, dragging, onSelect, onUpdate, onMove, onResize, onSetting, onDuplicate, onDelete, onRetryArtifact }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform } = useDraggable({ id: block.id, disabled: !isDraft });
  const resizeStart = useRef(null);
  const resizePreviewRef = useRef(null);
  const [resizePreview, setResizePreview] = useState(null);
  const titleTimerRef = useRef(null);
  const titleTransactionRef = useRef(false);
  useEffect(() => () => window.clearTimeout(titleTimerRef.current), []);
  const startResize = (event) => {
    event.stopPropagation();
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    const canvas = event.currentTarget.closest(".notion-canvas");
    const styles = canvas ? window.getComputedStyle(canvas) : null;
    const bounds = canvas?.getBoundingClientRect();
    const gap = Number.parseFloat(styles?.columnGap || "0") || 0;
    const padding = (Number.parseFloat(styles?.paddingLeft || "0") || 0) + (Number.parseFloat(styles?.paddingRight || "0") || 0);
    resizeStart.current = {
      x: event.clientX, y: event.clientY, w: block.w ?? block.columns, h: block.h ?? 4,
      columnStep: bounds ? Math.max(1, (bounds.width - padding - gap * 11) / 12 + gap) : 72,
      rowStep: (Number.parseFloat(styles?.getPropertyValue("--report-grid-row") || "56") || 56) + (Number.parseFloat(styles?.rowGap || "0") || 0),
    };
    resizePreviewRef.current = { w: block.w ?? block.columns, h: block.h ?? 4 };
    setResizePreview(resizePreviewRef.current);
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const resizeWithPointer = (event) => {
    if (!resizeStart.current || (event.buttons & 1) === 0) return;
    const start = resizeStart.current;
    const minimumWidth = block.type === "text" ? 4 : 6;
    const minimumHeight = block.type === "artifact" ? 5 : block.type === "chart" ? 7 : block.type === "table" ? 5 : 4;
    const next = {
      w: Math.max(minimumWidth, Math.min(12, start.w + Math.round((event.clientX - start.x) / start.columnStep))),
      h: Math.max(minimumHeight, Math.min(["artifact", "chart", "table"].includes(block.type) ? 18 : 14, start.h + Math.round((event.clientY - start.y) / start.rowStep))),
    };
    resizePreviewRef.current = next;
    setResizePreview(next);
  };
  const finishResize = () => {
    const next = resizePreviewRef.current;
    const start = resizeStart.current;
    resizeStart.current = null; resizePreviewRef.current = null; setResizePreview(null);
    if (next && start && (next.w !== start.w || next.h !== start.h)) onResize(next.w, next.h);
  };
  const cancelResize = () => {
    resizeStart.current = null; resizePreviewRef.current = null; setResizePreview(null);
  };
  const resizeWithKeyboard = (event) => {
    const movement = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] }[event.key];
    if (!movement) return;
    event.preventDefault(); event.stopPropagation();
    onResize((block.w ?? block.columns) + movement[0], (block.h ?? 4) + movement[1]);
  };
  const displayY = Math.max(0, (block.y ?? 0) - rowOffset);
  const displayW = resizePreview?.w ?? block.w ?? block.columns;
  const displayH = resizePreview?.h ?? block.h ?? 1;
  const style = {
    "--block-x": (block.x ?? 0) + 1, "--block-y": displayY + 1,
    "--block-w": displayW, "--block-h": displayH,
    "--block-order": displayY * 12 + (block.x ?? 0),
    gridRow: `${displayY + 1} / span ${displayH}`,
    transform: transform ? `translate3d(${Math.round(transform.x)}px, ${Math.round(transform.y)}px, 0)` : undefined,
  };
  return <article ref={setNodeRef} data-block-id={block.id} tabIndex={-1} className={`editor-block notion-block ${selected ? "selected" : ""} ${dragging ? "dragging is-dragging" : ""}`} aria-label={`${block.title || "제목 없음"} 블록${selected ? ", 선택됨" : ""}`} onClick={onSelect} onFocusCapture={onSelect} style={style}>
    <header className="report-block-chrome"><div className="report-block-title">{isDraft && <button ref={setActivatorNodeRef} type="button" className="report-drag-handle" {...listeners} {...attributes} aria-label={`${block.title} 블록 이동`} title="끌어서 이동 · Space 또는 Enter로 키보드 이동"><GripVertical size={17} /></button>}<span>{block.type === "text" ? "텍스트" : block.type === "artifact" ? "Artifact 전체" : block.type === "chart" ? "차트 보기" : "표 보기"}</span>{block.type !== "text" && <DataProvenanceBadge artifact={artifact} />}</div>{isDraft && <ReportBlockMenu block={block} artifact={artifact} onMove={onMove} onResize={onResize} onSetting={onSetting} onDuplicate={onDuplicate} onDelete={onDelete} />}</header>
    {isDraft ? <input className="notion-block-title" aria-label={`${block.title || "제목 없음"} 제목`} value={block.title} onChange={(event) => { const record = !titleTransactionRef.current; titleTransactionRef.current = true; window.clearTimeout(titleTimerRef.current); titleTimerRef.current = window.setTimeout(() => { titleTransactionRef.current = false; }, 700); onUpdate({ title: event.target.value }, record); }} placeholder="블록 제목을 입력하세요" /> : <h2>{block.title}</h2>}
    {block.type === "text" ? <MarkdownBlockEditor block={block} disabled={!isDraft} onUpdate={onUpdate} /> : block.type === "artifact" ? <ReportWholeArtifactBlock block={block} artifact={artifact} artifactState={artifactState} currency={currency} renderView={(type, options = {}) => <ReportArtifactContent block={{ ...block, type, h: options.height ?? block.h }} artifact={options.artifact || artifact} artifactState={artifactState} currency={currency} editor paper onRetry={onRetryArtifact} />} /> : <div className="notion-data-embed notion-data-embed-live"><div className="notion-data-status"><Columns2 size={19} aria-hidden="true" /><div><small>{dataProvenanceLabel(artifact?.evidence?.sources ?? []) ?? "분석 데이터"}</small><b>{block.type === "chart" ? "분석 차트 보기" : "분석 데이터 표 보기"}</b><span>Artifact에서 선택한 하나의 보기입니다.</span></div></div><ReportArtifactContent block={block} artifact={artifact} artifactState={artifactState} currency={currency} editor paper onRetry={onRetryArtifact} /></div>}
    {isDraft && <button type="button" className="report-resize-handle" aria-label={`${block.title} 블록 크기 조절`} title="끌어서 크기 조절 · 방향키로 미세 조절" onPointerDown={startResize} onPointerMove={resizeWithPointer} onPointerUp={finishResize} onPointerCancel={cancelResize} onLostPointerCapture={() => { if (resizeStart.current) cancelResize(); }} onKeyDown={resizeWithKeyboard}><span /></button>}
  </article>;
}

function reportKeyboardCoordinates(event, { currentCoordinates }) {
  const movement = {
    ArrowRight: [80, 0], ArrowLeft: [-80, 0], ArrowDown: [0, 72], ArrowUp: [0, -72],
  }[event.code];
  if (!movement) return undefined;
  event.preventDefault();
  return { x: currentCoordinates.x + movement[0], y: currentCoordinates.y + movement[1] };
}

export function ReportsPage({ role, onEditorMode }) {
  const client = useMemo(() => createReportClient(undefined, fetch), []);
  const analysisClient = useMemo(() => createAnalysisClient(fetch), []);
  const isAdmin = role === "report_admin";
  const [view, setView] = useState("list");
  const [toolPanelOpen, setToolPanelOpen] = useState(true);
  const [reportOrientation, setReportOrientation] = useState("landscape");
  const [reportCurrencyPolicy, setReportCurrencyPolicy] = useState(() => ({ ...DEFAULT_FRONTEND_CURRENCY_POLICY }));
  const [definitions, setDefinitions] = useState([]);
  const [definitionState, setDefinitionState] = useState("loading");
  const [selectedDefinition, setSelectedDefinition] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [schedules, setSchedules] = useState([]);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [query, setQuery] = useState("");
  const [runQuery, setRunQuery] = useState("");
  const [visibleRunCount, setVisibleRunCount] = useState(REPORT_RUN_PAGE_SIZE);
  const [statusFilter, setStatusFilter] = useState("all");
  const [cadence, setCadence] = useState("daily");
  const [scheduleAt, setScheduleAt] = useState("");
  const [assistantInstruction, setAssistantInstruction] = useState("");
  const [assistantTrace, setAssistantTrace] = useState(null);
  const [draggedBlockId, setDraggedBlockId] = useState("");
  const [dropPosition, setDropPosition] = useState(null);
  const [selectedBlockId, setSelectedBlockId] = useState("");
  const [isDirty, setIsDirty] = useState(false);
  const [artifacts, setArtifacts] = useState({});
  const [artifactStates, setArtifactStates] = useState({});
  const [artifactSources, setArtifactSources] = useState([]);
  const [analysisLibraryState, setAnalysisLibraryState] = useState({ status: "idle", message: "" });
  const [artifactSelection, setArtifactSelection] = useState("");
  const [history, setHistory] = useState({ past: [], future: [] });
  const [saveFailed, setSaveFailed] = useState(false);
  const [editorAnnouncement, setEditorAnnouncement] = useState("");
  const [finalDocument, setFinalDocument] = useState(null);
  const [finalDocumentState, setFinalDocumentState] = useState("idle");
  const blocksRef = useRef([]);
  const savedBlocksRef = useRef([]);
  const savedOrientationRef = useRef("landscape");
  const currencyPolicyRef = useRef({ ...DEFAULT_FRONTEND_CURRENCY_POLICY });
  const savedCurrencyPolicyRef = useRef({ ...DEFAULT_FRONTEND_CURRENCY_POLICY });
  const lastDropOutcomeRef = useRef({ success: false, message: "" });
  const pageCanvasRefs = useRef(new Map());
  const dragPointerRef = useRef(null);
  const pointerDragRef = useRef(false);
  const dropPositionRef = useRef(null);
  const toolPanelRef = useRef(null);
  const toolToggleRef = useRef(null);
  const errorRef = useRef(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: reportKeyboardCoordinates }),
  );

  useEffect(() => { onEditorMode?.(view === "editor"); }, [onEditorMode, view]);
  useEffect(() => () => onEditorMode?.(false), [onEditorMode]);
  useEffect(() => {
    window.dispatchEvent(new CustomEvent("answervice:report-dirty", { detail: isDirty }));
    return () => window.dispatchEvent(new CustomEvent("answervice:report-dirty", { detail: false }));
  }, [isDirty]);
  useEffect(() => {
    if (!error) return undefined;
    const frame = window.requestAnimationFrame(() => errorRef.current?.focus({ preventScroll: true }));
    return () => window.cancelAnimationFrame(frame);
  }, [error]);
  useEffect(() => {
    const tablet = window.matchMedia("(min-width: 901px) and (max-width: 1100px)");
    const collapseForTablet = (event) => { if (event.matches) setToolPanelOpen(false); };
    if (tablet.matches) setToolPanelOpen(false);
    tablet.addEventListener("change", collapseForTablet);
    return () => tablet.removeEventListener("change", collapseForTablet);
  }, []);
  useEffect(() => {
    if (!toolPanelOpen || !window.matchMedia("(min-width: 901px) and (max-width: 1100px)").matches) return undefined;
    const panel = toolPanelRef.current;
    const previous = toolToggleRef.current;
    const frame = window.requestAnimationFrame(() => panel?.focus());
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault(); setToolPanelOpen(false); return;
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleKeyDown);
      window.requestAnimationFrame(() => previous?.focus?.());
    };
  }, [toolPanelOpen]);

  const isDraft = selectedDefinition?.status === "draft";
  const canEdit = Boolean(isDraft && !pending);
  const selectedSchedules = selectedDefinition
    ? schedules.filter((item) => item.definition_id === selectedDefinition.definitionId && item.version === selectedDefinition.version)
    : [];
  const visibleDefinitions = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ko-KR");
    return definitions.filter((definition) => (
      (statusFilter === "all" || definition.status === statusFilter)
      && (!normalized || definition.title.toLocaleLowerCase("ko-KR").includes(normalized))
    ));
  }, [definitions, query, statusFilter]);
  const filteredRuns = useMemo(() => {
    const normalized = runQuery.trim().toLocaleLowerCase("ko-KR");
    return runs.filter((run) => !normalized || [
      runStatusLabel(run.status), `v${run.definitionVersion}`, formatSeoulTime(run.asOf),
      ...run.blocks.flatMap((block) => [block.failureCode, block.failureMessage]),
    ].filter(Boolean).join(" ").toLocaleLowerCase("ko-KR").includes(normalized));
  }, [runQuery, runs]);
  const visibleRuns = filteredRuns.slice(0, visibleRunCount);
  const artifactOptions = useMemo(() => {
    const seen = new Set();
    return [...artifactSources, ...blocks].filter((block) => {
      if (!block.artifactId || !artifacts[block.artifactId] || seen.has(block.artifactId)) return false;
      seen.add(block.artifactId);
      return true;
    });
  }, [artifactSources, artifacts, blocks]);
  const orderedBlocks = useMemo(() => [...blocks].sort((left, right) => (
    (left.y ?? 0) - (right.y ?? 0) || (left.x ?? 0) - (right.x ?? 0)
  )), [blocks]);
  const resolvedReportCurrencyUnit = useMemo(() => resolveCurrencyDisplayUnit(
    Object.values(artifacts).flatMap(artifactCurrencyValues),
    reportCurrencyPolicy,
  ), [artifacts, reportCurrencyPolicy]);
  const reportCurrency = useMemo(() => ({
    policy: reportCurrencyPolicy,
    unit: resolvedReportCurrencyUnit,
    label: currencyDisplayLabel(resolvedReportCurrencyUnit),
  }), [reportCurrencyPolicy, resolvedReportCurrencyUnit]);
  const reportPages = useMemo(() => paginateReportBlocks(
    orderedBlocks,
    reportOrientation,
    selectedDefinition?.definitionId || "report-draft",
  ), [orderedBlocks, reportOrientation, selectedDefinition?.definitionId]);
  const reportBlockNumbers = useMemo(() => new Map(orderedBlocks.map((block, index) => [block.id, index + 1])), [orderedBlocks]);
  const selectedArtifact = artifactSelection ? artifacts[artifactSelection] : null;
  const selectedArtifactSource = artifactOptions.find((block) => block.artifactId === artifactSelection);
  const selectedArtifactPeriod = selectedArtifact?.evidence?.period;
  const wholeArtifactTemplateFor = (source, width = null) => {
    const layout = estimateArtifactBlockLayout(source ? artifacts[source.artifactId] : null, {
      orientation: reportOrientation,
      visibleViews: WHOLE_ARTIFACT_VIEWS,
      ...(width ? { width } : {}),
    });
    return { ...WHOLE_ARTIFACT_TEMPLATE, w: layout.width, h: layout.height };
  };
  const viewArtifactTemplateFor = (template, width = template?.w) => {
    if (!template?.id?.startsWith("artifact-")) return template;
    const source = selectedArtifactSource || artifactOptions[0];
    const type = template.id === "artifact-chart" ? "chart" : "table";
    const resolvedWidth = width ?? 12;
    const layout = estimateArtifactViewBlockLayout({ type, w: resolvedWidth, columns: resolvedWidth }, source ? artifacts[source.artifactId] : null, {
      orientation: reportOrientation,
    });
    return { ...template, w: resolvedWidth, h: layout.height };
  };
  const activeTemplate = draggedBlockId.startsWith("template:")
    ? viewArtifactTemplateFor(REPORT_TEMPLATE_MAP.get(draggedBlockId.slice("template:".length)))
    : null;
  const activeArtifactSource = draggedBlockId.startsWith("artifact:")
    ? artifactOptions.find((source) => source.artifactId === draggedBlockId.slice("artifact:".length))
    : null;
  const activeInsert = activeTemplate || (activeArtifactSource ? wholeArtifactTemplateFor(activeArtifactSource) : null);
  const ActiveTemplateIcon = activeInsert?.icon;
  const registerPageCanvas = (element, context) => {
    if (element) pageCanvasRefs.current.set(context.page.id, { element, page: context.page });
    else pageCanvasRefs.current.delete(context.page.id);
  };

  const restoreReportCurrencyPolicy = (policy = DEFAULT_FRONTEND_CURRENCY_POLICY, saved = true) => {
    const next = { ...DEFAULT_FRONTEND_CURRENCY_POLICY, ...policy };
    currencyPolicyRef.current = next;
    if (saved) savedCurrencyPolicyRef.current = next;
    setReportCurrencyPolicy(next);
  };
  const draftChanged = (
    nextBlocks,
    nextPolicy = currencyPolicyRef.current,
    nextOrientation = reportOrientation,
  ) => (
    JSON.stringify(nextBlocks) !== JSON.stringify(savedBlocksRef.current)
    || JSON.stringify(nextPolicy) !== JSON.stringify(savedCurrencyPolicyRef.current)
    || nextOrientation !== savedOrientationRef.current
  );

  const resetBlocks = (nextBlocks, dirty = false) => {
    const next = [...nextBlocks];
    blocksRef.current = next;
    if (!dirty) savedBlocksRef.current = next;
    setBlocks(next);
    setHistory({ past: [], future: [] });
    setIsDirty(dirty);
    setSaveFailed(false);
  };
  const commitBlocks = (updater, record = true) => {
    if (!canEdit) return;
    const current = blocksRef.current;
    const next = typeof updater === "function" ? updater(current) : updater;
    if (!next || next === current) return;
    if (record) setHistory((value) => ({ past: [...value.past.slice(-39), current], future: [] }));
    blocksRef.current = [...next];
    setBlocks([...next]);
    setIsDirty(draftChanged(next));
  };
  const undo = () => setHistory((value) => {
    if (!value.past.length) return value;
    const current = blocksRef.current;
    const previous = value.past.at(-1);
    blocksRef.current = [...previous]; setBlocks([...previous]);
    setIsDirty(draftChanged(previous));
    return { past: value.past.slice(0, -1), future: [current, ...value.future].slice(0, 40) };
  });
  const redo = () => setHistory((value) => {
    if (!value.future.length) return value;
    const current = blocksRef.current;
    const [next, ...future] = value.future;
    blocksRef.current = [...next]; setBlocks([...next]);
    setIsDirty(draftChanged(next));
    return { past: [...value.past, current].slice(-40), future };
  });

  const mutate = async (name, action) => {
    setPending(name); setError(""); setNotice("");
    try { return await action(); } catch (nextError) { setError(apiError(nextError)); return null; } finally { setPending(""); }
  };
  const upsertDefinition = (definition, options = {}) => {
    setDefinitions((current) => [
      definition,
      ...current.filter((item) => !(item.definitionId === definition.definitionId && item.version === definition.version)),
    ].sort((left, right) => right.version - left.version || left.title.localeCompare(right.title, "ko-KR")));
    setSelectedDefinition(definition);
    const orientation = options.orientation || definition.orientation || reportOrientation;
    const currencyPolicy = options.currencyPolicy || {
      ...DEFAULT_FRONTEND_CURRENCY_POLICY,
      displayUnit: definition.currencyDisplayUnit || DEFAULT_FRONTEND_CURRENCY_POLICY.displayUnit,
    };
    setReportOrientation(orientation);
    savedOrientationRef.current = orientation;
    restoreReportCurrencyPolicy(currencyPolicy);
    const serverLayout = compactDraftLayout(restoreDraftLayout(options.serverBlocks || definition.blocks));
    const preparedLayout = prepareEditorLayout(definition.blocks, orientation);
    const layoutDirty = Boolean(options.forceDirty)
      || (definition.status === "draft"
        && JSON.stringify(preparedLayout) !== JSON.stringify(serverLayout));
    if (layoutDirty) savedBlocksRef.current = serverLayout;
    resetBlocks(preparedLayout, layoutDirty);
    setSelectedBlockId(definition.blocks[0]?.id || "");
  };
  const loadDefinitions = async () => {
    setDefinitionState("loading");
    const items = await mutate("definitions", () => client.listDefinitions());
    if (!items) return setDefinitionState("error");
    setDefinitions([...items]);
    setDefinitionState(items.length ? "ready" : "empty");
  };
  const loadSchedules = async () => {
    const items = await mutate("schedules", () => client.listSchedules());
    if (items) setSchedules([...items]);
  };
  useEffect(() => { void loadDefinitions(); if (isAdmin) void loadSchedules(); }, [isAdmin]);
  useEffect(() => {
    if (!isDirty) return undefined;
    const warnBeforeUnload = (event) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [isDirty]);

  const createDefinition = async (event) => {
    event.preventDefault();
    if (!newTitle.trim()) return;
    const initialContent = newContent.trim();
    const blockId = createUuid();
    const definition = await mutate("create", () => client.createDefinition({
      definition_id: createUuid(), title: newTitle.trim(), blocks: initialContent ? [{
        block_id: blockId, title: "운영 요약", columns: 12, type: "text",
        x: 0, y: 0, w: 12, h: 4, content: initialContent,
      }] : [],
    }));
    if (!definition) return;
    setAssistantTrace(null);
    upsertDefinition(definition, { currencyPolicy: DEFAULT_FRONTEND_CURRENCY_POLICY }); setDefinitionState("ready"); setCreateOpen(false);
    if (!initialContent) {
      resetBlocks([{ id: blockId, title: "운영 요약", columns: 12, type: "text", content: "", x: 0, y: 0, w: 12, h: 4 }], true);
      setSelectedBlockId(blockId);
    }
    setNewTitle(""); setNewContent(""); setView("editor");
  };
  const fetchDefinition = async (definition) => mutate("definition", () => client.getDefinition(definition.definitionId, definition.version));
  const loadFinalDocument = async (definition) => {
    if (definition.status !== "approved") {
      setFinalDocument(null); setFinalDocumentState("idle"); return;
    }
    setFinalDocument(null); setFinalDocumentState("loading");
    try {
      const document = await client.getFinalDocument(definition.definitionId, definition.version);
      setFinalDocument(document);
      setFinalDocumentState("ready");
      setReportOrientation(document.orientation);
      savedOrientationRef.current = document.orientation;
      restoreReportCurrencyPolicy({
        ...DEFAULT_FRONTEND_CURRENCY_POLICY,
        displayUnit: document.currencyDisplayUnit,
      });
    } catch (nextError) {
      if (nextError instanceof ReportApiError && nextError.status === 404) {
        setFinalDocumentState("missing"); return;
      }
      setFinalDocumentState("error"); setError(apiError(nextError));
    }
  };
  const openPreview = async (definition) => {
    const current = await fetchDefinition(definition);
    if (!current) return;
    setAssistantTrace(null);
    upsertDefinition(current, {
      orientation: current.orientation,
      currencyPolicy: {
        ...DEFAULT_FRONTEND_CURRENCY_POLICY,
        displayUnit: current.currencyDisplayUnit,
      },
    }); setView("document");
    await loadArtifacts(current);
    await loadFinalDocument(current);
  };
  const fitAutoArtifactViewLayout = (inputBlocks, artifactMap, orientation) => {
    // 먼저 행을 압축해 단독 블록의 최종 폭을 확정한 다음, 그 폭으로 차트·표 높이를 다시 계산한다.
    // 이 순서를 지켜야 6열 표가 단독 행에서 12열로 넓어진 뒤에도 이전 높이가 남지 않아 저장 후 재진입이 동일하다.
    const compacted = compactDraftLayout(inputBlocks);
    return compactDraftLayout(compacted.map((block) => (
      block.artifactId && artifactMap[block.artifactId] && ["chart", "table"].includes(block.type)
        ? fitFrontendArtifactViewBlock(block, artifactMap[block.artifactId], { orientation })
        : block
    )));
  };
  const applyHydratedArtifactViewSizing = (artifactMap, definition = selectedDefinition) => {
    if (definition?.status !== "draft") return false;
    const current = blocksRef.current;
    const fitted = fitAutoArtifactViewLayout(
      current,
      artifactMap,
      definition?.orientation || reportOrientation,
    );
    if (JSON.stringify(fitted) === JSON.stringify(current)) return false;
    setHistory((value) => ({ past: [...value.past.slice(-39), current], future: [] }));
    blocksRef.current = [...fitted];
    setBlocks([...fitted]);
    setIsDirty(draftChanged(fitted));
    setEditorAnnouncement("차트와 표 높이를 실제 데이터에 맞춰 조정했습니다.");
    return true;
  };
  const loadArtifacts = async (definition, includeLibrary = false) => {
    const reportSources = reportArtifactLibrarySources(definition, includeLibrary ? definitions : [definition]);
    let discoveredAnalysisSources = [];
    let nextAnalysisLibraryState = { status: "idle", message: "" };
    if (includeLibrary) {
      setAnalysisLibraryState({ status: "loading", message: "저장된 분석 결과를 확인하는 중입니다." });
      const [definitionResult, runResult] = await Promise.allSettled([
        analysisClient.listDefinitions(),
        analysisClient.listRuns(),
      ]);
      if (runResult.status === "fulfilled") {
        discoveredAnalysisSources = analysisRunArtifactSources(
          runResult.value,
          definitionResult.status === "fulfilled" ? definitionResult.value : [],
        );
        nextAnalysisLibraryState = definitionResult.status === "fulfilled"
          ? { status: "ready", message: "" }
          : { status: "partial", message: "일부 저장된 분석의 제목을 확인하지 못해 지표·기간 기반 제목으로 표시합니다." };
      } else {
        nextAnalysisLibraryState = {
          status: "error",
          message: "저장된 분석 보관함을 불러오지 못했습니다. 보고서에 이미 연결된 결과는 계속 사용할 수 있습니다.",
        };
      }
    } else {
      setAnalysisLibraryState({ status: "idle", message: "" });
    }
    const sourcesByArtifact = new Map(reportSources
      .filter((source) => source.artifactId)
      .map((source) => [source.artifactId, source]));
    for (const source of discoveredAnalysisSources) {
      const existing = sourcesByArtifact.get(source.artifactId);
      sourcesByArtifact.set(source.artifactId, existing ? {
        ...source,
        ...existing,
        title: source.title,
        definitionTitle: source.definitionTitle,
      } : source);
    }
    const sources = [...sourcesByArtifact.values()];
    const ids = sources.map((source) => source.artifactId);
    setArtifactSources(sources);
    setArtifacts({});
    setArtifactStates(Object.fromEntries(ids.map((artifactId) => [artifactId, { status: "loading", message: "" }])));
    const loaded = await Promise.all(sources.map(async (source) => {
      const artifactId = source.artifactId;
      try {
        const analysisSource = source.sourceKind === "analysisRun" || source.artifactSourceKind === "analysisRun";
        const analysisRun = analysisSource
          ? await analysisClient.getRunArtifact(source.requestId || source.artifactRequestId)
          : null;
        const artifact = analysisSource
          ? adaptAnalysisRunArtifact(analysisRun)
          : await client.getArtifact(source.definitionId, source.definitionVersion, artifactId);
        if (!artifact) throw new Error("완전한 검증 근거가 있는 분석 결과만 보고서에 추가할 수 있습니다.");
        if (!reportEvidenceReady(artifact)) throw new Error("검증 근거가 완전하지 않아 보고서 결과를 표시하지 않습니다.");
        const status = artifact?.table?.rows?.length === 0 ? "empty" : "success";
        setArtifactStates((current) => ({ ...current, [artifactId]: { status, message: "" } }));
        const hydratedSource = {
          ...source,
          queryId: artifact.query_id,
          artifactChecksum: source.artifactChecksum || artifact.artifact_checksum,
          sourceUrns: artifact.evidence.sources.map((item) => item.urn),
          ...(analysisSource ? {
            sourceKind: "analysisRun",
            artifactSourceKind: "analysisRun",
            requestId: analysisRun.requestId,
            artifactRequestId: analysisRun.requestId,
            title: analysisArtifactTitle(artifact, source.definitionTitle, source),
          } : {}),
        };
        return [artifactId, artifact, hydratedSource];
      } catch (nextError) {
        setArtifactStates((current) => ({ ...current, [artifactId]: { status: "error", message: apiError(nextError), requiredAction: apiRequiredAction(nextError) } }));
        return [artifactId, null, source];
      }
    }));
    const loadedArtifactMap = Object.fromEntries(loaded.map(([artifactId, artifact]) => [artifactId, artifact]));
    setArtifacts(loadedArtifactMap);
    applyHydratedArtifactViewSizing(loadedArtifactMap, definition);
    setArtifactSources(loaded.map(([, , source]) => source));
    const unavailableAnalysisCount = loaded.filter(([, artifact, source]) => (
      !artifact && (source.sourceKind === "analysisRun" || source.artifactSourceKind === "analysisRun")
    )).length;
    if (includeLibrary) setAnalysisLibraryState(nextAnalysisLibraryState.status === "error"
      ? nextAnalysisLibraryState
      : unavailableAnalysisCount
        ? {
            status: "partial",
            message: [
              nextAnalysisLibraryState.message,
              `근거가 완전하지 않은 저장 분석 ${unavailableAnalysisCount}개는 보관함에서 제외했습니다.`,
            ].filter(Boolean).join(" "),
          }
        : nextAnalysisLibraryState);
    const availableIds = loaded.filter(([, artifact]) => artifact).map(([artifactId]) => artifactId);
    setArtifactSelection((current) => availableIds.includes(current) ? current : availableIds[0] || "");
  };
  const retryArtifact = async (artifactId) => {
    if (!selectedDefinition || !artifactId) return;
    const source = artifactSources.find((item) => item.artifactId === artifactId);
    setArtifactStates((current) => ({ ...current, [artifactId]: { status: "loading", message: "" } }));
    try {
      const analysisSource = source?.sourceKind === "analysisRun" || source?.artifactSourceKind === "analysisRun";
      const analysisRun = analysisSource
        ? await analysisClient.getRunArtifact(source.requestId || source.artifactRequestId)
        : null;
      const artifact = analysisSource
        ? adaptAnalysisRunArtifact(analysisRun)
        : await client.getArtifact(
          source?.definitionId || selectedDefinition.definitionId,
          source?.definitionVersion ?? selectedDefinition.version,
          artifactId,
        );
      if (!artifact) throw new Error("완전한 검증 근거가 있는 분석 결과만 보고서에 추가할 수 있습니다.");
      if (!reportEvidenceReady(artifact)) throw new Error("검증 근거가 완전하지 않아 보고서 결과를 표시하지 않습니다.");
      setArtifacts((current) => ({ ...current, [artifactId]: artifact }));
      applyHydratedArtifactViewSizing({ [artifactId]: artifact }, selectedDefinition);
      setArtifactSources((current) => current.map((item) => item.artifactId === artifactId ? {
        ...item,
        queryId: artifact.query_id,
        artifactChecksum: item.artifactChecksum || artifact.artifact_checksum,
        sourceUrns: artifact.evidence.sources.map((entry) => entry.urn),
        ...(analysisSource ? { title: analysisArtifactTitle(artifact, item.definitionTitle, item) } : {}),
      } : item));
      setArtifactStates((current) => ({ ...current, [artifactId]: { status: artifact?.table?.rows?.length === 0 ? "empty" : "success", message: "" } }));
      setNotice("분석 결과를 다시 불러왔습니다.");
    } catch (nextError) {
      setArtifactStates((current) => ({ ...current, [artifactId]: { status: "error", message: apiError(nextError), requiredAction: apiRequiredAction(nextError) } }));
    }
  };
  const openEditor = async (definition) => {
    let current = await fetchDefinition(definition);
    if (!current) return;
    if (current.status === "approved") {
      const existingDraft = definitions
        .filter((item) => item.definitionId === current.definitionId && item.status === "draft")
        .sort((left, right) => right.version - left.version)[0];
      if (existingDraft) {
        current = await fetchDefinition(existingDraft);
        if (!current) return;
        setNotice(`기존 v${current.version} 초안을 이어서 편집합니다.`);
      } else {
        if (!window.confirm(`확정본 v${current.version}을 기준으로 새 편집 버전을 만들까요?`)) return;
        current = await mutate("next-draft", () => client.createNextDraft(current.definitionId, current.version));
        if (!current) return;
        setNotice(`확정본을 기준으로 v${current.version} 초안을 만들었습니다.`);
      }
    }
    const localDraft = loadFrontendDraft(window.sessionStorage, current.definitionId, current.version);
    const recoverLocalDraft = Boolean(localDraft
      && draftLayoutSignature(localDraft.blocks) !== draftLayoutSignature(current.blocks));
    const editable = recoverLocalDraft ? { ...current, blocks: localDraft.blocks } : current;
    setAssistantTrace(null);
    upsertDefinition(editable, {
      orientation: current.orientation,
      currencyPolicy: {
        ...DEFAULT_FRONTEND_CURRENCY_POLICY,
        displayUnit: current.currencyDisplayUnit,
      },
      ...(recoverLocalDraft ? { serverBlocks: current.blocks, forceDirty: true } : {}),
    }); setView("editor");
    if (recoverLocalDraft) {
      setNotice("이 브라우저에 남아 있던 구성을 복구했습니다. 서버 저장본과 다르므로 검토한 뒤 저장해 주세요.");
    }
    await loadArtifacts(editable, true);
  };
  const saveDraft = async () => {
    if (!selectedDefinition || !isDraft || pending) return;
    const invalid = orderedBlocks.find((block) => !block.title?.trim() || (block.type === "text" && !block.content?.trim()));
    if (invalid) {
      setSelectedBlockId(invalid.id);
      setSaveFailed(true);
      setError(!invalid.title?.trim() ? "블록 제목을 입력한 뒤 저장해 주세요." : `“${invalid.title}” 블록의 내용을 입력한 뒤 저장해 주세요.`);
      window.requestAnimationFrame(() => {
        const target = document.querySelector(`[data-block-id="${CSS.escape(invalid.id)}"] ${!invalid.title?.trim() ? ".notion-block-title" : ".notion-markdown-input"}`);
        target?.focus(); target?.scrollIntoView({ block: "center" });
      });
      return;
    }
    const snapshot = createFrontendDraftSnapshot({
      definitionId: selectedDefinition.definitionId,
      version: selectedDefinition.version,
      title: selectedDefinition.title,
      orientation: reportOrientation,
      currencyPolicy: reportCurrencyPolicy,
      blocks: orderedBlocks,
    });
    if (!snapshot.ok) {
      setSaveFailed(true);
      setError(snapshot.errors?.[0] || "보고서 초안을 구성하지 못했습니다.");
      return;
    }
    setPending("save"); setError(""); setNotice(""); setSaveFailed(false);
    try {
      const persistedBlocks = compactDraftLayout(orderedBlocks);
      const saved = await client.replaceDraftBlocks(
        selectedDefinition.definitionId, selectedDefinition.version, persistedBlocks.map(toReportBlockRequest),
        { orientation: reportOrientation, currencyDisplayUnit: reportCurrencyPolicy.displayUnit },
      );
      saveFrontendDraft(window.sessionStorage, snapshot.snapshot);
      upsertDefinition({ ...saved, blocks: snapshot.snapshot.blocks }, {
        orientation: saved.orientation,
        currencyPolicy: {
          ...DEFAULT_FRONTEND_CURRENCY_POLICY,
          displayUnit: saved.currencyDisplayUnit,
        },
      });
      setNotice("변경사항을 저장했습니다.");
    } catch (nextError) {
      setError(apiError(nextError)); setSaveFailed(true);
    } finally {
      setPending("");
    }
  };
  const approveDefinition = async () => {
    if (!selectedDefinition || !isDraft) return;
    if (isDirty) {
      setError("저장되지 않은 변경사항을 먼저 저장한 뒤 PDF를 확정해 주세요.");
      return;
    }
    if (!window.confirm(`v${selectedDefinition.version} 저장된 HTML 초안을 확정하고 수정할 수 없는 PDF를 생성할까요?`)) return;
    const approved = await mutate("approve", () => client.approveDefinition(
      selectedDefinition.definitionId, selectedDefinition.version, new Date().toISOString(), reportOrientation,
    ));
    if (approved) {
      const finalized = { ...approved, blocks: [...blocksRef.current] };
      upsertDefinition(finalized, { orientation: reportOrientation, currencyPolicy: reportCurrencyPolicy }); setView("document");
      await loadFinalDocument(finalized);
      setNotice("PDF 확정본을 생성했습니다. 이 버전은 더 이상 수정할 수 없습니다.");
    }
  };
  const openFinalAsset = async (format, download = false) => {
    if (!selectedDefinition || selectedDefinition.status !== "approved") return;
    const popup = download ? null : window.open("", "_blank");
    if (!download && !popup) {
      setError("새 탭이 차단되었습니다. 팝업을 허용하거나 다운로드를 이용해 주세요."); return;
    }
    if (popup) popup.opener = null;
    setPending(`${format}-${download ? "download" : "open"}`); setError(""); setNotice("");
    try {
      const body = format === "pdf"
        ? await client.getFinalPdf(selectedDefinition.definitionId, selectedDefinition.version)
        : await client.getFinalHtml(selectedDefinition.definitionId, selectedDefinition.version);
      const blob = body instanceof Blob ? body : new Blob([body], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      if (download) {
        const link = document.createElement("a");
        link.href = url; link.download = `report-v${selectedDefinition.version}.${format}`;
        document.body.append(link); link.click(); link.remove();
      } else {
        popup.location.href = url;
      }
      window.setTimeout(() => URL.revokeObjectURL(url), download ? 0 : 60000);
      setNotice(download ? "PDF 확정본을 다운로드했습니다." : `${format === "pdf" ? "PDF 확정본" : "확정 HTML"}을 새 탭에서 열었습니다.`);
    } catch (nextError) {
      popup?.close(); setError(apiError(nextError));
    } finally {
      setPending("");
    }
  };
  const loadRuns = async () => {
    if (!selectedDefinition) return;
    const items = await mutate("runs", () => client.listRuns(selectedDefinition.definitionId));
    if (items) { setRuns([...items]); setVisibleRunCount(REPORT_RUN_PAGE_SIZE); setSelectedRun(items[0] || null); }
  };
  const runDefinition = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "approved") return;
    const receipt = await mutate("run", () => client.createManualRun({
      definition_id: selectedDefinition.definitionId, version: selectedDefinition.version,
      as_of: new Date().toISOString(), idempotency_key: createUuid(),
    }));
    if (!receipt) return;
    setNotice(`보고서 실행을 요청했습니다. · ${runStatusLabel(receipt.status)}`);
    if (receipt.run_id) {
      const run = await mutate("run-detail", () => client.getRun(receipt.run_id));
      if (run) { setSelectedRun(run); setRuns((current) => [run, ...current.filter((item) => item.runId !== run.runId)]); }
    }
  };
  const createSchedule = async () => {
    if (!selectedDefinition || selectedDefinition.status !== "approved" || !scheduleAt) return;
    const schedule = await mutate("schedule-create", () => client.createSchedule({
      schedule_id: createUuid(), definition_id: selectedDefinition.definitionId,
      version: selectedDefinition.version, cadence, next_run_at: seoulWallClockToIso(scheduleAt), timezone: "Asia/Seoul",
    }));
    if (schedule) { setSchedules((current) => [...current, schedule]); setNotice("서울 시간 기준 예약을 만들었습니다."); }
  };
  const setScheduleEnabled = async (scheduleId, enabled) => {
    const schedule = await mutate("schedule-update", () => client.setScheduleEnabled(scheduleId, enabled));
    if (schedule) { setSchedules((current) => current.map((item) => item.schedule_id === scheduleId ? schedule : item)); setNotice(schedule.enabled ? "예약 실행을 재개했습니다." : "예약 실행을 중지했습니다."); }
  };
  const createAssistantDraft = async () => {
    if (!selectedArtifactSource?.artifactId || !selectedArtifact || !assistantInstruction.trim()) return;
    const result = await mutate("assistant", () => client.createAssistantDraft(selectedArtifactSource.artifactId, assistantInstruction.trim()));
    if (!result) return;
    upsertDefinition(result.definition, { currencyPolicy: DEFAULT_FRONTEND_CURRENCY_POLICY }); setAssistantTrace({ requestId: result.requestId, ...result.trace });
    setAssistantInstruction(""); setNotice("AI 초안을 만들었습니다. 게시하거나 확정하기 전에 내용을 검토해 주세요."); setView("editor");
  };

  const updateBlock = (blockId, change, record = true) => commitBlocks((current) => {
    const next = current.map((block) => block.id === blockId ? { ...block, ...change } : block);
    if (!Object.hasOwn(change, "content")) return next;
    return compactDraftLayout(next.map((block) => (
      block.id === blockId && block.type === "text"
        ? { ...block, h: frontendTextBlockLayout(block, reportOrientation).height }
        : block
    )));
  }, record);
  const frontendReportContext = (orientation = reportOrientation) => ({
    definitionId: selectedDefinition?.definitionId || "report-draft",
    version: selectedDefinition?.version || 1,
    title: selectedDefinition?.title || "보고서 초안",
    orientation,
    currencyPolicy: currencyPolicyRef.current,
  });
  const addWholeArtifact = (artifactId, position = null) => {
    const source = artifactOptions.find((item) => item.artifactId === artifactId);
    if (!source) { setNotice("추가할 Artifact를 불러온 뒤 다시 시도해 주세요."); return false; }
    const artifact = artifacts[artifactId];
    const autoLayout = estimateArtifactBlockLayout(artifact, {
      orientation: reportOrientation,
      visibleViews: WHOLE_ARTIFACT_VIEWS,
      ...(position?.w ? { width: position.w } : {}),
    });
    const analysisSource = source.sourceKind === "analysisRun" || source.artifactSourceKind === "analysisRun";
    const blockId = createUuid();
    const result = insertFrontendArtifact(blocksRef.current, {
      blockId,
      title: source.title || source.definitionTitle || "분석 결과",
      artifactId,
      artifactChecksum: source.artifactChecksum || artifact?.artifact_checksum,
      ...(!analysisSource ? {
        artifactDefinitionId: source.definitionId,
        artifactDefinitionVersion: source.definitionVersion,
      } : {
        sourceKind: "analysisRun",
        requestId: source.requestId || source.artifactRequestId,
        analysisDefinitionId: source.analysisDefinitionId,
        analysisDefinitionVersion: source.analysisDefinitionVersion,
      }),
      queryId: source.queryId || artifact?.query_id,
      question: source.question,
      sourceUrns: source.sourceUrns,
      artifact,
      visibleViews: WHOLE_ARTIFACT_VIEWS,
      sizeMode: "auto",
      width: position?.w ?? autoLayout.width,
      height: autoLayout.height,
      placement: position?.placement || { type: "end", pageId: position?.pageId },
    }, frontendReportContext());
    if (!result.ok) { setError(result.errors?.[0] || "Artifact 전체 블록을 추가하지 못했습니다."); return false; }
    commitBlocks(result.blocks);
    setSelectedBlockId(blockId);
    setNotice("Artifact 전체를 요약·KPI·차트·표가 포함된 하나의 블록으로 추가했습니다.");
    return true;
  };
  const moveBlock = (blockId, deltaX, deltaY) => {
    const source = blocksRef.current.find((block) => block.id === blockId);
    if (!source) return;
    const x = Math.min(12 - (source.w ?? source.columns), Math.max(0, (source.x ?? 0) + deltaX));
    const y = Math.max(0, (source.y ?? 0) + deltaY);
    if (x === source.x && y === source.y) return;
    commitBlocks((current) => placeDraftBlock(current, blockId, x, y));
    setEditorAnnouncement(`${source.title || "제목 없음"} 블록을 ${y + 1}행 ${x + 1}열로 이동했습니다.`);
  };
  const resizeBlock = (blockId, requestedWidth, requestedHeight) => commitBlocks((current) => {
    const sourceBlock = current.find((block) => block.id === blockId);
    if (!sourceBlock) return current;
    const minimumWidth = sourceBlock.type === "text" ? 4 : 6;
    const value = Math.max(minimumWidth, Math.min(12, requestedWidth));
    const contentMinimumHeight = sourceBlock.type === "text"
      ? frontendTextBlockLayout({ ...sourceBlock, w: value, columns: value, h: 4 }, reportOrientation).minimumHeight
      : 4;
    const minimumHeight = sourceBlock.type === "artifact" ? 5 : sourceBlock.type === "chart" ? 7 : sourceBlock.type === "table" ? 5 : contentMinimumHeight;
    const maximumHeight = ["artifact", "chart", "table"].includes(sourceBlock.type) ? 18 : 14;
    const height = requestedHeight === undefined ? Math.max(sourceBlock.h ?? minimumHeight, minimumHeight) : Math.max(minimumHeight, Math.min(maximumHeight, requestedHeight));
    if (value === (sourceBlock.w ?? sourceBlock.columns) && height === (sourceBlock.h ?? minimumHeight)) return current;
    const resizeRow = requestedHeight !== undefined && height !== (sourceBlock.h ?? minimumHeight);
    const resized = current.map((block) => {
      if (block.id === blockId) return {
        ...block, columns: value, w: value, h: height, x: Math.min(block.x ?? 0, 12 - value),
        ...(["artifact", "chart", "table"].includes(block.type) ? { content: JSON.stringify({ ...blockSettings(block), sizeMode: "manual" }) } : {}),
      };
      return resizeRow && block.y === sourceBlock.y ? { ...block, h: height } : block;
    });
    setEditorAnnouncement(`${sourceBlock.title || "제목 없음"} 블록 크기를 너비 ${value}/12, 높이 ${height}단으로 변경했습니다.`);
    return compactDraftLayout(resized);
  });
  const setBlockSetting = (blockId, name, value) => {
    const source = blocksRef.current.find((block) => block.id === blockId);
    if (!source) return;
    const settings = { ...blockSettings(source), [name]: value };
    const wholeArtifactAutoSizing = source.type === "artifact"
      && (name === "sizeMode" ? value === "auto" : wholeArtifactSettings(source)?.sizeMode === "auto");
    const artifactViewAutoSizing = ["chart", "table"].includes(source.type)
      && (name === "sizeMode" ? value === "auto" : artifactViewBlockSettings(source)?.sizeMode === "auto");
    if (!wholeArtifactAutoSizing && !artifactViewAutoSizing) { updateBlock(blockId, { content: JSON.stringify(settings) }); return; }
    commitBlocks((current) => compactDraftLayout(current.map((block) => {
      if (block.id !== blockId) return block;
      return wholeArtifactAutoSizing
        ? fitFrontendArtifactBlock(block, artifacts[source.artifactId], {
            orientation: reportOrientation, force: true, settings,
          })
        : fitFrontendArtifactViewBlock(block, artifacts[source.artifactId], {
            orientation: reportOrientation, force: true, settings,
          });
    })));
    setEditorAnnouncement(`${source.title || "분석 결과"} 블록 크기를 내용에 맞췄습니다.`);
  };
  const createTemplateBlock = (templateId, position = null) => {
    const template = REPORT_TEMPLATE_MAP.get(templateId);
    if (!template) return null;
    const current = blocksRef.current;
    const defaultY = current.reduce((bottom, block) => Math.max(bottom, (block.y ?? 0) + (block.h ?? 1)), 0);
    const id = createUuid();
    if (!templateId.startsWith("artifact-")) {
      const block = {
      id, title: template.blockTitle, columns: template.w, type: "text", content: template.content,
      x: position?.x ?? 0, y: position?.y ?? defaultY, w: position?.w ?? template.w, h: template.h,
      };
      return { ...block, h: frontendTextBlockLayout(block, reportOrientation).height };
    }

    const type = templateId === "artifact-chart" ? "chart" : "table";
    const source = artifactOptions.find((block) => block.artifactId === artifactSelection) || artifactOptions[0];
    if (!source?.artifactId) {
      setNotice("먼저 분석 결과를 보고서로 가져오면 표와 차트를 추가할 수 있습니다.");
      return null;
    }
    if (type === "chart" && !artifacts[source.artifactId]?.chart) {
      setNotice("선택한 분석 결과에는 차트 데이터가 없습니다.");
      return null;
    }
    const nextBlock = {
      ...source, id, type, title: `${source.title} ${type === "chart" ? "차트" : "표"}`,
      content: type === "chart" ? JSON.stringify({ showLegend: true, sizeMode: "auto" }) : JSON.stringify({ density: "comfortable", sizeMode: "auto" }),
      x: position?.x ?? 0, y: position?.y ?? defaultY, w: position?.w ?? template.w,
      columns: position?.w ?? template.w, h: template.h,
    };
    return fitFrontendArtifactViewBlock(nextBlock, artifacts[source.artifactId], {
      orientation: reportOrientation, force: true,
    });
  };
  const addTemplateBlock = (templateId, position = null) => {
    const block = createTemplateBlock(templateId, position);
    if (!block) return false;
    const requestedX = position?.requestedX ?? block.x;
    commitBlocks((current) => {
      const placed = placeDraftBlock([...current, block], block.id, requestedX, block.y);
      return templateId.startsWith("artifact-")
        ? fitAutoArtifactViewLayout(placed, artifacts, reportOrientation)
        : placed;
    });
    setSelectedBlockId(block.id);
    return true;
  };
  const duplicateBlock = (blockId) => {
    const current = blocksRef.current;
    const source = current.find((block) => block.id === blockId);
    if (!source) return;
    const duplicate = { ...source, id: createUuid(), title: `${source.title} 복사본`, y: (source.y ?? 0) + (source.h ?? 1) };
    commitBlocks(placeDraftBlock([...current, duplicate], duplicate.id, duplicate.x ?? 0, duplicate.y));
    setSelectedBlockId(duplicate.id);
  };
  const deleteBlock = (blockId) => {
    const ordered = [...blocksRef.current].sort((left, right) => (left.y ?? 0) - (right.y ?? 0) || (left.x ?? 0) - (right.x ?? 0));
    const index = ordered.findIndex((block) => block.id === blockId);
    const nextFocusId = ordered[index + 1]?.id || ordered[index - 1]?.id || "";
    const deleted = deleteFrontendBlock(blocksRef.current, blockId, frontendReportContext());
    commitBlocks(deleted.ok ? deleted.blocks : compactDraftLayout(blocksRef.current.filter((block) => block.id !== blockId)));
    setSelectedBlockId(nextFocusId);
    setNotice("블록을 삭제했습니다. 실행 취소로 되돌릴 수 있습니다.");
    window.requestAnimationFrame(() => {
      const target = nextFocusId
        ? document.querySelector(`[data-block-id="${CSS.escape(nextFocusId)}"]`)
        : document.querySelector(".report-empty-canvas button");
      target?.focus();
    });
  };
  const dragDestination = (active, delta) => {
    const activeId = String(active.id);
    const source = blocksRef.current.find((block) => block.id === activeId);
    const template = activeId.startsWith("template:")
      ? viewArtifactTemplateFor(REPORT_TEMPLATE_MAP.get(activeId.slice("template:".length)))
      : null;
    const libraryArtifact = activeId.startsWith("artifact:")
      ? artifactOptions.find((item) => item.artifactId === activeId.slice("artifact:".length))
      : null;
    const dragTemplate = template || (libraryArtifact ? wholeArtifactTemplateFor(libraryArtifact) : null);
    if (!source && !dragTemplate) return null;
    const initial = active.rect.current.initial;
    const center = pointerDragRef.current && dragPointerRef.current
      ? dragPointerRef.current
      : initial
        ? { x: initial.left + initial.width / 2 + delta.x, y: initial.top + initial.height / 2 + delta.y }
        : null;
    if (!center) return null;
    const targetCanvas = [...pageCanvasRefs.current.values()].find(({ element }) => {
      const bounds = element.getBoundingClientRect();
      return center.x >= bounds.left && center.x <= bounds.right && center.y >= bounds.top && center.y <= bounds.bottom;
    });
    if (!targetCanvas) return null;
    const { element: canvas, page } = targetCanvas;
    const styles = window.getComputedStyle(canvas);
    const bounds = canvas.getBoundingClientRect();
    const scale = canvas.offsetWidth ? bounds.width / canvas.offsetWidth : 1;
    const paddingLeft = (Number.parseFloat(styles.paddingLeft) || 0) * scale;
    const paddingRight = (Number.parseFloat(styles.paddingRight) || 0) * scale;
    const paddingTop = (Number.parseFloat(styles.paddingTop) || 0) * scale;
    const padding = paddingLeft + paddingRight;
    const columnGap = (Number.parseFloat(styles.columnGap) || 0) * scale;
    const contentWidth = Math.max(1, bounds.width - padding);
    const columnStep = Math.max(1, (contentWidth - columnGap * 11) / 12 + columnGap);
    const rowHeight = (Number.parseFloat(styles.getPropertyValue("--report-grid-row")) || 56) * scale;
    const rowStep = rowHeight + (Number.parseFloat(styles.rowGap) || 0) * scale;
    const w = source ? source.w ?? source.columns : dragTemplate.w;
    const h = source ? source.h ?? 1 : dragTemplate.h;
    const pointerColumn = Math.min(11, Math.max(0, Math.floor((center.x - bounds.left - paddingLeft) / columnStep)));
    const pointerRow = Math.max(0, Math.floor((center.y - bounds.top - paddingTop) / rowStep)) + page.offsetY;
    const fullRowTarget = blocksRef.current.find((block) => (
      block.id !== activeId && (block.w ?? block.columns) === 12
      && pointerRow >= (block.y ?? 0) && pointerRow < (block.y ?? 0) + (block.h ?? 1)
    ));
    const contentTarget = fullRowTarget || blocksRef.current
      .filter((block) => block.id !== activeId)
      .sort((left, right) => {
        const leftCenter = (left.y ?? 0) + (left.h ?? 1) / 2;
        const rightCenter = (right.y ?? 0) + (right.h ?? 1) / 2;
        return Math.abs(leftCenter - pointerRow) - Math.abs(rightCenter - pointerRow);
      })[0];
    const rawX = Math.round((center.x - bounds.left - paddingLeft) / columnStep - w / 2);
    const requestedX = fullRowTarget ? (pointerColumn < 6 ? 0 : 6) : Math.max(0, rawX);
    const dropWidth = fullRowTarget ? 6 : w;
    const dropHeight = !source && template?.id?.startsWith("artifact-")
      ? viewArtifactTemplateFor(template, dropWidth).h
      : !source && libraryArtifact
        ? wholeArtifactTemplateFor(libraryArtifact, dropWidth).h
        : h;
    const y = fullRowTarget
      ? fullRowTarget.y ?? 0
      : Math.max(page.offsetY, Math.round((center.y - bounds.top - paddingTop) / rowStep - dropHeight / 2) + page.offsetY);
    return {
      pageId: page.id,
      x: fullRowTarget ? (pointerColumn < 6 ? 0 : 6) : Math.min(12 - w, Math.max(0, rawX)),
      requestedX,
      y,
      w: dropWidth,
      h: dropHeight,
      placement: fullRowTarget
        ? { type: "side", targetBlockId: fullRowTarget.id, edge: pointerColumn < 6 ? "left" : "right" }
        : contentTarget
          ? { type: pointerRow < (contentTarget.y ?? 0) + (contentTarget.h ?? 1) / 2 ? "before" : "after", targetBlockId: contentTarget.id }
          : { type: "end", pageId: page.id },
    };
  };
  const finishDrag = ({ active, delta }) => {
    const activeId = String(active.id);
    const libraryTemplate = activeId.startsWith("template:")
      ? viewArtifactTemplateFor(REPORT_TEMPLATE_MAP.get(activeId.slice("template:".length)))
      : activeId.startsWith("artifact:")
        ? wholeArtifactTemplateFor(artifactOptions.find((item) => item.artifactId === activeId.slice("artifact:".length)))
        : null;
    const keyboardPosition = !pointerDragRef.current && libraryTemplate
      ? keyboardEndDropPosition(blocksRef.current, {
        pageId: reportPages.at(-1)?.id,
        width: libraryTemplate.w,
        height: libraryTemplate.h,
      })
      : null;
    const position = dropPosition ?? dropPositionRef.current ?? dragDestination(active, delta) ?? keyboardPosition;
    let succeeded = false;
    if (activeId.startsWith("artifact:")) {
      if (position) succeeded = addWholeArtifact(activeId.slice("artifact:".length), position);
    } else if (activeId.startsWith("template:")) {
      if (position) succeeded = addTemplateBlock(activeId.slice("template:".length), position);
    } else {
      const source = blocksRef.current.find((block) => block.id === activeId);
      if (position && source && (position.x !== source.x || position.y !== source.y)) {
        commitBlocks((current) => {
          const moved = moveFrontendBlock(current, activeId, position.placement, frontendReportContext());
          return moved.ok ? moved.blocks : placeDraftBlock(current, activeId, position.requestedX, position.y);
        });
        succeeded = true;
      }
    }
    const message = succeeded
      ? `${dragLabel(activeId)}을 문서에 놓았습니다.`
      : `${dragLabel(activeId)}은 유효한 위치가 없어 이동을 취소했습니다. 원래 구성을 유지합니다.`;
    lastDropOutcomeRef.current = { success: succeeded, message };
    setEditorAnnouncement(message);
    pointerDragRef.current = false; dragPointerRef.current = null; dropPositionRef.current = null;
    setDraggedBlockId(""); setDropPosition(null);
  };
  const handleEditorKeyDown = (event) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key === "s" && canEdit) { event.preventDefault(); void saveDraft(); return; }
    const textField = ["input", "textarea"].includes(event.target.tagName.toLowerCase());
    if (textField && !event.target.closest?.(".notion-block")) return;
    if (key === "z" && event.shiftKey) { event.preventDefault(); redo(); }
    else if (key === "z") { event.preventDefault(); undo(); }
    else if (key === "y") { event.preventDefault(); redo(); }
  };
  const changeEditorOrientation = (orientation) => {
    if (orientation === reportOrientation) return;
    const contentSized = compactDraftLayout(blocksRef.current.map((block) => (
      block.type === "text"
        ? { ...block, h: frontendTextBlockLayout(block, orientation).height }
        : block.type === "artifact" && wholeArtifactSettings(block)?.sizeMode === "auto"
          ? fitFrontendArtifactBlock(block, artifacts[block.artifactId], { orientation })
          : ["chart", "table"].includes(block.type) && artifactViewBlockSettings(block)?.sizeMode === "auto"
            ? fitFrontendArtifactViewBlock(block, artifacts[block.artifactId], { orientation })
            : block
    )));
    const reflowed = orientFrontendBlocks(contentSized, orientation, frontendReportContext(orientation));
    if (!reflowed.ok) { setError(reflowed.errors?.[0] || "A4 방향에 맞게 보고서를 재배치하지 못했습니다."); return; }
    commitBlocks(fitAutoArtifactViewLayout(reflowed.blocks, artifacts, orientation));
    setReportOrientation(orientation);
    setIsDirty(true);
  };
  const changeReportCurrencyUnit = (displayUnit) => {
    const next = { ...currencyPolicyRef.current, displayUnit };
    currencyPolicyRef.current = next;
    setReportCurrencyPolicy(next);
    setIsDirty(draftChanged(blocksRef.current, next));
  };
  const leaveEditor = () => {
    if (isDirty && !window.confirm("저장하지 않은 변경사항이 있습니다. 편집을 종료할까요?")) return;
    setView("list");
  };
  const previewEditor = () => {
    if (isDirty) { setError("변경사항을 저장한 뒤 HTML 초안을 확인해 주세요."); return; }
    setFinalDocument(null); setFinalDocumentState("idle");
    if (selectedDefinition) setSelectedDefinition({ ...selectedDefinition, blocks: [...blocks] });
    setView("document");
    if (selectedDefinition) void loadArtifacts({ ...selectedDefinition, blocks: [...blocks] });
  };
  const returnToEditor = () => {
    const restoreEditorFocus = () => window.requestAnimationFrame(() => {
      const canvases = [...pageCanvasRefs.current.values()].map(({ element }) => element);
      const selectedBlock = selectedBlockId
        ? canvases.map((canvas) => canvas.querySelector(`[data-block-id="${CSS.escape(selectedBlockId)}"]`)).find(Boolean)
        : null;
      (selectedBlock || canvases.map((canvas) => canvas.querySelector("[data-block-id]")).find(Boolean))?.focus({ preventScroll: true });
    });
    if (selectedDefinition?.status === "draft") {
      setView("editor");
      restoreEditorFocus();
      return;
    }
    if (selectedDefinition) void openEditor(selectedDefinition).then(restoreEditorFocus);
  };
  const dragLabel = (activeId) => {
    const id = String(activeId);
    if (id.startsWith("template:")) return `${REPORT_TEMPLATE_MAP.get(id.slice("template:".length))?.title || "새"} 블록`;
    if (id.startsWith("artifact:")) return `${artifactOptions.find((item) => item.artifactId === id.slice("artifact:".length))?.title || "분석 결과"} Artifact 전체 블록`;
    const block = blocksRef.current.find((item) => item.id === id);
    return `${block?.title || "제목 없음"} ${block?.type === "artifact" ? "Artifact 전체" : block?.type === "chart" ? "차트" : block?.type === "table" ? "표" : "텍스트"} 블록`;
  };
  const dragPositionMessage = (activeId) => {
    const position = dropPositionRef.current;
    if (position) return `${dragLabel(activeId)}, ${position.y + 1}행 ${position.x + 1}열, 너비 ${position.w}/12 위치`;
    const block = blocksRef.current.find((item) => item.id === String(activeId));
    return block ? `${dragLabel(activeId)}, ${Number(block.y ?? 0) + 1}행 ${Number(block.x ?? 0) + 1}열` : dragLabel(activeId);
  };
  const saveStatus = pending === "save" ? "saving" : saveFailed ? "error" : isDirty ? "unsaved" : "saved";
  const artifactStateFor = (artifactId) => artifactId ? artifactStates[artifactId] || { status: "loading", message: "" } : null;
  const renderReportPageHeader = ({ pageNumber, pageCount }) => <><div className="answer-report-page-title"><small>ANSWERVICE · HOTEL INTELLIGENCE</small><h1>{selectedDefinition?.title || "호텔 운영 분석 보고서"}</h1><p>{assistantTrace ? "AI 초안 · 검토 필요" : statusLabel(selectedDefinition?.status)} · v{selectedDefinition?.version} · {pageNumber}/{pageCount}페이지</p></div><span className="answer-report-draft-mark">{selectedDefinition?.status === "approved" ? "확정본" : "HTML 편집 초안"}</span></>;
  const renderReportPageFooter = () => <span>분석 근거 연결 · HTML 편집본</span>;

  if (view === "list") return <div className="page-content enterprise-reports-list">
    <div className={`legacy-report-toolbar ${definitionState === "empty" ? "is-empty" : ""}`}>
      <button type="button" className="primary" aria-expanded={createOpen} onClick={() => setCreateOpen((open) => !open)}><FilePlus2 size={15} />새 보고서</button>
      {definitionState === "ready" && <><label className="report-search"><span>검색</span><input aria-label="보고서 검색" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="보고서 제목 검색" /></label>
      <label><span>상태</span><select aria-label="보고서 상태" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">전체</option><option value="draft">초안</option><option value="approved">확정</option></select></label></>}
      <button type="button" className="report-refresh" onClick={() => void loadDefinitions()} disabled={Boolean(pending)}><RotateCcw size={14} />새로고침</button>
    </div>
    {createOpen && <section className="report-create-shell"><form className="report-create-form" onSubmit={createDefinition} aria-busy={pending === "create"}><header><div><small>새 초안</small><h2>보고서 작성을 시작하세요</h2><p>제목만 입력해도 편집기로 바로 이동합니다.</p></div><button type="button" onClick={() => setCreateOpen(false)}>닫기</button></header><label><span>보고서 제목</span><input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="예: 8월 객실 매출 운영 보고서" autoFocus required /></label><label><span>첫 문단 <small>선택</small></span><textarea value={newContent} onChange={(event) => setNewContent(event.target.value)} placeholder="지금 작성하거나 편집기에서 나중에 입력할 수 있습니다." /></label><footer><button type="button" onClick={() => setCreateOpen(false)}>취소</button><button className="primary" disabled={Boolean(pending) || !newTitle.trim()}>{pending === "create" ? <LoaderCircle size={14} /> : <FilePlus2 size={14} />}{pending === "create" ? "만드는 중" : "편집 시작"}</button></footer></form></section>}
    {error && <p ref={errorRef} tabIndex={-1} className="report-api-state error" role="alert">{/^40[13]/.test(error) ? <ShieldAlert size={17} /> : <AlertTriangle size={17} />}{error}</p>}
    {definitionState === "loading" && <p className="report-api-state"><LoaderCircle size={17} />보고서를 불러오는 중입니다.</p>}
    {definitionState === "empty" && !createOpen && <section className="report-empty-state"><span><FilePlus2 size={24} /></span><small>첫 보고서</small><h2>아직 작성한 보고서가 없습니다</h2><p>새 초안을 만들면 서버에 저장되고 편집 화면으로 바로 이동합니다.</p><button type="button" className="primary" onClick={() => setCreateOpen(true)}><FilePlus2 size={15} />첫 보고서 만들기</button></section>}
    {definitionState === "error" && <p className="report-api-state error"><ShieldAlert size={17} />보고서 목록을 불러오지 못했습니다.</p>}
    {definitionState === "ready" && <section className="card legacy-report-list"><div className="legacy-report-row legacy-report-head"><span>상태</span><span>버전·제목</span><span>구성</span><span>최근 변경</span><span>동작</span></div>{visibleDefinitions.map((definition) => <article className="legacy-report-row" key={`${definition.definitionId}-${definition.version}`}><strong>{statusLabel(definition.status)}</strong><b>v{definition.version}<small>{definition.title}</small></b><span>{definition.blocks.length}개 블록</span><span>{definition.approvedAt ? formatSeoulTime(definition.approvedAt) : "편집 중"}</span><nav className="legacy-report-actions" aria-label={`${definition.title} 동작`}><button className="edit" onClick={() => void openEditor(definition)}>{definition.status === "approved" ? "새 버전으로 편집" : "편집"}</button><button className="view" onClick={() => void openPreview(definition)}>열람 <ChevronRight size={13} /></button></nav></article>)}</section>}
    {definitionState === "ready" && !visibleDefinitions.length && <p className="report-api-state"><Inbox size={17} />검색 조건에 맞는 보고서가 없습니다.</p>}
    {definitionState === "ready" && <p className="legacy-report-guide">초안은 자유롭게 배치하고 서버에 저장할 수 있습니다. 확정본 편집 시 새 버전 초안이 생성됩니다.</p>}
  </div>;

  if (view === "document" && selectedDefinition) return <div className="page-content legacy-report-document generated-preview">
    <div className="legacy-document-actions"><button className="secondary" onClick={leaveEditor}><ArrowLeft size={14} />보고서 목록</button><div><ReportCurrencyControl value={reportCurrencyPolicy.displayUnit} onChange={changeReportCurrencyUnit} disabled={selectedDefinition.status === "approved"} /><div className="report-orientation-switch" role="group" aria-label={selectedDefinition.status === "approved" ? "확정된 A4 용지 방향" : "PDF A4 용지 방향"}><button type="button" aria-pressed={reportOrientation === "landscape"} disabled={selectedDefinition.status === "approved"} onClick={() => changeEditorOrientation("landscape")}><Maximize2 size={14} />가로</button><button type="button" aria-pressed={reportOrientation === "portrait"} disabled={selectedDefinition.status === "approved"} onClick={() => changeEditorOrientation("portrait")}><Minimize2 size={14} />세로</button></div><button onClick={returnToEditor}><ArrowLeft size={14} />{selectedDefinition.status === "approved" ? "새 버전으로 편집" : "편집으로 돌아가기"}</button>{isAdmin && selectedDefinition.status === "approved" && <button onClick={() => void runDefinition()} disabled={Boolean(pending)}><Send size={14} />보고서 실행</button>}</div></div>
    {error && <p ref={errorRef} tabIndex={-1} className="report-api-state error" role="alert"><AlertTriangle size={17} />{error}</p>}
    {notice && <p className="report-api-state" role="status"><Check size={17} />{notice}</p>}
    {selectedDefinition.status === "draft" ? <section className="report-finalization-panel" aria-labelledby="report-finalization-title">
      <div className="report-finalization-copy"><span><Eye size={18} aria-hidden="true" /></span><div><small>HTML 초안 · 검토 단계</small><h2 id="report-finalization-title">저장된 HTML 초안을 확인하세요</h2><p>내용과 A4 방향을 검토한 뒤 PDF 확정본을 생성합니다.</p></div></div>
      <div className="report-finalization-action">
        {isDirty ? <p className="report-finalization-blocker" role="alert"><AlertTriangle size={16} aria-hidden="true" /><span>문단 높이 또는 표시 설정이 변경되었습니다. 편집 화면에서 저장한 뒤 PDF를 확정해 주세요.</span></p> : <p><LockKeyhole size={15} aria-hidden="true" /><span>확정하면 v{selectedDefinition.version}은 수정할 수 없습니다. 이후 변경은 새 버전에서 진행합니다.</span></p>}
        {isAdmin ? <button type="button" className="primary" onClick={() => void approveDefinition()} disabled={Boolean(pending) || isDirty}>{pending === "approve" ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <LockKeyhole size={15} aria-hidden="true" />}{pending === "approve" ? "PDF 생성 중" : "확정하고 PDF 생성"}</button> : <small>PDF 확정은 보고서 관리자에게 요청해 주세요.</small>}
      </div>
    </section> : <section className="report-finalization-panel is-final" aria-labelledby="report-final-title" aria-busy={finalDocumentState === "loading"}>
      <div className="report-finalization-copy"><span><LockKeyhole size={18} aria-hidden="true" /></span><div><small>PDF 확정본 · 수정 불가</small><h2 id="report-final-title">확정된 문서를 안전하게 보관하고 있습니다</h2><p>이 버전은 변경되지 않습니다. 수정하려면 새 버전을 만드세요.</p></div></div>
      {finalDocumentState === "loading" && <p className="report-finalization-loading" role="status"><LoaderCircle className="spin" size={15} aria-hidden="true" />확정 문서 정보를 확인하는 중입니다.</p>}
      {finalDocumentState === "missing" && <p className="report-finalization-blocker" role="status"><AlertTriangle size={16} aria-hidden="true" /><span>이전 방식으로 확정된 버전이라 저장된 PDF가 없습니다.</span></p>}
      {finalDocumentState === "error" && <button type="button" onClick={() => void loadFinalDocument(selectedDefinition)}><RotateCcw size={14} aria-hidden="true" />문서 정보 다시 불러오기</button>}
      {finalDocumentState === "ready" && finalDocument && <div className="report-finalization-result"><dl><div><dt>확정 시각</dt><dd>{formatSeoulTime(finalDocument.confirmedAt)}</dd></div><div><dt>용지</dt><dd>A4 {finalDocument.orientation === "landscape" ? "가로" : "세로"}</dd></div><div><dt>포함 Artifact</dt><dd>{finalDocument.artifactVersions.length}개</dd></div><div><dt>PDF 식별값</dt><dd><code title={finalDocument.pdfChecksum}>{finalDocument.pdfChecksum.slice(0, 12)}…</code></dd></div></dl><nav aria-label="확정 문서 동작"><button type="button" onClick={() => void openFinalAsset("html")} disabled={Boolean(pending)}><ExternalLink size={14} aria-hidden="true" />확정 HTML 열기</button><button type="button" className="primary" onClick={() => void openFinalAsset("pdf")} disabled={Boolean(pending)}><ExternalLink size={14} aria-hidden="true" />PDF 새 탭에서 열기</button><button type="button" onClick={() => void openFinalAsset("pdf", true)} disabled={Boolean(pending)}><Download size={14} aria-hidden="true" />PDF 다운로드</button></nav></div>}
    </section>}
    <section className="report-preview-meta-strip" aria-label="보고서 미리보기 정보"><b>{selectedDefinition.status === "draft" ? "저장된 A4 HTML 초안" : "보고서 구성 미리보기"}</b><span>{statusLabel(selectedDefinition.status)} · v{selectedDefinition.version}</span><span>{selectedDefinition.blocks.length}개 블록</span><span>{selectedDefinition.approvedAt ? formatSeoulTime(selectedDefinition.approvedAt) : `PDF ${reportOrientation === "landscape" ? "가로" : "세로"}`}</span></section>
    <ReportPageCanvas pages={reportPages} orientation={reportOrientation} mode="preview" ariaLabel={`${selectedDefinition.title} A4 미리보기`} renderHeader={renderReportPageHeader} renderFooter={renderReportPageFooter} renderBlock={(layoutBlock) => { const block = layoutBlock.sourceBlock || layoutBlock; return <GeneratedReportBlock block={block} number={reportBlockNumbers.get(block.id)} rowOffset={0} artifact={block.artifactId ? artifacts[block.artifactId] : null} artifactState={artifactStateFor(block.artifactId)} currency={reportCurrency} orientation={reportOrientation} onRetry={block.artifactId ? () => void retryArtifact(block.artifactId) : undefined} />; }} />
  </div>;

  return <DndContext
    sensors={sensors}
    onDragStart={({ active, activatorEvent }) => {
      const activeId = String(active.id);
      pointerDragRef.current = Number.isFinite(activatorEvent?.clientX) && Number.isFinite(activatorEvent?.clientY);
      dragPointerRef.current = pointerDragRef.current ? { x: activatorEvent.clientX, y: activatorEvent.clientY } : null;
      dropPositionRef.current = null;
      lastDropOutcomeRef.current = { success: false, message: "" };
      setDraggedBlockId(activeId);
      if (!activeId.startsWith("template:") && !activeId.startsWith("artifact:")) setSelectedBlockId(activeId);
    }}
    onDragMove={({ active, delta }) => {
      const position = dragDestination(active, delta);
      dropPositionRef.current = position;
      setDropPosition(position);
    }}
    onDragEnd={finishDrag}
    onDragCancel={({ active }) => { const message = `${dragLabel(active.id)} 이동을 취소했습니다. 원래 위치를 유지합니다.`; lastDropOutcomeRef.current = { success: false, message }; setEditorAnnouncement(message); pointerDragRef.current = false; dragPointerRef.current = null; dropPositionRef.current = null; setDraggedBlockId(""); setDropPosition(null); }}
    accessibility={{
      screenReaderInstructions: { draggable: "블록을 이동하려면 Enter 또는 Space를 누르세요. 방향키로 위치를 바꾸고 Enter 또는 Space로 놓습니다. Escape를 누르면 취소합니다." },
      announcements: {
        onDragStart: ({ active }) => `${dragLabel(active.id)} 이동을 시작했습니다. 방향키로 위치를 선택하세요.`,
        onDragMove: ({ active }) => dragPositionMessage(active.id),
        onDragEnd: ({ active }) => lastDropOutcomeRef.current.message || `${dragLabel(active.id)} 이동을 종료했습니다. 문서 구성을 확인해 주세요.`,
        onDragCancel: ({ active }) => `${dragLabel(active.id)} 이동을 취소했습니다. 원래 위치를 유지합니다.`,
      },
    }}
  ><div className={`enterprise-report-editor notion-report-editor ${toolPanelOpen ? "" : "tools-collapsed"}`} onPointerMoveCapture={(event) => { if (pointerDragRef.current) dragPointerRef.current = { x: event.clientX, y: event.clientY }; }} onKeyDown={handleEditorKeyDown}>
    {toolPanelOpen && <button type="button" className="editor-tools-scrim" aria-label="블록 도구 닫기" onClick={() => setToolPanelOpen(false)} />}
    {toolPanelOpen && <aside ref={toolPanelRef} tabIndex={-1} className="editor-library notion-editor-sidebar" aria-label="블록 도구"><header><div><p>보고서 편집</p><h2>블록 도구</h2><span>문단과 근거가 연결된 분석 결과를 끌어 문서를 구성합니다.</span></div><button type="button" className="editor-library-close" aria-label="블록 도구 닫기" onClick={() => setToolPanelOpen(false)}><PanelLeftClose size={16} aria-hidden="true" /></button></header>
      {isDraft && <section className="notion-insert"><h3><Plus size={14} />블록 추가</h3><p className="report-template-label">빠른 블록</p><div className="report-insert-grid">{REPORT_TEMPLATES.slice(0, 2).map((template) => <ReportTemplateTile template={template} onAdd={addTemplateBlock} disabled={!canEdit} key={template.id} />)}</div><p className="report-template-label">보고서 템플릿</p><div className="report-insert-grid report-template-grid">{REPORT_TEMPLATES.slice(2).map((template) => <ReportTemplateTile template={template} onAdd={addTemplateBlock} disabled={!canEdit} key={template.id} />)}</div><p className="report-template-label">Artifact 전체</p><div className="report-artifact-library" aria-label="분석 Artifact 라이브러리">{artifactOptions.length ? artifactOptions.map((source) => <ReportArtifactLibraryTile source={source} artifact={artifacts[source.artifactId]} disabled={!canEdit || artifactStates[source.artifactId]?.status === "loading"} onAdd={addWholeArtifact} key={source.artifactId} />) : <p className="report-artifact-library-empty">{analysisLibraryState.status === "loading" ? "저장된 분석 결과를 확인하는 중입니다." : "보고서에 사용할 분석 결과가 없습니다."}</p>}</div>{analysisLibraryState.status !== "loading" && analysisLibraryState.message && <small className="report-insert-help" role={analysisLibraryState.status === "error" ? "alert" : "status"}>{analysisLibraryState.message}</small>}<small className="report-insert-help">Artifact 전체는 요약·KPI·차트·표를 한 블록으로 유지합니다. 원하는 위치로 끌어다 놓으세요. 행은 빈 공간 없이 자동 정렬됩니다.</small><label className="report-artifact-picker"><span>개별 보기용 Artifact</span><select aria-label="표 또는 차트로 삽입할 분석 결과" value={artifactSelection} onChange={(event) => setArtifactSelection(event.target.value)} disabled={!canEdit || !artifactOptions.length}>{artifactOptions.length ? artifactOptions.map((block) => <option value={block.artifactId} key={block.artifactId}>{block.title}</option>) : <option value="">연결된 결과 없음</option>}</select></label><div className="report-insert-grid">{ARTIFACT_TEMPLATES.map((template) => <ReportTemplateTile template={template} onAdd={addTemplateBlock} disabled={!canEdit || !artifactOptions.length || (template.id === "artifact-chart" && !selectedArtifact?.chart)} key={template.id} />)}</div><small className="report-insert-help">표 보기만·차트 보기만은 기존 보고서 호환을 위한 개별 보기입니다. 클릭하거나 끌어 원하는 위치에 추가하세요.</small></section>}
      <nav className="notion-outline" aria-label="보고서 목차"><p>목차</p>{orderedBlocks.map((block, index) => <button type="button" onClick={() => setSelectedBlockId(block.id)} aria-pressed={selectedBlockId === block.id} key={block.id}><span>{String(index + 1).padStart(2, "0")}</span><b>{block.title || "제목 없음"}</b></button>)}</nav>
      {selectedDefinition?.blocks.some((block) => block.artifactId) && <details className="notion-assistant"><summary><Sparkles size={14} />AI 초안 만들기</summary><div className="assistant-source-preview"><b>선택한 원본</b><span>{selectedArtifact?.title || selectedArtifactSource?.title || "분석 결과를 선택해 주세요."}</span><small>{selectedArtifactPeriod ? `${selectedArtifactPeriod.start} ~ ${selectedArtifactPeriod.end_exclusive} 미포함` : "기간 정보 없음"}</small><small>{selectedArtifact?.evidence?.sources?.length ? `출처 ${selectedArtifact.evidence.sources.map((source) => source.name).join("·")}` : "출처 정보 없음"}</small></div><textarea aria-label="AI 초안 지시" value={assistantInstruction} onChange={(event) => setAssistantInstruction(event.target.value)} maxLength={500} placeholder="예: 핵심 수치와 시사점을 경영진용으로 요약해줘" /><button onClick={() => void createAssistantDraft()} disabled={Boolean(pending) || !selectedArtifact || !assistantInstruction.trim()}><Sparkles size={14} />선택한 원본으로 AI 초안 생성</button><small>생성 결과는 AI 초안이며 확정 전에 검토가 필요합니다.</small></details>}
    </aside>}
    <main className="editor-workspace notion-editor-workspace"><header className="editor-topbar notion-editor-topbar"><div><button onClick={leaveEditor}><ArrowLeft size={14} aria-hidden="true" />보고서</button><span className="notion-status-chip">{statusLabel(selectedDefinition?.status)} · v{selectedDefinition?.version}</span></div><div><div className="editor-view-actions" aria-label="편집 화면 설정"><button ref={toolToggleRef} type="button" aria-pressed={toolPanelOpen} aria-label={toolPanelOpen ? "블록 도구 숨기기" : "블록 도구 열기"} title={toolPanelOpen ? "블록 도구 숨기기" : "블록 도구 열기"} onClick={() => setToolPanelOpen((open) => !open)}>{toolPanelOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}<span>도구</span></button><ReportCurrencyControl value={reportCurrencyPolicy.displayUnit} onChange={changeReportCurrencyUnit} disabled={!canEdit} /><div className="report-orientation-switch" role="group" aria-label="A4 용지 방향"><button type="button" aria-pressed={reportOrientation === "landscape"} title="A4 가로" onClick={() => changeEditorOrientation("landscape")}><Maximize2 size={15} /><span>가로</span></button><button type="button" aria-pressed={reportOrientation === "portrait"} title="A4 세로" onClick={() => changeEditorOrientation("portrait")}><Minimize2 size={15} /><span>세로</span></button></div></div><div className="editor-history-actions" aria-label="편집 기록"><button type="button" aria-label="실행 취소" title="실행 취소 (Ctrl+Z)" onClick={undo} disabled={Boolean(pending) || !history.past.length}><Undo2 size={14} /></button><button type="button" aria-label="다시 실행" title="다시 실행 (Ctrl+Y)" onClick={redo} disabled={Boolean(pending) || !history.future.length}><Redo2 size={14} /></button></div><span className={`editor-save-state ${saveStatus}`} role="status">{saveStatus === "saving" ? <LoaderCircle className="spin" size={13} aria-hidden="true" /> : saveStatus === "error" ? <AlertTriangle size={13} aria-hidden="true" /> : saveStatus === "unsaved" ? <Clock3 size={13} aria-hidden="true" /> : <Check size={13} aria-hidden="true" />}{saveStatus === "saving" ? "저장 중" : saveStatus === "error" ? "저장 실패" : saveStatus === "unsaved" ? "저장되지 않은 변경" : "저장됨"}</span><button title={isDirty ? "변경사항을 먼저 저장해 주세요" : "저장된 HTML 초안 확인"} onClick={previewEditor} disabled={Boolean(pending) || isDirty}><Eye size={14} aria-hidden="true" />HTML 초안 확인</button>{isDraft && <button className="primary" aria-label="보고서 저장" onClick={() => void saveDraft()} disabled={Boolean(pending) || !isDirty}><Save size={14} aria-hidden="true" />저장</button>}{isAdmin && selectedDefinition?.status === "approved" && <button className="primary" onClick={() => void runDefinition()} disabled={Boolean(pending)}><Send size={14} aria-hidden="true" />실행</button>}</div></header>
      {error && <p ref={errorRef} tabIndex={-1} className="report-api-state error" role="alert"><AlertTriangle size={17} />{error}</p>}{notice && <p className="report-api-state notion-editor-notice" role="status"><Check size={17} />{notice}</p>}
      <section className="report-a4-editor-shell" aria-label="A4 보고서 편집" aria-busy={pending === "save"}>
        <ReportPageCanvas
          pages={reportPages}
          orientation={reportOrientation}
          mode="editor"
          ariaLabel={`${selectedDefinition?.title || "보고서"} A4 편집 영역`}
          renderHeader={renderReportPageHeader}
          renderFooter={renderReportPageFooter}
          gridClassName={`editor-canvas report-api-blocks notion-canvas ${draggedBlockId ? "drop-ready is-drop-ready" : ""}`}
          getGridRef={registerPageCanvas}
          renderGridOverlay={(context) => <>
            {dropPosition?.pageId === context.page.id && <div aria-hidden="true" className="report-drop-preview" style={{ gridColumn: `${dropPosition.x + 1} / span ${dropPosition.w}`, gridRow: `${Math.max(0, dropPosition.y - context.page.offsetY) + 1} / span ${dropPosition.h}` }}><span>{activeInsert ? `${activeArtifactSource?.title || activeInsert.title} 놓기` : "여기에 이동"}</span></div>}
            {!orderedBlocks.length && context.pageIndex === 0 && <div className="report-empty-canvas"><span><Plus size={19} aria-hidden="true" /></span><h2>첫 블록을 추가하세요</h2><p>왼쪽 편집 도구에서 템플릿을 끌어오거나 클릭해서 시작할 수 있습니다.</p><button type="button" onClick={() => addTemplateBlock("text")} disabled={!canEdit}><Type size={14} aria-hidden="true" />텍스트 블록 추가</button></div>}
          </>}
          renderBlock={(layoutBlock, context) => {
            const block = layoutBlock.sourceBlock || layoutBlock;
            return <ReportEditorBlock block={block} rowOffset={context.page.offsetY} artifact={block.artifactId ? artifacts[block.artifactId] : null} artifactState={artifactStateFor(block.artifactId)} currency={reportCurrency} isDraft={canEdit} selected={selectedBlockId === block.id} dragging={draggedBlockId === block.id} onSelect={() => setSelectedBlockId(block.id)} onUpdate={(change, record) => updateBlock(block.id, change, record)} onMove={(x, y) => moveBlock(block.id, x, y)} onResize={(width, height) => resizeBlock(block.id, width, height)} onSetting={(name, value) => setBlockSetting(block.id, name, value)} onDuplicate={() => duplicateBlock(block.id)} onDelete={() => deleteBlock(block.id)} onRetryArtifact={block.artifactId ? () => void retryArtifact(block.artifactId) : undefined} />;
          }}
        />
      </section>
      {isAdmin && selectedDefinition?.status === "approved" && <details className="card editor-advanced"><summary>실행 및 예약 관리</summary><section className="report-run-actual"><header><h3>실행 이력</h3><button onClick={() => void loadRuns()} disabled={Boolean(pending)}><RotateCcw size={13} />불러오기</button></header><label className="report-search"><span>실행 검색</span><input value={runQuery} onChange={(event) => { setRunQuery(event.target.value); setVisibleRunCount(REPORT_RUN_PAGE_SIZE); }} placeholder="상태·버전·오류 검색" /></label>{visibleRuns.length ? <ul>{visibleRuns.map((run) => <li key={run.runId}><button type="button" aria-pressed={selectedRun?.runId === run.runId} onClick={() => setSelectedRun(run)}><b>{runStatusLabel(run.status)}</b><span>v{run.definitionVersion} · 기준 {formatSeoulTime(run.asOf)}</span></button></li>)}</ul> : <p className="report-api-state"><Inbox size={17} />{runs.length ? "검색 조건에 맞는 실행이 없습니다." : "실행 이력이 없습니다."}</p>}{filteredRuns.length > visibleRunCount && <button type="button" onClick={() => setVisibleRunCount((count) => count + REPORT_RUN_PAGE_SIZE)}>실행 더 보기</button>}{selectedRun && <article className="report-run-detail"><header><div><b>{runStatusLabel(selectedRun.status)}</b><span>v{selectedRun.definitionVersion} · 데이터 기준 {formatSeoulTime(selectedRun.asOf)}</span></div>{["failed", "partial"].includes(selectedRun.status) && <button type="button" onClick={() => void runDefinition()} disabled={Boolean(pending)}><RotateCcw size={13} />다시 실행</button>}</header><ul>{selectedRun.blocks.map((block) => <li key={block.blockId}><div><b>{runStatusLabel(block.status)}</b><span>{block.failureMessage || "블록 실행 결과가 저장되었습니다."}</span>{block.failureCode && <small>오류 코드 {block.failureCode}</small>}<details><summary>기술 정보</summary><code>Artifact {block.artifactId || "없음"}</code><code>Query {block.queryId || "없음"}</code></details></div></li>)}</ul></article>}</section><section className="report-schedule-actual"><header><div><h3>예약 실행</h3><small>입력값은 브라우저 위치와 관계없이 서울 현지 시각으로 저장합니다.</small></div></header><div className="report-schedule-form"><label>주기<select value={cadence} onChange={(event) => setCadence(event.target.value)}><option value="daily">매일</option><option value="weekly">매주</option><option value="monthly">매월</option></select></label><label>다음 실행 시각 (Asia/Seoul)<input type="datetime-local" value={scheduleAt} onChange={(event) => setScheduleAt(event.target.value)} /></label><button className="primary" onClick={() => void createSchedule()} disabled={Boolean(pending) || !scheduleAt}><Clock3 size={14} />예약 생성</button></div><div className="report-schedule-list">{selectedSchedules.map((schedule) => <article key={schedule.schedule_id}><div><b>{schedule.cadence === "daily" ? "매일" : schedule.cadence === "weekly" ? "매주" : "매월"} · {schedule.enabled ? "실행 중" : "중지됨"}</b><small>다음 실행 {formatSeoulTime(schedule.next_run_at)}</small></div><button onClick={() => void setScheduleEnabled(schedule.schedule_id, !schedule.enabled)}>{schedule.enabled ? "중지" : "재개"}</button></article>)}</div></section></details>}
      {assistantTrace && <details className="card editor-advanced"><summary>AI 처리 정보</summary><p>초안 생성을 완료했습니다. · {(assistantTrace.duration_ms / 1000).toFixed(1)}초</p></details>}
      <p className="sr-only" aria-live="polite">{editorAnnouncement}</p>
    </main>
  </div><DragOverlay dropAnimation={{ duration: 160, easing: "ease-out" }}>{activeInsert && <div className="report-template-overlay">{ActiveTemplateIcon && <ActiveTemplateIcon size={16} />}<span><b>{activeArtifactSource?.title || activeInsert.title}</b><small>{activeArtifactSource ? "Artifact 전체로 추가" : "캔버스에 놓아 추가"}</small></span></div>}</DragOverlay></DndContext>;
}

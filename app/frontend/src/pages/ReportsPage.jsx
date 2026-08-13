import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ArrowUpDown, Bold, Check,
  ChevronRight, Clock3, Columns2, Copy, Eye, FileBarChart, FilePlus2,
  GripVertical, Heading2, Inbox, Italic, Link2, List, LoaderCircle,
  Maximize2, Minimize2, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Plus,
  Quote, Redo2, RotateCcw, Save, Send, ShieldAlert, Sparkles, Table2, Trash2,
  Type, Undo2,
} from "lucide-react";
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, TouchSensor, useDraggable,
  useSensor, useSensors,
} from "@dnd-kit/core";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { createReportClient, ReportApiError } from "../api/reportClient";
import { compactDraftLayout, placeDraftBlock, toReportBlockRequest } from "../contracts/report";
import { createUuid } from "../utils/createUuid";

function apiError(error) {
  if (error instanceof ReportApiError && error.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (error instanceof ReportApiError && error.status === 403) return "현재 계정은 이 기능을 사용할 수 없습니다.";
  if (error instanceof ReportApiError && error.status >= 500) return "보고서 서버에 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.";
  if (error instanceof TypeError) return "서버에 연결할 수 없습니다. 네트워크 연결을 확인한 뒤 다시 시도해 주세요.";
  return error instanceof Error ? error.message : "보고서 요청을 처리하지 못했습니다.";
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

const REPORT_COLUMN_LABELS = {
  month: "월", business_date: "일자",
  recognized_room_revenue: "인식 객실 매출",
  recognized_room_revenue_krw: "인식 객실 매출",
  total_guest_revenue_krw: "객실·식음 통합 매출",
};

function reportValue(value, column) {
  const numeric = typeof value === "number" ? value : typeof value === "string" && /^-?\d+(?:\.\d+)?$/.test(value) ? Number(value) : null;
  const rendered = numeric !== null && Number.isFinite(numeric) ? numeric.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) : String(value ?? "—");
  return /(?:revenue|_krw)$/.test(column) ? `${rendered} KRW` : rendered;
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

const REPORT_SERIES_COLORS = ["#5b9df5", "#d3a45c", "#6bc49b", "#b58cf2"];

const REPORT_TEMPLATES = [
  { id: "text", title: "텍스트", description: "문단·목록·Markdown", icon: Type, blockTitle: "새 텍스트", content: "새 문단을 작성하세요.", w: 12, h: 4 },
  { id: "section", title: "섹션", description: "소제목이 있는 문단", icon: Heading2, blockTitle: "새 섹션", content: "## 새 섹션\n섹션 내용을 입력하세요.", w: 12, h: 4 },
  { id: "executive", title: "경영진 요약", description: "결론과 비즈니스 영향", icon: Sparkles, blockTitle: "경영진 요약", content: "## 핵심 결론\n가장 중요한 결과를 한 문장으로 정리하세요.\n\n## 비즈니스 영향\n의사결정에 미치는 영향을 작성하세요.", w: 12, h: 5 },
  { id: "kpi", title: "핵심 지표", description: "수치와 의미를 한눈에", icon: Columns2, blockTitle: "핵심 지표", content: "| 지표 | 값 | 의미 |\n| --- | ---: | --- |\n| 핵심 지표 | 값 입력 | 의미를 작성하세요 |", w: 6, h: 5 },
  { id: "insight", title: "핵심 인사이트", description: "해석을 강조하는 콜아웃", icon: Quote, blockTitle: "핵심 인사이트", content: "> 데이터가 말하는 핵심 변화와 그 의미를 간결하게 작성하세요.", w: 6, h: 4 },
  { id: "actions", title: "권고 사항", description: "실행 항목과 후속 조치", icon: List, blockTitle: "권고 사항", content: "- [ ] 우선 실행할 조치\n- [ ] 담당자와 기한 확인\n- [ ] 후속 지표 모니터링", w: 6, h: 4 },
];

const ARTIFACT_TEMPLATES = [
  { id: "artifact-table", title: "표", description: "원본 데이터를 행으로", icon: Table2, w: 12, h: 5 },
  { id: "artifact-chart", title: "차트", description: "막대·선 전환 가능", icon: FileBarChart, w: 12, h: 7 },
];

const REPORT_TEMPLATE_MAP = new Map([...REPORT_TEMPLATES, ...ARTIFACT_TEMPLATES].map((template) => [template.id, template]));

function blockSettings(block) {
  if (block.type === "text" || !block.content) return {};
  try {
    const parsed = JSON.parse(block.content);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function ReportArtifactContent({ block, artifact, editor = false }) {
  const [sorting, setSorting] = useState({ column: "", direction: "" });
  if (!artifact?.table) {
    return <div className="report-artifact-loading"><LoaderCircle size={16} /><span>분석 데이터를 불러오는 중입니다.</span></div>;
  }
  if (block.type === "table") {
    const settings = blockSettings(block);
    const showRowNumbers = settings.showRowNumbers === true;
    const mobileFit = artifact.table.columns.length + Number(showRowNumbers) <= 3;
    const rows = sortedTableRows(artifact.table.rows, sorting);
    return <div className={`analysis-table generated-report-table ${editor ? "editor-artifact-table" : ""} ${mobileFit ? "mobile-fit-table" : ""} ${settings.density === "compact" ? "is-compact" : ""}`}><table><caption className="sr-only">{block.title}</caption><thead><tr>{showRowNumbers && <th scope="col">#</th>}{artifact.table.columns.map((column) => <th scope="col" aria-sort={sorting.column === column ? (sorting.direction === "asc" ? "ascending" : "descending") : "none"} key={column}><button type="button" className="report-table-sort" aria-label={`${REPORT_COLUMN_LABELS[column] || column} 열 정렬`} onClick={() => setSorting((current) => nextTableSort(current, column))}><span>{REPORT_COLUMN_LABELS[column] || column}</span><ArrowUpDown size={12} aria-hidden="true" /></button></th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{showRowNumbers && <th scope="row">{index + 1}</th>}{artifact.table.columns.map((column) => <td className={typeof row[column] === "number" ? "is-numeric" : ""} key={column}>{reportValue(row[column], column)}</td>)}</tr>)}</tbody></table></div>;
  }
  if (block.type === "chart" && artifact.chart && artifact.table.rows.length) {
    const settings = blockSettings(block);
    const chartType = settings.chartType || artifact.chart.chart_type || "bar";
    const yFields = artifact.chart.y_fields.slice(0, REPORT_SERIES_COLORS.length);
    const showLegend = settings.showLegend !== false;
    const common = <><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey={artifact.chart.x_field} tickMargin={9} padding={{ left: 10, right: 10 }} /><YAxis width={editor ? 58 : 68} tickFormatter={(value) => Number(value).toLocaleString("ko-KR", { notation: "compact", maximumFractionDigits: 1 })} />{showLegend && <Legend verticalAlign="top" height={32} />}<Tooltip formatter={(value, name, item) => [reportValue(value, item.dataKey), name]} contentStyle={{ background: "#0b1320", border: "1px solid #35537d", borderRadius: 8 }} /></>;
    const series = yFields.map((field, index) => chartType === "line"
      ? <Line type="monotone" dataKey={field} name={REPORT_COLUMN_LABELS[field] || field} stroke={REPORT_SERIES_COLORS[index]} strokeWidth={3} dot={artifact.table.rows.length <= 12} activeDot={{ r: 5 }} isAnimationActive={false} key={field} />
      : <Bar dataKey={field} name={REPORT_COLUMN_LABELS[field] || field} fill={REPORT_SERIES_COLORS[index]} radius={[4, 4, 0, 0]} isAnimationActive={false} key={field} />);
    const chartMargin = { top: 8, right: editor ? 18 : 24, bottom: 8, left: 0 };
    const chart = chartType === "line"
      ? <LineChart data={artifact.table.rows} margin={chartMargin} accessibilityLayer>{common}{series}</LineChart>
      : <BarChart data={artifact.table.rows} margin={chartMargin} accessibilityLayer>{common}{series}</BarChart>;
    return <figure className={`generated-report-chart-live ${editor ? "editor-artifact-chart" : ""}`} aria-label={`${block.title} 차트`}><ResponsiveContainer width="100%" height={editor ? 240 : 280}>{chart}</ResponsiveContainer><figcaption className="sr-only">{artifact.table.rows.length}개 데이터 행을 {chartType === "line" ? "선" : "막대"} 차트로 표시합니다.</figcaption></figure>;
  }
  return <div className="report-artifact-loading"><AlertTriangle size={16} /><span>표시할 분석 데이터가 없습니다.</span></div>;
}

function prepareEditorLayout(blocks) {
  return compactDraftLayout(blocks.map((block) => {
    const minimumHeight = block.type === "chart" ? 7 : block.type === "table" ? 5 : 4;
    return { ...block, h: Math.max(block.h ?? 1, minimumHeight) };
  }));
}

function GeneratedReportBlock({ block, number, artifact }) {
  const isArtifact = block.type === "table" || block.type === "chart";
  let content = <MarkdownText content={block.content} />;
  if (isArtifact && !artifact) {
    content = <div className="generated-report-copy report-evidence"><small>검증된 데이터</small><b>{block.type === "chart" ? "분석 차트" : "분석 데이터 표"}</b><p>분석 근거를 불러오는 중입니다.</p></div>;
  } else if (isArtifact) {
    content = <ReportArtifactContent block={block} artifact={artifact} />;
  }
  return <article className="card generated-report-block" style={{ "--report-block-width": block.w ?? block.columns }}>
    <header><span>{String(number).padStart(2, "0")}</span><div><small>보고서 섹션</small><h2>{block.title}</h2></div></header>
    {content}
  </article>;
}

function MarkdownBlockEditor({ block, disabled, onUpdate }) {
  const textareaRef = useRef(null);
  const [mode, setMode] = useState("edit");
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
      : <textarea ref={textareaRef} className="notion-markdown-input" aria-label={`${block.title} 내용`} disabled={disabled} value={block.content || ""} onChange={(event) => onUpdate({ content: event.target.value })} placeholder="내용을 입력하세요. Markdown 표·목록·체크박스·링크를 사용할 수 있습니다." />}
  </div>;
}

function ReportBlockMenu({ block, artifact, onMove, onResize, onSetting, onDuplicate, onDelete }) {
  const settings = blockSettings(block);
  const widths = block.type === "text" ? [[4, "좁게"], [6, "절반"], [12, "전체"]] : [[6, "절반"], [12, "전체"]];
  const chartType = settings.chartType || artifact?.chart?.chart_type || "bar";
  return <details className="report-block-menu" name="report-block-menu" onClick={(event) => event.stopPropagation()}>
    <summary aria-label={`${block.title} 블록 메뉴`} title="블록 메뉴"><MoreHorizontal size={17} /></summary>
    <div className="report-block-menu-popover">
      <section><span>블록 너비</span><div className="report-block-widths">{widths.map(([width, label]) => <button type="button" className={(block.w ?? block.columns) === width ? "active" : ""} onClick={() => onResize(width)} key={width}>{label}</button>)}</div></section>
      <section><span>블록 높이</span><div className="report-block-height"><button type="button" aria-label="높이 줄이기" onClick={() => onResize(block.w ?? block.columns, (block.h ?? 4) - 1)}>−</button><output>{block.h ?? 4}단</output><button type="button" aria-label="높이 늘리기" onClick={() => onResize(block.w ?? block.columns, (block.h ?? 4) + 1)}>+</button></div></section>
      <section><span>위치 이동</span><div className="report-block-moves"><button type="button" aria-label="왼쪽으로 이동" title="왼쪽으로 이동" onClick={() => onMove(-1, 0)}><ArrowLeft size={14} /></button><button type="button" aria-label="위로 이동" title="위로 이동" disabled={(block.y ?? 0) === 0} onClick={() => onMove(0, -1)}><ArrowUp size={14} /></button><button type="button" aria-label="아래로 이동" title="아래로 이동" onClick={() => onMove(0, 1)}><ArrowDown size={14} /></button><button type="button" aria-label="오른쪽으로 이동" title="오른쪽으로 이동" onClick={() => onMove(1, 0)}><ArrowRight size={14} /></button></div></section>
      {block.type === "chart" && <section><span>차트 표현</span><div className="report-block-widths"><button type="button" className={chartType === "bar" ? "active" : ""} onClick={() => onSetting("chartType", "bar")}>막대</button><button type="button" className={chartType === "line" ? "active" : ""} onClick={() => onSetting("chartType", "line")}>선</button></div><label><input type="checkbox" checked={settings.showLegend !== false} onChange={(event) => onSetting("showLegend", event.target.checked)} />범례 표시</label></section>}
      {block.type === "table" && <section><span>표 표현</span><div className="report-block-widths"><button type="button" className={settings.density !== "compact" ? "active" : ""} onClick={() => onSetting("density", "comfortable")}>보통</button><button type="button" className={settings.density === "compact" ? "active" : ""} onClick={() => onSetting("density", "compact")}>간결</button></div><label><input type="checkbox" checked={settings.showRowNumbers === true} onChange={(event) => onSetting("showRowNumbers", event.target.checked)} />행 번호 표시</label></section>}
      <div className="report-block-menu-actions"><button type="button" onClick={onDuplicate}><Copy size={14} />복제</button><button type="button" className="danger" onClick={onDelete}><Trash2 size={14} />삭제</button></div>
    </div>
  </details>;
}

function ReportTemplateTile({ template, disabled = false, onAdd }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `template:${template.id}`,
    disabled,
    data: { kind: "template", templateId: template.id },
  });
  const Icon = template.icon;
  return <button
    ref={setNodeRef}
    type="button"
    className={`report-template-tile ${isDragging ? "is-dragging" : ""}`}
    disabled={disabled}
    onClick={() => onAdd(template.id)}
    title="클릭해서 추가하거나 캔버스의 원하는 위치로 끌어다 놓으세요"
    {...listeners}
    {...attributes}
  ><Icon size={15} /><span>{template.title}<small>{template.description}</small></span><GripVertical className="report-template-grip" size={13} aria-hidden="true" /></button>;
}

function ReportEditorBlock({ block, rowOffset, artifact, isDraft, selected, dragging, onSelect, onUpdate, onMove, onResize, onSetting, onDuplicate, onDelete }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform } = useDraggable({ id: block.id, disabled: !isDraft });
  const resizeStart = useRef(null);
  const startResize = (event) => {
    event.stopPropagation();
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
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const resizeWithPointer = (event) => {
    if (!resizeStart.current) return;
    const start = resizeStart.current;
    onResize(start.w + Math.round((event.clientX - start.x) / start.columnStep), start.h + Math.round((event.clientY - start.y) / start.rowStep));
  };
  const resizeWithKeyboard = (event) => {
    const movement = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] }[event.key];
    if (!movement) return;
    event.preventDefault(); event.stopPropagation();
    onResize((block.w ?? block.columns) + movement[0], (block.h ?? 4) + movement[1]);
  };
  const displayY = Math.max(0, (block.y ?? 0) - rowOffset);
  const style = {
    "--block-x": (block.x ?? 0) + 1, "--block-y": displayY + 1,
    "--block-w": block.w ?? block.columns, "--block-h": block.h ?? 1,
    "--block-order": displayY * 12 + (block.x ?? 0),
    gridRow: `${displayY + 1} / span ${block.h ?? 1}`,
    transform: transform ? `translate3d(${Math.round(transform.x)}px, ${Math.round(transform.y)}px, 0)` : undefined,
  };
  return <article ref={setNodeRef} className={`editor-block notion-block ${selected ? "selected" : ""} ${dragging ? "dragging is-dragging" : ""}`} aria-label={`${block.title} 블록`} aria-selected={selected} onClick={onSelect} onFocusCapture={onSelect} style={style}>
    <header className="report-block-chrome"><div className="report-block-title">{isDraft && <button ref={setActivatorNodeRef} type="button" className="report-drag-handle" {...listeners} {...attributes} aria-label={`${block.title} 블록 이동`} title="끌어서 이동 · Space 또는 Enter로 키보드 이동"><GripVertical size={17} /></button>}<span>{block.type === "text" ? "텍스트" : block.type === "chart" ? "차트" : "데이터 표"}</span></div>{isDraft && <ReportBlockMenu block={block} artifact={artifact} onMove={onMove} onResize={onResize} onSetting={onSetting} onDuplicate={onDuplicate} onDelete={onDelete} />}</header>
    {isDraft ? <input className="notion-block-title" aria-label={`${block.title} 제목`} value={block.title} onChange={(event) => onUpdate({ title: event.target.value })} placeholder="블록 제목을 입력하세요" /> : <h2>{block.title}</h2>}
    {block.type === "text" ? <MarkdownBlockEditor block={block} disabled={!isDraft} onUpdate={onUpdate} /> : <div className="notion-data-embed notion-data-embed-live"><div className="notion-data-status"><Columns2 size={19} /><div><small>검증된 데이터</small><b>{block.type === "chart" ? "분석 차트" : "분석 데이터 표"}</b><span>원본 분석 결과와 연결된 콘텐츠입니다.</span></div></div><ReportArtifactContent block={block} artifact={artifact} editor /></div>}
    {isDraft && <button type="button" className="report-resize-handle" aria-label={`${block.title} 블록 크기 조절`} title="끌어서 크기 조절 · 방향키로 미세 조절" onPointerDown={startResize} onPointerMove={resizeWithPointer} onPointerUp={() => { resizeStart.current = null; }} onPointerCancel={() => { resizeStart.current = null; }} onKeyDown={resizeWithKeyboard}><span /></button>}
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

export function ReportsPage({ authToken, role, onEditorMode }) {
  const client = useMemo(() => createReportClient(undefined, fetch, authToken), [authToken]);
  const isAdmin = role === "report_admin";
  const [view, setView] = useState("list");
  const [toolPanelOpen, setToolPanelOpen] = useState(true);
  const [wideDocument, setWideDocument] = useState(true);
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
  const [artifactSources, setArtifactSources] = useState([]);
  const [artifactSelection, setArtifactSelection] = useState("");
  const [history, setHistory] = useState({ past: [], future: [] });
  const blocksRef = useRef([]);
  const savedBlocksRef = useRef([]);
  const canvasRef = useRef(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: reportKeyboardCoordinates }),
  );

  useEffect(() => { onEditorMode?.(view === "editor"); }, [onEditorMode, view]);
  useEffect(() => () => onEditorMode?.(false), [onEditorMode]);

  const isDraft = selectedDefinition?.status === "draft";
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
  const selectedArtifact = artifactSelection ? artifacts[artifactSelection] : null;
  const activeTemplate = draggedBlockId.startsWith("template:")
    ? REPORT_TEMPLATE_MAP.get(draggedBlockId.slice("template:".length))
    : null;
  const ActiveTemplateIcon = activeTemplate?.icon;
  const canvasOffsetY = orderedBlocks.length ? Math.min(...orderedBlocks.map((block) => block.y ?? 0)) : 0;

  const resetBlocks = (nextBlocks, dirty = false) => {
    const next = [...nextBlocks];
    blocksRef.current = next;
    if (!dirty) savedBlocksRef.current = next;
    setBlocks(next);
    setHistory({ past: [], future: [] });
    setIsDirty(dirty);
  };
  const commitBlocks = (updater, record = true) => {
    const current = blocksRef.current;
    const next = typeof updater === "function" ? updater(current) : updater;
    if (!next || next === current) return;
    if (record) setHistory((value) => ({ past: [...value.past.slice(-39), current], future: [] }));
    blocksRef.current = [...next];
    setBlocks([...next]);
    setIsDirty(JSON.stringify(next) !== JSON.stringify(savedBlocksRef.current));
  };
  const undo = () => setHistory((value) => {
    if (!value.past.length) return value;
    const current = blocksRef.current;
    const previous = value.past.at(-1);
    blocksRef.current = [...previous]; setBlocks([...previous]);
    setIsDirty(JSON.stringify(previous) !== JSON.stringify(savedBlocksRef.current));
    return { past: value.past.slice(0, -1), future: [current, ...value.future].slice(0, 40) };
  });
  const redo = () => setHistory((value) => {
    if (!value.future.length) return value;
    const current = blocksRef.current;
    const [next, ...future] = value.future;
    blocksRef.current = [...next]; setBlocks([...next]);
    setIsDirty(JSON.stringify(next) !== JSON.stringify(savedBlocksRef.current));
    return { past: [...value.past, current].slice(-40), future };
  });

  const mutate = async (name, action) => {
    setPending(name); setError(""); setNotice("");
    try { return await action(); } catch (nextError) { setError(apiError(nextError)); return null; } finally { setPending(""); }
  };
  const upsertDefinition = (definition) => {
    setDefinitions((current) => [
      definition,
      ...current.filter((item) => !(item.definitionId === definition.definitionId && item.version === definition.version)),
    ].sort((left, right) => right.version - left.version || left.title.localeCompare(right.title, "ko-KR")));
    setSelectedDefinition(definition);
    resetBlocks(prepareEditorLayout(definition.blocks));
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
    upsertDefinition(definition); setDefinitionState("ready"); setCreateOpen(false);
    if (!initialContent) {
      resetBlocks([{ id: blockId, title: "운영 요약", columns: 12, type: "text", content: "", x: 0, y: 0, w: 12, h: 4 }], true);
      setSelectedBlockId(blockId);
    }
    setNewTitle(""); setNewContent(""); setView("editor");
  };
  const fetchDefinition = async (definition) => mutate("definition", () => client.getDefinition(definition.definitionId, definition.version));
  const openPreview = async (definition) => {
    const current = await fetchDefinition(definition);
    if (!current) return;
    upsertDefinition(current); setView("document");
    await loadArtifacts(current);
  };
  const loadArtifacts = async (definition) => {
    const ids = [...new Set(definition.blocks.map((block) => block.artifactId).filter(Boolean))];
    const seen = new Set();
    setArtifactSources(definition.blocks.filter((block) => {
      if (!block.artifactId || seen.has(block.artifactId)) return false;
      seen.add(block.artifactId); return true;
    }));
    setArtifacts({});
    const loaded = await Promise.all(ids.map(async (artifactId) => {
      try { return [artifactId, await client.getArtifact(definition.definitionId, definition.version, artifactId)]; }
      catch (nextError) { setError(apiError(nextError)); return [artifactId, null]; }
    }));
    setArtifacts(Object.fromEntries(loaded));
    setArtifactSelection((current) => ids.includes(current) ? current : ids[0] || "");
  };
  const openEditor = async (definition) => {
    let current = await fetchDefinition(definition);
    if (!current) return;
    if (current.status === "approved") {
      current = await mutate("next-draft", () => client.createNextDraft(current.definitionId, current.version));
      if (!current) return;
      setNotice(`확정본 v${definition.version}을 기준으로 편집 가능한 v${current.version} 초안을 만들었습니다.`);
    }
    upsertDefinition(current); setView("editor");
    await loadArtifacts(current);
  };
  const saveDraft = async () => {
    if (!selectedDefinition || !isDraft) return;
    const saved = await mutate("save", () => client.replaceDraftBlocks(
      selectedDefinition.definitionId, selectedDefinition.version, orderedBlocks.map(toReportBlockRequest),
    ));
    if (saved) { upsertDefinition(saved); setNotice("변경사항을 저장했습니다."); }
  };
  const approveDefinition = async () => {
    if (!selectedDefinition || !isDraft) return;
    const approved = await mutate("approve", () => client.approveDefinition(
      selectedDefinition.definitionId, selectedDefinition.version, new Date().toISOString(),
    ));
    if (approved) { upsertDefinition(approved); setNotice("보고서를 확정했습니다."); setView("document"); }
  };
  const loadRuns = async () => {
    if (!selectedDefinition) return;
    const items = await mutate("runs", () => client.listRuns(selectedDefinition.definitionId));
    if (items) { setRuns([...items]); setSelectedRun(items.at(-1) || null); }
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
      version: selectedDefinition.version, cadence, next_run_at: new Date(scheduleAt).toISOString(), timezone: "Asia/Seoul",
    }));
    if (schedule) setSchedules((current) => [...current, schedule]);
  };
  const setScheduleEnabled = async (scheduleId, enabled) => {
    const schedule = await mutate("schedule-update", () => client.setScheduleEnabled(scheduleId, enabled));
    if (schedule) setSchedules((current) => current.map((item) => item.schedule_id === scheduleId ? schedule : item));
  };
  const createAssistantDraft = async () => {
    const artifact = selectedDefinition?.blocks.find((block) => block.artifactId);
    if (!artifact || !assistantInstruction.trim()) return;
    const result = await mutate("assistant", () => client.createAssistantDraft(artifact.artifactId, assistantInstruction.trim()));
    if (!result) return;
    upsertDefinition(result.definition); setAssistantTrace({ requestId: result.requestId, ...result.trace });
    setAssistantInstruction(""); setView("editor");
  };

  const updateBlock = (blockId, change, record = true) => commitBlocks(
    (current) => current.map((block) => block.id === blockId ? { ...block, ...change } : block),
    record,
  );
  const moveBlock = (blockId, deltaX, deltaY) => {
    const source = blocksRef.current.find((block) => block.id === blockId);
    if (!source) return;
    const x = Math.min(12 - (source.w ?? source.columns), Math.max(0, (source.x ?? 0) + deltaX));
    const y = Math.max(0, (source.y ?? 0) + deltaY);
    if (x === source.x && y === source.y) return;
    commitBlocks((current) => placeDraftBlock(current, blockId, x, y));
  };
  const resizeBlock = (blockId, requestedWidth, requestedHeight) => commitBlocks((current) => {
    const sourceBlock = current.find((block) => block.id === blockId);
    if (!sourceBlock) return current;
    const minimumWidth = sourceBlock.type === "text" ? 4 : 6;
    const minimumHeight = sourceBlock.type === "chart" ? 7 : sourceBlock.type === "table" ? 5 : 4;
    const value = Math.max(minimumWidth, Math.min(12, requestedWidth));
    const height = requestedHeight === undefined ? sourceBlock.h ?? minimumHeight : Math.max(minimumHeight, Math.min(14, requestedHeight));
    if (value === (sourceBlock.w ?? sourceBlock.columns) && height === (sourceBlock.h ?? minimumHeight)) return current;
    const resized = current.map((block) => block.id === blockId ? {
      ...block, columns: value, w: value, h: height, x: Math.min(block.x ?? 0, 12 - value),
    } : block);
    const source = resized.find((block) => block.id === blockId);
    return source ? placeDraftBlock(resized, blockId, source.x ?? 0, source.y ?? 0) : current;
  });
  const setBlockSetting = (blockId, name, value) => {
    const source = blocksRef.current.find((block) => block.id === blockId);
    if (!source) return;
    updateBlock(blockId, { content: JSON.stringify({ ...blockSettings(source), [name]: value }) });
  };
  const createTemplateBlock = (templateId, position = null) => {
    const template = REPORT_TEMPLATE_MAP.get(templateId);
    if (!template) return null;
    const current = blocksRef.current;
    const defaultY = current.reduce((bottom, block) => Math.max(bottom, (block.y ?? 0) + (block.h ?? 1)), 0);
    const id = createUuid();
    if (!templateId.startsWith("artifact-")) return {
      id, title: template.blockTitle, columns: template.w, type: "text", content: template.content,
      x: position?.x ?? 0, y: position?.y ?? defaultY, w: position?.w ?? template.w, h: template.h,
    };

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
    return {
      ...source, id, type, title: `${source.title} ${type === "chart" ? "차트" : "표"}`,
      content: type === "chart" ? JSON.stringify({ showLegend: true }) : JSON.stringify({ density: "comfortable" }),
      x: position?.x ?? 0, y: position?.y ?? defaultY, w: position?.w ?? template.w,
      columns: position?.w ?? template.w, h: template.h,
    };
  };
  const addTemplateBlock = (templateId, position = null) => {
    const block = createTemplateBlock(templateId, position);
    if (!block) return;
    const requestedX = position?.requestedX ?? block.x;
    commitBlocks((current) => placeDraftBlock([...current, block], block.id, requestedX, block.y));
    setSelectedBlockId(block.id);
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
    commitBlocks((current) => compactDraftLayout(current.filter((block) => block.id !== blockId)));
    setSelectedBlockId("");
    setNotice("블록을 삭제했습니다. 실행 취소로 되돌릴 수 있습니다.");
  };
  const dragDestination = (active, delta) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const activeId = String(active.id);
    const source = blocksRef.current.find((block) => block.id === activeId);
    const template = activeId.startsWith("template:")
      ? REPORT_TEMPLATE_MAP.get(activeId.slice("template:".length))
      : null;
    if (!source && !template) return null;
    const styles = window.getComputedStyle(canvas);
    const bounds = canvas.getBoundingClientRect();
    const paddingLeft = Number.parseFloat(styles.paddingLeft) || 0;
    const paddingRight = Number.parseFloat(styles.paddingRight) || 0;
    const paddingTop = Number.parseFloat(styles.paddingTop) || 0;
    const padding = paddingLeft + paddingRight;
    const columnGap = Number.parseFloat(styles.columnGap) || 0;
    const contentWidth = Math.max(1, bounds.width - padding);
    const columnStep = Math.max(1, (contentWidth - columnGap * 11) / 12 + columnGap);
    const rowHeight = Number.parseFloat(styles.getPropertyValue("--report-grid-row")) || 56;
    const rowStep = rowHeight + (Number.parseFloat(styles.rowGap) || 0);
    const w = source ? source.w ?? source.columns : template.w;
    const h = source ? source.h ?? 1 : template.h;
    if (!source) {
      const initial = active.rect.current.initial;
      if (!initial) return null;
      const left = initial.left + delta.x;
      const top = initial.top + delta.y;
      const width = initial.width;
      const height = initial.height;
      const centerX = left + width / 2;
      const centerY = top + height / 2;
      if (centerX < bounds.left || centerX > bounds.right || centerY < bounds.top || centerY > bounds.bottom) return null;
      const pointerColumn = Math.min(11, Math.max(0, Math.floor((centerX - bounds.left - paddingLeft) / columnStep)));
      const rawX = Math.round((centerX - bounds.left - paddingLeft) / columnStep - w / 2);
      const y = Math.max(0, Math.round((centerY - bounds.top - paddingTop) / rowStep - h / 2)) + canvasOffsetY;
      const requestedX = w === 12 ? (pointerColumn < 6 ? 0 : 6) : Math.max(0, rawX);
      const splitsFullRow = blocksRef.current.some((block) => (
        (block.w ?? block.columns) === 12 && y < (block.y ?? 0) + (block.h ?? 1) && y + h > (block.y ?? 0)
      ));
      const previewWidth = splitsFullRow ? 6 : w;
      return {
        x: splitsFullRow ? (requestedX < 6 ? 0 : 6) : Math.min(12 - w, Math.max(0, rawX)), requestedX,
        y, w: previewWidth, h,
      };
    }
    const rawX = (source.x ?? 0) + Math.round(delta.x / columnStep);
    return {
      x: Math.min(12 - w, Math.max(0, rawX)), requestedX: Math.max(0, rawX),
      y: Math.max(0, (source.y ?? 0) + Math.round(delta.y / rowStep)), w, h,
    };
  };
  const finishDrag = ({ active, delta }) => {
    const activeId = String(active.id);
    const position = dragDestination(active, delta);
    if (activeId.startsWith("template:")) {
      if (position) addTemplateBlock(activeId.slice("template:".length), position);
    } else {
      const source = blocksRef.current.find((block) => block.id === activeId);
      if (position && source && (position.x !== source.x || position.y !== source.y)) {
        commitBlocks((current) => placeDraftBlock(current, activeId, position.requestedX, position.y));
      }
    }
    setDraggedBlockId(""); setDropPosition(null);
  };
  const handleEditorKeyDown = (event) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key === "s" && isDraft) { event.preventDefault(); void saveDraft(); return; }
    if (["input", "textarea"].includes(event.target.tagName.toLowerCase())) return;
    if (key === "z" && event.shiftKey) { event.preventDefault(); redo(); }
    else if (key === "z") { event.preventDefault(); undo(); }
    else if (key === "y") { event.preventDefault(); redo(); }
  };
  const leaveEditor = () => {
    if (isDirty && !window.confirm("저장하지 않은 변경사항이 있습니다. 편집을 종료할까요?")) return;
    setView("list");
  };
  const previewEditor = () => {
    if (selectedDefinition) setSelectedDefinition({ ...selectedDefinition, blocks: [...blocks] });
    setView("document");
    if (selectedDefinition) void loadArtifacts({ ...selectedDefinition, blocks: [...blocks] });
  };
  const returnToEditor = () => {
    if (selectedDefinition?.status === "draft") {
      setView("editor");
      return;
    }
    void openEditor(selectedDefinition);
  };

  if (view === "list") return <div className="page-content enterprise-reports-list">
    <div className={`legacy-report-toolbar ${definitionState === "empty" ? "is-empty" : ""}`}>
      <button type="button" className="primary" aria-expanded={createOpen} onClick={() => setCreateOpen((open) => !open)}><FilePlus2 size={15} />새 보고서</button>
      {definitionState === "ready" && <><label className="report-search"><span>검색</span><input aria-label="보고서 검색" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="보고서 제목 검색" /></label>
      <label><span>상태</span><select aria-label="보고서 상태" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">전체</option><option value="draft">초안</option><option value="approved">확정</option></select></label></>}
      <button type="button" className="report-refresh" onClick={() => void loadDefinitions()} disabled={Boolean(pending)}><RotateCcw size={14} />새로고침</button>
    </div>
    {createOpen && <section className="report-create-shell"><form className="report-create-form" onSubmit={createDefinition} aria-busy={pending === "create"}><header><div><small>새 초안</small><h2>보고서 작성을 시작하세요</h2><p>제목만 입력해도 편집기로 바로 이동합니다.</p></div><button type="button" onClick={() => setCreateOpen(false)}>닫기</button></header><label><span>보고서 제목</span><input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="예: 8월 객실 매출 운영 보고서" autoFocus required /></label><label><span>첫 문단 <small>선택</small></span><textarea value={newContent} onChange={(event) => setNewContent(event.target.value)} placeholder="지금 작성하거나 편집기에서 나중에 입력할 수 있습니다." /></label><footer><button type="button" onClick={() => setCreateOpen(false)}>취소</button><button className="primary" disabled={Boolean(pending) || !newTitle.trim()}>{pending === "create" ? <LoaderCircle size={14} /> : <FilePlus2 size={14} />}{pending === "create" ? "만드는 중" : "편집 시작"}</button></footer></form></section>}
    {error && <p className="report-api-state error" role="alert">{/^40[13]/.test(error) ? <ShieldAlert size={17} /> : <AlertTriangle size={17} />}{error}</p>}
    {definitionState === "loading" && <p className="report-api-state"><LoaderCircle size={17} />보고서를 불러오는 중입니다.</p>}
    {definitionState === "empty" && !createOpen && <section className="report-empty-state"><span><FilePlus2 size={24} /></span><small>첫 보고서</small><h2>아직 작성한 보고서가 없습니다</h2><p>새 초안을 만들면 서버에 저장되고 편집 화면으로 바로 이동합니다.</p><button type="button" className="primary" onClick={() => setCreateOpen(true)}><FilePlus2 size={15} />첫 보고서 만들기</button></section>}
    {definitionState === "error" && <p className="report-api-state error"><ShieldAlert size={17} />보고서 목록을 불러오지 못했습니다.</p>}
    {definitionState === "ready" && <section className="card legacy-report-list"><div className="legacy-report-row legacy-report-head"><span>상태</span><span>버전·제목</span><span>구성</span><span>최근 변경</span><span>동작</span></div>{visibleDefinitions.map((definition) => <article className="legacy-report-row" key={`${definition.definitionId}-${definition.version}`} onClick={() => void openPreview(definition)}><strong>{statusLabel(definition.status)}</strong><b>v{definition.version}<small>{definition.title}</small></b><span>{definition.blocks.length}개 블록</span><span>{definition.approvedAt ? formatSeoulTime(definition.approvedAt) : "편집 중"}</span><nav className="legacy-report-actions"><button className="edit" onClick={(event) => { event.stopPropagation(); void openEditor(definition); }}>편집</button><button className="view" onClick={(event) => { event.stopPropagation(); void openPreview(definition); }}>열람 <ChevronRight size={13} /></button></nav></article>)}</section>}
    {definitionState === "ready" && !visibleDefinitions.length && <p className="report-api-state"><Inbox size={17} />검색 조건에 맞는 보고서가 없습니다.</p>}
    {definitionState === "ready" && <p className="legacy-report-guide">초안은 자유롭게 배치하고 서버에 저장할 수 있습니다. 확정본 편집 시 새 버전 초안이 생성됩니다.</p>}
  </div>;

  if (view === "document" && selectedDefinition) return <div className="page-content legacy-report-document generated-preview">
    <div className="legacy-document-actions"><button className="secondary" onClick={leaveEditor}><ArrowLeft size={14} />보고서 목록</button><div><button onClick={returnToEditor}><ArrowLeft size={14} />편집으로 돌아가기</button>{isAdmin && selectedDefinition.status === "approved" && <button onClick={() => void runDefinition()} disabled={Boolean(pending)}><Send size={14} />보고서 실행</button>}</div></div>
    {error && <p className="report-api-state error" role="alert"><AlertTriangle size={17} />{error}</p>}
    {notice && <p className="report-api-state" role="status"><Check size={17} />{notice}</p>}
    <header className="card generated-report-cover"><div><small>{statusLabel(selectedDefinition.status)} · v{selectedDefinition.version}</small><h1>{selectedDefinition.title}</h1><p>저장된 보고서 내용과 검증된 분석 근거로 구성했습니다.</p></div><dl><div><dt>상태</dt><dd>{statusLabel(selectedDefinition.status)}</dd></div><div><dt>기준 시각</dt><dd>{selectedDefinition.approvedAt ? formatSeoulTime(selectedDefinition.approvedAt) : "편집 중"}</dd></div><div><dt>구성</dt><dd>{selectedDefinition.blocks.length}개 블록</dd></div></dl></header>
    <section className="generated-report-grid">{orderedBlocks.map((block, index) => <GeneratedReportBlock block={block} number={index + 1} artifact={block.artifactId ? artifacts[block.artifactId] : null} key={block.id} />)}</section>
  </div>;

  return <DndContext
    sensors={sensors}
    onDragStart={({ active }) => {
      const activeId = String(active.id);
      setDraggedBlockId(activeId);
      if (!activeId.startsWith("template:")) setSelectedBlockId(activeId);
    }}
    onDragMove={({ active, delta }) => setDropPosition(dragDestination(active, delta))}
    onDragEnd={finishDrag}
    onDragCancel={() => { setDraggedBlockId(""); setDropPosition(null); }}
    accessibility={{ announcements: {
      onDragStart: ({ active }) => String(active.id).startsWith("template:") ? "새 블록을 캔버스로 이동합니다." : "블록 이동을 시작했습니다.",
      onDragEnd: ({ active }) => String(active.id).startsWith("template:") ? "새 블록 배치를 마쳤습니다." : "블록 이동을 마쳤습니다.",
      onDragCancel: () => "블록 이동을 취소했습니다.",
    } }}
  ><div className={`enterprise-report-editor notion-report-editor ${toolPanelOpen ? "" : "tools-collapsed"}`} onKeyDown={handleEditorKeyDown}>
    {toolPanelOpen && <aside className="editor-library notion-editor-sidebar"><header><p>보고서 편집</p><h2>블록 도구</h2><span>문단과 검증된 분석 결과를 끌어 문서를 구성합니다.</span></header>
      {isDraft && <section className="notion-insert"><h3><Plus size={14} />블록 추가</h3><p className="report-template-label">빠른 블록</p><div className="report-insert-grid">{REPORT_TEMPLATES.slice(0, 2).map((template) => <ReportTemplateTile template={template} onAdd={addTemplateBlock} key={template.id} />)}</div><p className="report-template-label">보고서 템플릿</p><div className="report-insert-grid report-template-grid">{REPORT_TEMPLATES.slice(2).map((template) => <ReportTemplateTile template={template} onAdd={addTemplateBlock} key={template.id} />)}</div><label className="report-artifact-picker"><span>분석 결과</span><select aria-label="삽입할 분석 결과" value={artifactSelection} onChange={(event) => setArtifactSelection(event.target.value)} disabled={!artifactOptions.length}>{artifactOptions.length ? artifactOptions.map((block) => <option value={block.artifactId} key={block.artifactId}>{block.title}</option>) : <option value="">연결된 결과 없음</option>}</select></label><div className="report-insert-grid">{ARTIFACT_TEMPLATES.map((template) => <ReportTemplateTile template={template} onAdd={addTemplateBlock} disabled={!artifactOptions.length || (template.id === "artifact-chart" && !selectedArtifact?.chart)} key={template.id} />)}</div><small className="report-insert-help">클릭해서 추가하거나 원하는 위치로 끌어다 놓으세요. 행은 빈 공간 없이 자동 정렬됩니다.</small></section>}
      <nav className="notion-outline" aria-label="보고서 목차"><p>목차</p>{orderedBlocks.map((block, index) => <button type="button" onClick={() => setSelectedBlockId(block.id)} aria-pressed={selectedBlockId === block.id} key={block.id}><span>{String(index + 1).padStart(2, "0")}</span><b>{block.title || "제목 없음"}</b></button>)}</nav>
      {selectedDefinition?.blocks.some((block) => block.artifactId) && <details className="notion-assistant"><summary><Sparkles size={14} />AI로 초안 만들기</summary><textarea aria-label="Assistant 초안 지시" value={assistantInstruction} onChange={(event) => setAssistantInstruction(event.target.value)} maxLength={500} placeholder="예: 핵심 수치와 시사점을 경영진용으로 요약해줘" /><button onClick={() => void createAssistantDraft()} disabled={Boolean(pending) || !assistantInstruction.trim()}><Sparkles size={14} />초안 생성</button></details>}
    </aside>}
    <main className="editor-workspace notion-editor-workspace"><header className="editor-topbar notion-editor-topbar"><div><button onClick={leaveEditor}><ArrowLeft size={14} />보고서</button><span className="notion-status-chip">{statusLabel(selectedDefinition?.status)} · v{selectedDefinition?.version}</span></div><div><div className="editor-view-actions" aria-label="편집 화면 설정"><button type="button" aria-pressed={toolPanelOpen} aria-label={toolPanelOpen ? "블록 도구 숨기기" : "블록 도구 열기"} title={toolPanelOpen ? "블록 도구 숨기기" : "블록 도구 열기"} onClick={() => setToolPanelOpen((open) => !open)}>{toolPanelOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}<span>도구</span></button><button type="button" aria-pressed={wideDocument} aria-label={wideDocument ? "기본 문서 폭으로 보기" : "넓은 문서 폭으로 보기"} title={wideDocument ? "기본 문서 폭으로 보기" : "넓은 문서 폭으로 보기"} onClick={() => setWideDocument((wide) => !wide)}>{wideDocument ? <Minimize2 size={15} /> : <Maximize2 size={15} />}<span>{wideDocument ? "기본 폭" : "넓게"}</span></button></div><div className="editor-history-actions" aria-label="편집 기록"><button type="button" aria-label="실행 취소" title="실행 취소 (Ctrl+Z)" onClick={undo} disabled={!history.past.length}><Undo2 size={14} /></button><button type="button" aria-label="다시 실행" title="다시 실행 (Ctrl+Y)" onClick={redo} disabled={!history.future.length}><Redo2 size={14} /></button></div><span className={`editor-save-state ${pending === "save" ? "saving" : ""}`}>{pending === "save" ? <LoaderCircle size={13} /> : <Check size={13} />}{pending === "save" ? "저장 중" : isDirty ? "저장되지 않은 변경" : "저장됨"}</span><button onClick={previewEditor}><Eye size={14} />미리보기</button>{isDraft && <button className="primary" aria-label="보고서 저장" onClick={() => void saveDraft()} disabled={Boolean(pending) || !isDirty}><Save size={14} />저장</button>}{isAdmin && isDraft && <button title={isDirty ? "변경사항을 먼저 저장해 주세요" : undefined} onClick={() => void approveDefinition()} disabled={Boolean(pending) || isDirty}><Check size={14} />확정</button>}{isAdmin && selectedDefinition?.status === "approved" && <button className="primary" onClick={() => void runDefinition()} disabled={Boolean(pending)}><Send size={14} />실행</button>}</div></header>
      {error && <p className="report-api-state error" role="alert"><AlertTriangle size={17} />{error}</p>}{notice && <p className="report-api-state notion-editor-notice" role="status"><Check size={17} />{notice}</p>}
      <article className={`notion-document ${wideDocument ? "is-wide" : ""}`}><header className="notion-page-heading"><span>{statusLabel(selectedDefinition?.status)}</span><h1>{selectedDefinition?.title}</h1><p>블록을 끌어 구성하세요. 너비와 행 높이는 겹침이나 빈 줄이 생기지 않도록 자동으로 맞춰집니다.</p></header>
        <section ref={canvasRef} className={`editor-canvas report-api-blocks notion-canvas ${draggedBlockId ? "drop-ready is-drop-ready" : ""}`} aria-label="보고서 편집 영역">{dropPosition && <div aria-hidden="true" className="report-drop-preview" style={{ gridColumn: `${dropPosition.x + 1} / span ${dropPosition.w}`, gridRow: `${Math.max(0, dropPosition.y - canvasOffsetY) + 1} / span ${dropPosition.h}` }}><span>{activeTemplate ? `${activeTemplate.title} 놓기` : "여기에 이동"}</span></div>}{orderedBlocks.length ? orderedBlocks.map((block) => <ReportEditorBlock block={block} rowOffset={canvasOffsetY} artifact={block.artifactId ? artifacts[block.artifactId] : null} isDraft={isDraft} selected={selectedBlockId === block.id} dragging={draggedBlockId === block.id} onSelect={() => setSelectedBlockId(block.id)} onUpdate={(change, record) => updateBlock(block.id, change, record)} onMove={(x, y) => moveBlock(block.id, x, y)} onResize={(width, height) => resizeBlock(block.id, width, height)} onSetting={(name, value) => setBlockSetting(block.id, name, value)} onDuplicate={() => duplicateBlock(block.id)} onDelete={() => deleteBlock(block.id)} key={block.id} />) : <div className="report-empty-canvas"><span><Plus size={19} /></span><h2>첫 블록을 추가하세요</h2><p>왼쪽 편집 도구에서 템플릿을 끌어오거나 클릭해서 시작할 수 있습니다.</p><button type="button" onClick={() => addTemplateBlock("text")} disabled={!isDraft}><Type size={14} />텍스트 블록 추가</button></div>}</section>
      </article>
      {isAdmin && selectedDefinition?.status === "approved" && <details className="card editor-advanced"><summary>실행 및 예약 관리</summary><section className="report-run-actual"><header><h3>실행 이력</h3><button onClick={() => void loadRuns()} disabled={Boolean(pending)}><RotateCcw size={13} />불러오기</button></header>{selectedRun ? <p><b>{runStatusLabel(selectedRun.status)}</b><br />데이터 기준일 {selectedRun.asOf || "확인 필요"}</p> : <p className="report-api-state"><Inbox size={17} />{runs.length ? "실행을 선택해 주세요." : "실행 이력이 없습니다."}</p>}</section><section className="report-schedule-actual"><header><div><h3>예약 실행</h3><small>서울 시간 기준으로 자동 실행합니다.</small></div></header><div className="report-schedule-form"><label>주기<select value={cadence} onChange={(event) => setCadence(event.target.value)}><option value="daily">매일</option><option value="weekly">매주</option><option value="monthly">매월</option></select></label><label>다음 실행 시각<input type="datetime-local" value={scheduleAt} onChange={(event) => setScheduleAt(event.target.value)} /></label><button className="primary" onClick={() => void createSchedule()} disabled={Boolean(pending) || !scheduleAt}><Clock3 size={14} />예약 생성</button></div><div className="report-schedule-list">{selectedSchedules.map((schedule) => <article key={schedule.schedule_id}><div><b>{schedule.cadence === "daily" ? "매일" : schedule.cadence === "weekly" ? "매주" : "매월"} · {schedule.enabled ? "실행 중" : "중지됨"}</b><small>다음 실행 {formatSeoulTime(schedule.next_run_at)}</small></div><button onClick={() => void setScheduleEnabled(schedule.schedule_id, !schedule.enabled)}>{schedule.enabled ? "중지" : "재개"}</button></article>)}</div></section></details>}
      {assistantTrace && <details className="card editor-advanced"><summary>AI 처리 정보</summary><p>초안 생성을 완료했습니다. · {(assistantTrace.duration_ms / 1000).toFixed(1)}초</p></details>}
    </main>
  </div><DragOverlay dropAnimation={{ duration: 160, easing: "ease-out" }}>{activeTemplate && <div className="report-template-overlay">{ActiveTemplateIcon && <ActiveTemplateIcon size={16} />}<span><b>{activeTemplate.title}</b><small>캔버스에 놓아 추가</small></span></div>}</DragOverlay></DndContext>;
}

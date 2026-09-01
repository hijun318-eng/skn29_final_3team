/** 보고서 block의 통화·표현·크기·복제·삭제 제어기를 제공하는 모듈이다. */
import { memo, useId, useRef, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Copy, Lock, MoreHorizontal, Trash2, Unlock } from "lucide-react";
import { useDraggable } from "@dnd-kit/core";

import { ARTIFACT_VIEW_LABELS, artifactViewBlockSettings } from "../reportDraftV2";
import { REPORT_CURRENCY_OPTIONS } from "../reportCurrency";
import { blockSettings, REPORT_CHART_OPTIONS } from "./reportPresentation";
import { ReportFloatingPanel } from "./ReportFloatingPanel";

/** 문서 통화 배율을 계약 값으로만 선택하게 하는 memo 제어 컴포넌트다. */
export const ReportCurrencyControl = memo(function ReportCurrencyControl({
  value,
  onChange,
  disabled = false,
}) {
  return (
    <label className="report-currency-control">
      <span>금액 단위</span>
      <select
        aria-label="보고서 금액 단위"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {REPORT_CURRENCY_OPTIONS.map((option) => (
          <option value={option.value} key={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  );
});

/** 선택 블록의 크기·위치·표현·복제 명령을 메뉴와 속성 패널에서 같은 계약으로 제공한다. */
export const ReportBlockSettings = memo(function ReportBlockSettings({
  block,
  artifact,
  disabled = false,
  locked = false,
  onMove,
  onResize,
  onSetting,
  onDuplicate,
  onDelete,
  onToggleLock,
}) {
  const settings = blockSettings(block);
  const viewSizing = artifactViewBlockSettings(block);
  const artifactViewDescription = (viewSizing?.visibleViews || [])
    .map((view) => ARTIFACT_VIEW_LABELS[view])
    .filter(Boolean)
    .join(" · ");
  const widths = block.type === "text"
    ? [[4, "좁게"], [6, "절반"], [12, "전체"]]
    : [[6, "절반"], [12, "전체"]];
  const chartType = settings.chartType || artifact?.chart?.chart_type || "bar";

  return <div className="report-block-settings">
    <section>
      <span>블록 너비</span>
      <div className="report-block-widths">
        {widths.map(([width, label]) => <button type="button" className={(block.w ?? block.columns) === width ? "active" : ""} onClick={() => onResize(width)} disabled={disabled} key={width}>{label}</button>)}
      </div>
    </section>
    <section>
      <span>블록 높이</span>
      <div className="report-block-height">
        <button type="button" aria-label="높이 줄이기" onClick={() => onResize(block.w ?? block.columns, (block.h ?? 4) - 1)} disabled={disabled}>−</button>
        <output>{block.h ?? 4}단</output>
        <button type="button" aria-label="높이 늘리기" onClick={() => onResize(block.w ?? block.columns, (block.h ?? 4) + 1)} disabled={disabled}>+</button>
      </div>
    </section>
    <section>
      <span>위치 이동</span>
      <div className="report-block-moves">
        <button type="button" aria-label="왼쪽으로 이동" title="왼쪽으로 이동" onClick={() => onMove(-1, 0)} disabled={disabled}><ArrowLeft size={14} /></button>
        <button type="button" aria-label="위로 이동" title="위로 이동" disabled={disabled || (block.y ?? 0) === 0} onClick={() => onMove(0, -1)}><ArrowUp size={14} /></button>
        <button type="button" aria-label="아래로 이동" title="아래로 이동" onClick={() => onMove(0, 1)} disabled={disabled}><ArrowDown size={14} /></button>
        <button type="button" aria-label="오른쪽으로 이동" title="오른쪽으로 이동" onClick={() => onMove(1, 0)} disabled={disabled}><ArrowRight size={14} /></button>
      </div>
    </section>
    {block.type === "chart" && <section>
      <span>차트 표현</span>
      <label className="report-chart-type"><span className="sr-only">차트 유형</span><select aria-label={`${block.title} 차트 유형`} value={chartType} onChange={(event) => onSetting("chartType", event.target.value)} disabled={disabled}>{REPORT_CHART_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <small>화면·HTML·PDF가 함께 지원하는 표현만 선택할 수 있습니다.</small>
      <label><input type="checkbox" checked={settings.showLegend !== false} onChange={(event) => onSetting("showLegend", event.target.checked)} disabled={disabled} />범례 표시</label>
      <button type="button" className={viewSizing?.sizeMode === "auto" ? "active" : ""} onClick={() => onSetting("sizeMode", "auto")} disabled={disabled}>내용에 맞춤</button>
    </section>}
    {block.type === "table" && <section>
      <span>표 표현</span>
      <div className="report-block-widths"><button type="button" className={settings.density !== "compact" ? "active" : ""} onClick={() => onSetting("density", "comfortable")} disabled={disabled}>보통</button><button type="button" className={settings.density === "compact" ? "active" : ""} onClick={() => onSetting("density", "compact")} disabled={disabled}>간결</button></div>
      <label><input type="checkbox" checked={settings.showRowNumbers === true} onChange={(event) => onSetting("showRowNumbers", event.target.checked)} disabled={disabled} />행 번호 표시</label>
      <button type="button" className={viewSizing?.sizeMode === "auto" ? "active" : ""} onClick={() => onSetting("sizeMode", "auto")} disabled={disabled}>내용에 맞춤</button>
    </section>}
    {block.type === "artifact" && <section>
      <span>분석 결과</span>
      <small>{artifactViewDescription || "선택한 분석"} 요소를 원본 분석 근거와 함께 유지합니다.</small>
      <button type="button" className={settings.sizeMode === "auto" ? "active" : ""} onClick={() => onSetting("sizeMode", "auto")} disabled={disabled}>내용에 맞춤</button>
    </section>}
    <div className="report-block-menu-actions">
      <button type="button" onClick={onDuplicate} disabled={disabled}><Copy size={14} />복제</button>
      {onToggleLock && <button type="button" onClick={onToggleLock}>{locked ? <><Unlock size={14} />해제</> : <><Lock size={14} />잠금</>}</button>}
      <button type="button" className="danger" onClick={onDelete} disabled={disabled || locked}><Trash2 size={14} />삭제</button>
    </div>
  </div>;
});

/** 선택 블록의 허용 편집·크기·삭제 명령만 노출하고 disabled 권한을 강제한다. */
export const ReportBlockMenu = memo(function ReportBlockMenu({
  block,
  artifact,
  locked = false,
  onMove,
  onResize,
  onSetting,
  onDuplicate,
  onDelete,
  onToggleLock,
}) {
  const detailsRef = useRef(null);
  const panelRef = useRef(null);
  const menuId = useId();
  const [open, setOpen] = useState(false);
  const closeMenu = () => {
    if (detailsRef.current) detailsRef.current.open = false;
    setOpen(false);
  };
  const handleMenuKeyDown = (event) => {
    const details = detailsRef.current;
    if (!details?.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeMenu();
      details.querySelector("summary")?.focus();
      return;
    }
    if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) {
      return;
    }
    const controls = [
      ...panelRef.current?.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled)") || [],
    ];
    if (!controls.length) return;
    event.preventDefault();
    event.stopPropagation();
    const current = controls.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0
      : event.key === "End" ? controls.length - 1
        : event.key === "ArrowDown" || event.key === "ArrowRight"
          ? (current + 1 + controls.length) % controls.length
          : (current - 1 + controls.length) % controls.length;
    controls[next]?.focus();
  };

  return <>
    <details
      ref={detailsRef}
      className="report-block-menu"
      name="report-block-menu"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={handleMenuKeyDown}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="report-block-menu-trigger report-block-chrome-button" aria-label={`${block.title} 블록 메뉴`} aria-haspopup="true" aria-expanded={open} aria-controls={menuId} title="블록 설정 및 작업">
        <MoreHorizontal size={17} />
      </summary>
    </details>
    <ReportFloatingPanel
      anchorRef={detailsRef}
      panelRef={panelRef}
      open={open}
      id={menuId}
      className="report-block-menu-popover"
      aria-label={`${block.title} 블록 설정`}
      onKeyDown={handleMenuKeyDown}
      onRequestClose={closeMenu}
    >
      <ReportBlockSettings block={block} artifact={artifact} disabled={locked} locked={locked} onMove={onMove} onResize={onResize} onSetting={onSetting} onDuplicate={onDuplicate} onDelete={onDelete} onToggleLock={onToggleLock} />
    </ReportFloatingPanel>
  </>;
});

/** 일반 block template을 drag/keyboard 삽입 대상으로 제공하며 안정된 props를 재사용한다. */
export const ReportTemplateTile = memo(function ReportTemplateTile({
  template,
  disabled = false,
  disabledReason = "",
  onAdd,
}) {
  const reasonId = useId();
  const hasVisibleReason = disabled && Boolean(disabledReason);
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    isDragging,
  } = useDraggable({
    id: `template:${template.id}`,
    disabled,
    data: { kind: "template", templateId: template.id },
  });
  const Icon = template.icon;
  return (
    <div
      ref={setNodeRef}
      className={`report-template-tile ${isDragging ? "is-dragging" : ""} ${hasVisibleReason ? "has-disabled-reason" : ""}`.trim()}
      role={hasVisibleReason ? "group" : undefined}
      aria-disabled={disabled || undefined}
      aria-describedby={hasVisibleReason ? reasonId : undefined}
      aria-label={hasVisibleReason ? `${template.title}: ${disabledReason}` : undefined}
      tabIndex={hasVisibleReason ? 0 : undefined}
    >
      <button
        ref={setActivatorNodeRef}
        type="button"
        className="report-template-add"
        disabled={disabled}
        onClick={() => onAdd(template.id)}
        aria-describedby={hasVisibleReason ? reasonId : undefined}
        title={disabled ? undefined : `${template.title} 블록 바로 추가 또는 끌어서 배치`}
        {...listeners}
        {...attributes}
      >
        <Icon size={15} aria-hidden="true" />
        <span className="report-template-copy"><b>{template.title}</b><small>{template.description}</small></span>
      </button>
      {hasVisibleReason && <small id={reasonId} className="report-template-disabled-reason" role="note">{disabledReason}</small>}
    </div>
  );
});

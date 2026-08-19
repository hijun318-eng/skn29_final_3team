/** 보고서 block의 통화·표현·크기·복제·삭제 제어기를 제공하는 모듈이다. */
import { memo, useRef } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Copy, GripVertical, Lock, MoreHorizontal, Trash2, Unlock } from "lucide-react";
import { useDraggable } from "@dnd-kit/core";

import { artifactViewBlockSettings } from "../reportDraftV2";
import { REPORT_CURRENCY_OPTIONS } from "../reportCurrency";
import { blockSettings, REPORT_CHART_OPTIONS } from "./reportPresentation";

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
  const settings = blockSettings(block);
  const viewSizing = artifactViewBlockSettings(block);
  const widths = block.type === "text"
    ? [[4, "좁게"], [6, "절반"], [12, "전체"]]
    : [[6, "절반"], [12, "전체"]];
  const chartType = settings.chartType || artifact?.chart?.chart_type || "bar";

  const handleMenuKeyDown = (event) => {
    const details = detailsRef.current;
    if (!details?.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      details.open = false;
      details.querySelector("summary")?.focus();
      return;
    }
    if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) {
      return;
    }
    const controls = [
      ...details.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled)"),
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

  return (
    <details
      ref={detailsRef}
      className="report-block-menu"
      name="report-block-menu"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={handleMenuKeyDown}
    >
      <summary aria-label={`${block.title} 블록 메뉴`} aria-haspopup="true" title="블록 메뉴">
        <MoreHorizontal size={17} />
      </summary>
      <div className="report-block-menu-popover" aria-label={`${block.title} 블록 설정`}>
        <section>
          <span>블록 너비</span>
          <div className="report-block-widths">
            {widths.map(([width, label]) => (
              <button
                type="button"
                className={(block.w ?? block.columns) === width ? "active" : ""}
                disabled={locked}
                onClick={() => onResize(width)}
                key={width}
              >
                {label}
              </button>
            ))}
          </div>
        </section>
        <section>
          <span>블록 높이</span>
          <div className="report-block-height">
            <button type="button" aria-label="높이 줄이기" disabled={locked} onClick={() => onResize(block.w ?? block.columns, (block.h ?? 4) - 1)}>−</button>
            <output>{block.h ?? 4}단</output>
            <button type="button" aria-label="높이 늘리기" disabled={locked} onClick={() => onResize(block.w ?? block.columns, (block.h ?? 4) + 1)}>+</button>
          </div>
        </section>
        <section>
          <span>위치 이동</span>
          <div className="report-block-moves">
            <button type="button" aria-label="왼쪽으로 이동" title="왼쪽으로 이동" disabled={locked} onClick={() => onMove(-1, 0)}><ArrowLeft size={14} /></button>
            <button type="button" aria-label="위로 이동" title="위로 이동" disabled={locked || (block.y ?? 0) === 0} onClick={() => onMove(0, -1)}><ArrowUp size={14} /></button>
            <button type="button" aria-label="아래로 이동" title="아래로 이동" disabled={locked} onClick={() => onMove(0, 1)}><ArrowDown size={14} /></button>
            <button type="button" aria-label="오른쪽으로 이동" title="오른쪽으로 이동" disabled={locked} onClick={() => onMove(1, 0)}><ArrowRight size={14} /></button>
          </div>
        </section>
        {block.type === "chart" && (
          <section>
            <span>차트 표현</span>
            <label className="report-chart-type">
              <span className="sr-only">차트 유형</span>
              <select
                aria-label={`${block.title} 차트 유형`}
                value={chartType}
                onChange={(event) => onSetting("chartType", event.target.value)}
              >
                {REPORT_CHART_OPTIONS.map(([value, label]) => (
                  <option value={value} key={value}>{label}</option>
                ))}
              </select>
            </label>
            <small>데이터 구조에 맞지 않는 표현은 안전 안내로 대체됩니다.</small>
            <label>
              <input
                type="checkbox"
                checked={settings.showLegend !== false}
                onChange={(event) => onSetting("showLegend", event.target.checked)}
              />
              범례 표시
            </label>
            <button
              type="button"
              className={viewSizing?.sizeMode === "auto" ? "active" : ""}
              onClick={() => onSetting("sizeMode", "auto")}
            >
              내용에 맞춤
            </button>
          </section>
        )}
        {block.type === "table" && (
          <section>
            <span>표 표현</span>
            <div className="report-block-widths">
              <button type="button" className={settings.density !== "compact" ? "active" : ""} onClick={() => onSetting("density", "comfortable")}>보통</button>
              <button type="button" className={settings.density === "compact" ? "active" : ""} onClick={() => onSetting("density", "compact")}>간결</button>
            </div>
            <label>
              <input
                type="checkbox"
                checked={settings.showRowNumbers === true}
                onChange={(event) => onSetting("showRowNumbers", event.target.checked)}
              />
              행 번호 표시
            </label>
            <button
              type="button"
              className={viewSizing?.sizeMode === "auto" ? "active" : ""}
              onClick={() => onSetting("sizeMode", "auto")}
            >
              내용에 맞춤
            </button>
          </section>
        )}
        {block.type === "artifact" && (
          <section>
            <span>Artifact 전체</span>
            <small>요약·KPI·차트·표가 함께 이동하고 미리보기에 같은 순서로 표시됩니다.</small>
            <button
              type="button"
              className={settings.sizeMode === "auto" ? "active" : ""}
              onClick={() => onSetting("sizeMode", "auto")}
            >
              내용에 맞춤
            </button>
          </section>
        )}
        <div className="report-block-menu-actions">
          <button type="button" onClick={onDuplicate}><Copy size={14} />복제</button>
          <button type="button" onClick={onToggleLock}>
            {locked ? <><Unlock size={14} />잠금 해제</> : <><Lock size={14} />잠금</>}
          </button>
          <button type="button" className="danger" disabled={locked} title={locked ? "잠긴 블록은 삭제할 수 없습니다" : undefined} onClick={onDelete}><Trash2 size={14} />삭제</button>
        </div>
      </div>
    </details>
  );
});

/** 일반 block template을 drag/keyboard 삽입 대상으로 제공하며 안정된 props를 재사용한다. */
export const ReportTemplateTile = memo(function ReportTemplateTile({
  template,
  disabled = false,
  onAdd,
}) {
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
      className={`report-template-tile ${isDragging ? "is-dragging" : ""}`}
      aria-disabled={disabled || undefined}
    >
      <button
        type="button"
        className="report-template-add"
        disabled={disabled}
        onClick={() => onAdd(template.id)}
        title={`${template.title} 블록 바로 추가`}
      >
        <Icon size={15} />
        <span>{template.title}<small>{template.description}</small></span>
      </button>
      <button
        ref={setActivatorNodeRef}
        type="button"
        className="report-template-drag"
        disabled={disabled}
        aria-label={`${template.title} 블록 끌어서 추가`}
        title="Space 또는 Enter로 들어 캔버스 위치를 선택하세요"
        {...listeners}
        {...attributes}
      >
        <GripVertical className="report-template-grip" size={14} aria-hidden="true" />
      </button>
    </div>
  );
});

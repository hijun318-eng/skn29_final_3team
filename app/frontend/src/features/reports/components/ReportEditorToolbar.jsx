/** 보고서 editor의 저장·history·방향·미리보기 명령을 제공하는 toolbar 모듈이다. */
import { memo } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Clock3,
  Eye,
  LoaderCircle,
  Maximize2,
  Minimize2,
  PanelLeftClose,
  PanelLeftOpen,
  Redo2,
  Save,
  Send,
  Undo2,
  ZoomIn,
} from "lucide-react";

import { reportStatusLabel } from "../reportPageLabels";

/** 저장·미리보기·undo/redo·방향 명령을 상태에 맞게 잠그는 memo toolbar다. */
export const ReportEditorToolbar = memo(function ReportEditorToolbar({
  builderV2,
  currencyControl,
  history,
  isAdmin,
  isDraft,
  isDirty,
  onChangeOrientation,
  onLeave,
  onPreview,
  onRedo,
  onRun,
  onSave,
  onToggleTools,
  onUndo,
  orientation,
  pending,
  saveStatus,
  selectedDefinition,
  toolPanelOpen,
  toolToggleRef,
  zoom,
  onZoom,
}) {
  return <header className="editor-topbar notion-editor-topbar">
    <div className={builderV2 ? "report-builder-heading" : ""}><button onClick={onLeave} disabled={Boolean(pending)}><ArrowLeft size={14} aria-hidden="true" />보고서</button>{builderV2 ? <div><small>ANSWERVICE / REPORT BUILDER</small><h1>{selectedDefinition?.title || "보고서 초안"}</h1><span>A4 문서 · 12열 그리드 · {reportStatusLabel(selectedDefinition?.status)} v{selectedDefinition?.version}</span></div> : <span className="notion-status-chip">{reportStatusLabel(selectedDefinition?.status)} · v{selectedDefinition?.version}</span>}</div>
    <div>
      <div className="editor-view-actions" aria-label="편집 화면 설정"><button ref={toolToggleRef} type="button" aria-pressed={toolPanelOpen} aria-label={toolPanelOpen ? "블록 도구 숨기기" : "블록 도구 열기"} title={toolPanelOpen ? "블록 도구 숨기기" : "블록 도구 열기"} onClick={onToggleTools} disabled={Boolean(pending)}>{toolPanelOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}<span>도구</span></button>{builderV2 && <label className="report-builder-zoom"><ZoomIn size={14} /><select aria-label="보고서 확대 축소" value={zoom} onChange={(event) => onZoom(Number(event.target.value))}><option value="0.7">70%</option><option value="0.85">85%</option><option value="1">100%</option></select></label>}{currencyControl}<div className="report-orientation-switch" role="group" aria-label="A4 용지 방향"><button type="button" aria-pressed={orientation === "landscape"} title="A4 가로" onClick={() => onChangeOrientation("landscape")} disabled={Boolean(pending)}><Maximize2 size={15} /><span>가로</span></button><button type="button" aria-pressed={orientation === "portrait"} title="A4 세로" onClick={() => onChangeOrientation("portrait")} disabled={Boolean(pending)}><Minimize2 size={15} /><span>세로</span></button></div></div>
      <div className="editor-history-actions" aria-label="편집 기록"><button type="button" aria-label="실행 취소" title="실행 취소 (Ctrl+Z)" onClick={onUndo} disabled={Boolean(pending) || !history.past.length}><Undo2 size={14} /></button><button type="button" aria-label="다시 실행" title="다시 실행 (Ctrl+Y)" onClick={onRedo} disabled={Boolean(pending) || !history.future.length}><Redo2 size={14} /></button></div>
      <span className={`editor-save-state ${saveStatus}`} role="status">{saveStatus === "saving" ? <LoaderCircle className="spin" size={13} aria-hidden="true" /> : saveStatus === "error" ? <AlertTriangle size={13} aria-hidden="true" /> : saveStatus === "unsaved" ? <Clock3 size={13} aria-hidden="true" /> : <Check size={13} aria-hidden="true" />}{saveStatus === "saving" ? "저장 중" : saveStatus === "error" ? "저장 실패" : saveStatus === "unsaved" ? "저장되지 않은 변경" : "저장됨"}</span>
      <button title={isDirty ? "변경사항을 먼저 저장해 주세요" : "저장된 HTML 초안 확인"} onClick={onPreview} disabled={Boolean(pending) || isDirty}><Eye size={14} aria-hidden="true" />{builderV2 ? "Preview" : "HTML 초안 확인"}</button>
      {isDraft && <button className="primary" aria-label="보고서 저장" onClick={onSave} disabled={Boolean(pending) || !isDirty}><Save size={14} aria-hidden="true" />저장</button>}
      {isAdmin && selectedDefinition?.status === "approved" && <button className="primary" onClick={onRun} disabled={Boolean(pending)}><Send size={14} aria-hidden="true" />실행</button>}
    </div>
  </header>;
});

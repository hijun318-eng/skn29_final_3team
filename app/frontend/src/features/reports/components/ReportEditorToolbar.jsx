/** 보고서 editor의 저장·history·방향·미리보기 명령을 제공하는 toolbar 모듈이다. */
import { memo } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Clock3,
  Eye,
  LayoutGrid,
  LoaderCircle,
  Maximize2,
  Minimize2,
  PanelLeftClose,
  PanelLeftOpen,
  Redo2,
  Save,
  Send,
  Undo2,
} from "lucide-react";

import { REPORT_EDITOR_SCALE_OPTIONS } from "../reportEditorViewport";
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
  onChangeViewScale,
  onCompactLayout,
  onLeave,
  onPreview,
  onRedo,
  onRun,
  onSave,
  onToggleTools,
  onUndo,
  orientation,
  pending,
  reportTitle,
  saveStatus,
  selectedDefinition,
  toolPanelOpen,
  toolToggleRef,
  viewScale,
}) {
  return <header className="editor-topbar notion-editor-topbar">
    <div className="editor-navigation-actions">{builderV2 && <div className="report-builder-heading"><small>REPORT BUILDER</small><h1>{reportTitle || "보고서 초안"}</h1></div>}<button onClick={onLeave} disabled={Boolean(pending)}><ArrowLeft size={14} aria-hidden="true" />보고서</button>{!builderV2 && <span className="notion-status-chip">{reportStatusLabel(selectedDefinition?.status)} · v{selectedDefinition?.version}</span>}</div>
    <div className="editor-command-actions">
      <div className="editor-view-actions" aria-label="편집 화면 설정"><button ref={toolToggleRef} type="button" aria-pressed={toolPanelOpen} aria-label={toolPanelOpen ? "블록 도구 숨기기" : "블록 도구 열기"} title={toolPanelOpen ? "블록 도구 숨기기" : "블록 도구 열기"} onClick={onToggleTools} disabled={Boolean(pending)}>{toolPanelOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}<span>도구</span></button><label className="report-view-scale"><span className="sr-only">보고서 확대 축소</span><select aria-label="보고서 확대 축소" value={viewScale} onChange={(event) => onChangeViewScale(event.target.value)}>{REPORT_EDITOR_SCALE_OPTIONS.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label><button type="button" aria-label="블록 자동 정돈" title="기존 12열 계약으로 블록 자동 정돈" onClick={onCompactLayout} disabled={Boolean(pending)}><LayoutGrid size={15} /><span>정돈</span></button>{currencyControl}<div className="report-orientation-switch" role="group" aria-label="A4 용지 방향"><button type="button" aria-pressed={orientation === "landscape"} title="A4 가로" onClick={() => onChangeOrientation("landscape")} disabled={Boolean(pending)}><Maximize2 size={15} /><span>가로</span></button><button type="button" aria-pressed={orientation === "portrait"} title="A4 세로" onClick={() => onChangeOrientation("portrait")} disabled={Boolean(pending)}><Minimize2 size={15} /><span>세로</span></button></div></div>
      <div className="editor-history-actions" aria-label="편집 기록"><button type="button" aria-label="실행 취소" title="실행 취소 (Ctrl+Z)" onClick={onUndo} disabled={Boolean(pending) || !history.past.length}><Undo2 size={14} /></button><button type="button" aria-label="다시 실행" title="다시 실행 (Ctrl+Y)" onClick={onRedo} disabled={Boolean(pending) || !history.future.length}><Redo2 size={14} /></button></div>
      <span className={`editor-save-state ${saveStatus}`} role="status">{saveStatus === "saving" ? <LoaderCircle className="spin" size={13} aria-hidden="true" /> : saveStatus === "error" ? <AlertTriangle size={13} aria-hidden="true" /> : saveStatus === "unsaved" ? <Clock3 size={13} aria-hidden="true" /> : <Check size={13} aria-hidden="true" />}{saveStatus === "saving" ? "저장 중" : saveStatus === "error" ? "저장 실패" : saveStatus === "unsaved" ? "저장되지 않은 변경" : "저장됨"}</span>
      <button title={isDirty ? "변경사항을 먼저 저장해 주세요" : "저장된 HTML 초안 확인"} onClick={onPreview} disabled={Boolean(pending) || isDirty}><Eye size={14} aria-hidden="true" />{builderV2 ? "Preview" : "HTML 초안 확인"}</button>
      {isDraft && <button className="primary" aria-label="보고서 저장" onClick={onSave} disabled={Boolean(pending) || !isDirty}><Save size={14} aria-hidden="true" />저장</button>}
      {isAdmin && selectedDefinition?.status === "approved" && <button className="primary" onClick={onRun} disabled={Boolean(pending)}><Send size={14} aria-hidden="true" />실행</button>}
    </div>
  </header>;
});

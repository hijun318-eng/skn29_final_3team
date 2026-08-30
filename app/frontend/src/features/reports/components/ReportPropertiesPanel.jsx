/** 선택 블록 속성·일괄 작업·검색·세션 스냅샷을 한 패널에 제공한다. */
import { memo, useState } from "react";
import {
  Camera, Clipboard, Copy, Lock, Search, Trash2, Unlock, X,
} from "lucide-react";

import { REPORT_CHART_OPTIONS, blockSettings } from "./reportPresentation";
import { reportEvidenceLabel } from "../../../contracts/report";

function sourceLabel(artifact) {
  const names = artifact?.evidence?.sources?.map((source) => source.name).filter(Boolean) ?? [];
  return names.length ? names.join(" · ") : "연결된 출처 정보 없음";
}

/** payload에 포함되지 않는 편집 명령과 저장 가능한 block 속성을 명확히 분리한다. */
export const ReportPropertiesPanel = memo(function ReportPropertiesPanel({
  artifact,
  canEdit,
  editorTools,
  onSetting,
  onUpdate,
  orientation,
  pageCount,
}) {
  const [snapshotName, setSnapshotName] = useState("");
  const block = editorTools.primaryBlock;
  const blockLocked = block ? editorTools.lockedBlockIds.has(block.id) : false;
  const settings = blockSettings(block ?? {});
  const selectedCount = editorTools.selectedBlockIds.size;
  const lockedSelectedCount = [...editorTools.selectedBlockIds]
    .filter((id) => editorTools.lockedBlockIds.has(id)).length;

  return <aside className="report-properties-panel" aria-label="보고서 속성">
    <header><div><p>보고서 설정</p><h2>속성</h2></div><span>{selectedCount ? `${selectedCount}개 선택` : "선택 없음"}</span></header>

    {selectedCount > 1 && <section className="report-batch-actions">
      <h3>선택 블록 정렬</h3>
      <div className="report-batch-sizing">
        <button type="button" onClick={() => editorTools.unifySelectedSize("width")} disabled={!canEdit || lockedSelectedCount > 0}>너비 통일</button>
        <button type="button" onClick={() => editorTools.unifySelectedSize("height")} disabled={!canEdit || lockedSelectedCount > 0}>높이 통일</button>
      </div>
      <small className="report-properties-help">기준 블록의 크기로 맞추며 한 번의 Undo 단계로 기록합니다.</small>
      <div className="report-batch-locks">
        <button type="button" onClick={() => editorTools.setSelectedLocks(true)} disabled={!canEdit}><Lock size={14} />잠금</button>
        <button type="button" onClick={() => editorTools.setSelectedLocks(false)} disabled={!canEdit || !lockedSelectedCount}><Unlock size={14} />해제</button>
        <button type="button" className="danger" onClick={editorTools.deleteSelected} disabled={!canEdit || lockedSelectedCount > 0}><Trash2 size={14} />삭제</button>
      </div>
    </section>}

    <section>
      <h3><Search size={14} />블록 검색</h3>
      <label className="report-properties-search"><Search size={14} /><input value={editorTools.searchQuery} onChange={(event) => editorTools.setSearchQuery(event.target.value)} placeholder="제목 또는 텍스트 검색" />{editorTools.searchQuery && <button type="button" aria-label="검색 지우기" onClick={() => editorTools.setSearchQuery("")}><X size={13} /></button>}</label>
      {editorTools.searchQuery && <div className="report-properties-results">{editorTools.searchResults.length ? editorTools.searchResults.map((result) => <button type="button" onClick={() => editorTools.focusSearchResult(result.id)} key={result.id}><b>{result.title || "제목 없음"}</b><small>{result.type === "text" ? "텍스트" : result.type}</small></button>) : <p>일치하는 블록이 없습니다.</p>}</div>}
    </section>

    {block ? <section className="report-block-properties" key={block.id}>
      <h3>선택 블록</h3>
      <label><span>제목</span><input defaultValue={block.title} disabled={!canEdit || blockLocked} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} onBlur={(event) => { const title = event.target.value.trim(); if (title && title !== block.title) onUpdate(block.id, { title }); }} /></label>
      <dl><div><dt>유형</dt><dd>{block.type}</dd></div><div><dt>위치</dt><dd>{(block.x ?? 0) + 1}열 · {(block.y ?? 0) + 1}행</dd></div><div><dt>크기</dt><dd>{block.w ?? block.columns}/12 · {block.h}단</dd></div><div><dt>상태</dt><dd>{blockLocked ? "잠김" : "편집 가능"}</dd></div></dl>
      <div className="report-property-lock"><button type="button" onClick={() => editorTools.toggleBlockLock(block.id)} disabled={!canEdit}>{blockLocked ? <><Unlock size={14} />잠금 해제</> : <><Lock size={14} />블록 잠금</>}</button></div>
      <span className="report-property-label">8단계 크기</span>
      <div className="report-size-presets">{editorTools.sizePresets.map((preset) => <button type="button" title={`${preset.width}/12 · ${preset.height}단`} aria-label={`${preset.index}단계 ${preset.label}`} className={(block.w ?? block.columns) === preset.width && block.h === preset.height ? "active" : ""} onClick={() => editorTools.resizePrimary(preset)} disabled={!canEdit || editorTools.lockedBlockIds.has(block.id)} key={preset.index}><b>{preset.index}</b><small>{preset.label}</small></button>)}</div>
      {block.type === "chart" && <>
        <label><span>차트 유형</span><select value={settings.chartType || artifact?.chart?.chart_type || "bar"} disabled={!canEdit || blockLocked} onChange={(event) => onSetting(block.id, "chartType", event.target.value)}>{REPORT_CHART_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label className="report-property-check"><input type="checkbox" checked={settings.showLegend !== false} disabled={!canEdit || blockLocked} onChange={(event) => onSetting(block.id, "showLegend", event.target.checked)} /><span>범례 표시</span></label>
      </>}
      {block.type !== "text" && <div className="report-property-evidence"><span>데이터 출처</span><b>{sourceLabel(artifact)}</b>{!block.artifactId && <small>연결된 분석 결과 없음</small>}</div>}
      {block.type === "text" && block.evidenceRefs?.length ? <div className="report-property-evidence"><span>AI 검증 근거</span><b>{block.evidenceRefs.map(reportEvidenceLabel).join(" · ")}</b><small>본문을 직접 수정하면 이 근거 표시는 해제됩니다.</small></div> : null}
      <div className="report-property-actions"><button type="button" onClick={() => { editorTools.copySelected(); editorTools.pasteBlocks(); }} disabled={!canEdit}><Copy size={14} />복제</button><button type="button" className="danger" onClick={() => editorTools.deleteBlock(block.id)} disabled={!canEdit || blockLocked}><Trash2 size={14} />삭제</button></div>
    </section> : <section className="report-properties-empty"><dl><div><dt>용지 방향</dt><dd>{orientation === "landscape" ? "A4 가로" : "A4 세로"}</dd></div><div><dt>페이지</dt><dd>{pageCount}페이지</dd></div></dl><p>보고서 블록을 선택하면 크기와 표현 속성을 편집할 수 있습니다.</p></section>}

    <section>
      <h3><Camera size={14} />세션 스냅샷</h3>
      <div className="report-snapshot-create"><input value={snapshotName} maxLength={40} onChange={(event) => setSnapshotName(event.target.value)} placeholder="스냅샷 이름" /><button type="button" onClick={() => { editorTools.createSnapshot(snapshotName); setSnapshotName(""); }} disabled={!editorTools.primaryBlock}><Camera size={14} />저장</button></div>
      <div className="report-snapshot-list">{editorTools.snapshots.length ? editorTools.snapshots.map((snapshot) => <div key={snapshot.id}><button type="button" onClick={() => editorTools.restoreSnapshot(snapshot.id)} disabled={!canEdit}><b>{snapshot.name}</b><small>{new Date(snapshot.createdAt).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}</small></button><button type="button" aria-label={`${snapshot.name} 삭제`} onClick={() => editorTools.removeSnapshot(snapshot.id)}><X size={13} /></button></div>) : <p>현재 세션에 저장된 버전이 없습니다.</p>}</div>
    </section>

    <section>
      <h3><Clipboard size={14} />클립보드</h3>
      <div className="report-clipboard-actions"><button type="button" onClick={editorTools.copySelected} disabled={!selectedCount}><Copy size={14} />복사</button><button type="button" onClick={editorTools.pasteBlocks} disabled={!canEdit}><Clipboard size={14} />붙여넣기</button></div>
      <small className="report-properties-help">Shift+클릭하거나 A4의 빈 영역을 드래그해 여러 블록을 선택할 수 있습니다.</small>
    </section>
  </aside>;
});

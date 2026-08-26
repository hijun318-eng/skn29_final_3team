/** 감사 trail 검색·cursor 목록·선택 상세의 서버 상태와 응답 경합을 관리하는 화면 모듈이다. */

import { ChevronLeft, ChevronRight, FileClock, RotateCcw, Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AuditOutcomeBadge, AuditTrailDetail, formatAuditTimestamp } from "./AuditTrailDetail.tsx";
import type {
  AuditTrailDetailData,
  AuditTrailFilters,
  AuditTrailPage,
} from "./auditTrailTypes.ts";
import "./audit-trail.css";

const EMPTY_FILTERS: AuditTrailFilters = { query: "", outcome: "", action: "", from: "", to: "" };
const EMPTY_PAGE: AuditTrailPage = { items: [], next_cursor: null };

/** 패널이 의존하는 읽기 전용 목록·상세 호출만 제한해 테스트 주입과 실제 client를 같은 경계로 받는다. */
export interface AuditTrailClient {
  listAuditTrails(filters: AuditTrailFilters, cursor?: string): Promise<AuditTrailPage>;
  getAuditTrail(trailId: string): Promise<AuditTrailDetailData>;
}

function auditErrorMessage() {
  return "감사 추적 API를 사용할 수 없습니다. 서버 연결 상태를 확인한 뒤 다시 시도해 주세요.";
}

function shortIdentifier(value: string) {
  return value.length <= 18 ? value : `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function durationLabel(startedAt: string, endedAt: string | null) {
  if (!endedAt) return "종료 시각 없음";
  const duration = new Date(endedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(duration) || duration < 0) return "소요 시간 확인 불가";
  if (duration < 1_000) return `${duration}ms`;
  if (duration < 60_000) return `${(duration / 1_000).toFixed(duration < 10_000 ? 1 : 0)}초`;
  return `${Math.floor(duration / 60_000)}분 ${Math.floor((duration % 60_000) / 1_000)}초`;
}

/** 서버 필터와 cursor를 적용해 최신 trail 목록과 선택한 상세를 독립적으로 조회한다. */
export function AuditTrailPanel({
  client,
  onApiStateChange,
}: {
  client: AuditTrailClient;
  onApiStateChange?: (state: "checking" | "connected" | "error") => void;
}) {
  const [draftFilters, setDraftFilters] = useState<AuditTrailFilters>(EMPTY_FILTERS);
  const [filters, setFilters] = useState<AuditTrailFilters>(EMPTY_FILTERS);
  const [cursor, setCursor] = useState("");
  const [cursorHistory, setCursorHistory] = useState<string[]>([]);
  const [page, setPage] = useState<AuditTrailPage>(EMPTY_PAGE);
  const [selectedTrailId, setSelectedTrailId] = useState("");
  const [detail, setDetail] = useState<AuditTrailDetailData | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [listError, setListError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [listRetry, setListRetry] = useState(0);
  const [detailRetry, setDetailRetry] = useState(0);
  const listGeneration = useRef(0);
  const detailGeneration = useRef(0);
  const detailRef = useRef<HTMLDivElement>(null);
  const selectedTrailIdRef = useRef(selectedTrailId);
  selectedTrailIdRef.current = selectedTrailId;

  const loadTrails = useCallback(async () => {
    const generation = ++listGeneration.current;
    setListLoading(true);
    setListError("");
    onApiStateChange?.("checking");
    try {
      const nextPage = await client.listAuditTrails(filters, cursor);
      if (listGeneration.current !== generation) return;
      setPage(nextPage);
      const selectedId = selectedTrailIdRef.current;
      if (selectedId && !nextPage.items.some((item) => item.trail_id === selectedId)) {
        detailGeneration.current += 1;
        setSelectedTrailId("");
        setDetail(null);
      }
      onApiStateChange?.("connected");
    } catch {
      if (listGeneration.current !== generation) return;
      setPage(EMPTY_PAGE);
      setSelectedTrailId("");
      setDetail(null);
      setListError(auditErrorMessage());
      onApiStateChange?.("error");
    } finally {
      if (listGeneration.current === generation) setListLoading(false);
    }
  }, [client, cursor, filters, listRetry, onApiStateChange]);

  useEffect(() => {
    void loadTrails();
    return () => { listGeneration.current += 1; };
  }, [loadTrails]);

  useEffect(() => {
    if (!selectedTrailId) {
      detailGeneration.current += 1;
      setDetail(null);
      setDetailError("");
      setDetailLoading(false);
      return undefined;
    }
    const generation = ++detailGeneration.current;
    setDetail(null);
    setDetailError("");
    setDetailLoading(true);
    onApiStateChange?.("checking");
    client.getAuditTrail(selectedTrailId)
      .then((nextDetail) => {
        if (detailGeneration.current === generation && nextDetail.trail_id === selectedTrailId) {
          setDetail(nextDetail);
          onApiStateChange?.("connected");
        }
      })
      .catch(() => {
        if (detailGeneration.current === generation) {
          setDetailError(auditErrorMessage());
          onApiStateChange?.("error");
        }
      })
      .finally(() => {
        if (detailGeneration.current === generation) setDetailLoading(false);
      });
    return () => { detailGeneration.current += 1; };
  }, [client, detailRetry, onApiStateChange, selectedTrailId]);

  useEffect(() => {
    if (!selectedTrailId || typeof window === "undefined" || !window.matchMedia("(max-width: 760px)").matches) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" }));
  }, [selectedTrailId]);

  const applyFilters = (event: React.FormEvent) => {
    event.preventDefault();
    setCursor("");
    setCursorHistory([]);
    setSelectedTrailId("");
    setDetail(null);
    setFilters({
      query: draftFilters.query.trim(),
      outcome: draftFilters.outcome,
      action: draftFilters.action.trim(),
      from: draftFilters.from,
      to: draftFilters.to,
    });
  };

  const resetFilters = () => {
    setDraftFilters(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
    setCursor("");
    setCursorHistory([]);
    setSelectedTrailId("");
    setDetail(null);
  };

  const openPreviousPage = () => {
    const previousCursor = cursorHistory.at(-1);
    if (previousCursor === undefined) return;
    setCursorHistory((current) => current.slice(0, -1));
    setCursor(previousCursor);
  };

  const openNextPage = () => {
    if (!page.next_cursor) return;
    setCursorHistory((current) => [...current, cursor]);
    setCursor(page.next_cursor ?? "");
  };

  return <section className="admin-panel audit-trail-panel" id="admin-panel-audit" role="tabpanel" aria-labelledby="admin-tab-audit">
    <header className="admin-panel__header audit-trail-header"><div><small>TRACEABLE OPERATIONS</small><h2>감사 추적</h2><p>요청부터 검증, 실행 결과까지 연결된 작업 이력을 확인합니다.</p></div></header>

    <form className="audit-filter-bar card" onSubmit={applyFilters}>
      <label className="audit-filter-search"><span>통합 검색</span><div><Search size={15} /><input value={draftFilters.query} onChange={(event) => setDraftFilters((current) => ({ ...current, query: event.target.value }))} placeholder="수행자, 대상, request 또는 trace ID" /></div></label>
      <label><span>시작일</span><input type="date" value={draftFilters.from} onChange={(event) => setDraftFilters((current) => ({ ...current, from: event.target.value }))} /></label>
      <label><span>종료일</span><input type="date" value={draftFilters.to} onChange={(event) => setDraftFilters((current) => ({ ...current, to: event.target.value }))} /></label>
      <label><span>결과</span><select value={draftFilters.outcome} onChange={(event) => setDraftFilters((current) => ({ ...current, outcome: event.target.value as AuditTrailFilters["outcome"] }))}><option value="">전체 결과</option><option value="SUCCEEDED">성공</option><option value="FAILED">실패</option><option value="DENIED">정책 거부</option><option value="CANCELLED">취소</option><option value="IN_PROGRESS">진행 중</option><option value="CLARIFICATION_REQUIRED">확인 필요</option><option value="UNKNOWN">확인 불가</option></select></label>
      <label><span>이벤트 유형</span><input value={draftFilters.action} onChange={(event) => setDraftFilters((current) => ({ ...current, action: event.target.value }))} placeholder="Action code" /></label>
      <div className="audit-filter-actions"><button type="button" onClick={resetFilters}><RotateCcw size={14} />초기화</button><button className="primary" type="submit"><Search size={14} />검색</button></div>
    </form>

    <div className="audit-workbench">
      <section className="audit-trail-list card" aria-labelledby="audit-trail-list-title">
        <header><div><small>AUDIT TRAILS</small><h3 id="audit-trail-list-title">작업 이력</h3></div><span>{page.items.length}건 표시</span></header>
        {listLoading && <div className="audit-list-state" role="status"><i className="audit-spinner" /><b>작업 이력을 불러오고 있습니다.</b></div>}
        {!listLoading && listError && <div className="audit-list-state audit-list-state--error" role="alert"><FileClock size={23} /><b>{listError}</b><button type="button" onClick={() => setListRetry((current) => current + 1)}>다시 시도</button></div>}
        {!listLoading && !listError && page.items.length === 0 && <div className="audit-list-state"><FileClock size={23} /><b>조건에 맞는 작업 이력이 없습니다.</b><span>검색 조건이나 기간을 변경해 주세요.</span></div>}
        {!listLoading && !listError && page.items.length > 0 && <div className="audit-trail-items" role="listbox" aria-label="감사 추적 목록">
          {page.items.map((item) => <button
            type="button"
            role="option"
            aria-selected={selectedTrailId === item.trail_id}
            className={selectedTrailId === item.trail_id ? "is-selected" : ""}
            key={item.trail_id}
            onClick={() => setSelectedTrailId(item.trail_id)}
          >
            <span className="audit-trail-item__time">{formatAuditTimestamp(item.started_at)}</span>
            <span className="audit-trail-item__title"><b>{item.headline}</b><AuditOutcomeBadge outcome={item.outcome} /></span>
            <span className="audit-trail-item__meta">{item.actor.display_name || "시스템"} · {item.actor.role} · 이벤트 {item.event_count}개</span>
            <span className="audit-trail-item__target">{item.primary_object.type}<code title={item.primary_object.id}>{shortIdentifier(item.primary_object.id)}</code></span>
            <span className="audit-trail-item__correlation"><small>{item.correlation.type}</small><code title={item.correlation.id}>{shortIdentifier(item.correlation.id)}</code><em>{durationLabel(item.started_at, item.ended_at)}</em></span>
          </button>)}
        </div>}
        <footer className="audit-cursor-pagination"><span>{cursorHistory.length + 1} 페이지</span><div><button type="button" disabled={listLoading || cursorHistory.length === 0} onClick={openPreviousPage}><ChevronLeft size={14} />이전</button><button type="button" disabled={listLoading || !page.next_cursor} onClick={openNextPage}>다음<ChevronRight size={14} /></button></div></footer>
      </section>

      <section className="audit-trail-detail card" aria-label="선택한 감사 추적 상세" ref={detailRef}>
        <AuditTrailDetail detail={detail} loading={detailLoading} error={detailError} onRetry={() => setDetailRetry((current) => current + 1)} />
      </section>
    </div>
  </section>;
}

/**
 * SP-03 실시간 모니터링 화면
 * @see SensePlace_목업_v1.2.html — #sp03
 */

import { useState, useCallback, useMemo } from 'react';
import { Layout } from '../components/Layout.tsx';
import { SevBadge } from '../components/Badge.tsx';
import { EmptyState } from '../components/EmptyState.tsx';
import { INC, KPI } from '../data/mockData.ts';
import { ZONES } from '../data/ontology.ts';
import type { Incident } from '../data/mockData.ts';
import type { Severity, VOCStatus } from '../lib/api.ts';

/* ------------------------------------------------------------------ */
/*  상수                                                               */
/* ------------------------------------------------------------------ */

const SEV_GLYPH: Record<string, string> = { danger: '●', warn: '◐', ok: '○' };

const STATUS_LABEL: Record<string, string> = {
  recv: '접수', check: '확인', prog: '진행중', done: '완료',
};

/* ------------------------------------------------------------------ */
/*  SVG 지도 마커                                                       */
/* ------------------------------------------------------------------ */

function MapSvg({ items }: { items: Incident[] }) {
  const zonePoly = (pts: string, fill: string) => (
    <polygon
      points={pts}
      fill={fill}
      fillOpacity={0.10}
      stroke={fill}
      strokeOpacity={0.35}
      strokeWidth={1.5}
    />
  );

  return (
    <svg viewBox="0 0 800 520" style={{ width: '100%', height: '100%', display: 'block' }}>
      <rect width="800" height="520" fill="#eef4f2" />
      <path d="M0,300 Q200,270 400,300 T800,290" stroke="#bfdbfe" strokeWidth={26} fill="none" opacity={0.7} />
      <text x={60} y={295} fontSize={11} fill="#60a5fa">한강</text>

      {zonePoly('120,90 320,90 320,220 120,220', '#0ea5e9')}
      <text x={130} y={108} fontSize={11} fontWeight={700} fill="#0369a1">객실동</text>

      {zonePoly('280,200 470,200 470,300 280,300', '#f59e0b')}
      <text x={290} y={218} fontSize={11} fontWeight={700} fill="#b45309">다이닝</text>

      {zonePoly('440,120 640,120 640,240 440,240', '#10b981')}
      <text x={450} y={138} fontSize={11} fontWeight={700} fill="#047857">레저·웰니스</text>

      {zonePoly('190,350 500,350 500,460 190,460', '#8b5cf6')}
      <text x={200} y={368} fontSize={11} fontWeight={700} fill="#6d28d9">MICE·엔터</text>

      {zonePoly('540,360 700,360 700,470 540,470', '#64748b')}
      <text x={550} y={378} fontSize={11} fontWeight={700} fill="#475569">인프라</text>

      <path d="M40,500 L760,500" stroke="#cbd5e1" strokeWidth={8} strokeDasharray="2 10" fill="none" />
      <text x={700} y={495} fontSize={10} fill="#94a3b8">South Gate ▸</text>

      {items.map((i) => {
        const col = i.sev === 'danger' ? 'var(--sev-danger)' : i.sev === 'warn' ? 'var(--sev-warn)' : 'var(--sev-ok)';
        const txtcol = i.sev === 'ok' ? col : '#fff';
        return (
          <g key={i.id} transform={`translate(${i.x},${i.y})`} style={{ cursor: 'pointer' }}>
            <circle r={15} fill={col} />
            {i.sev === 'ok' && <circle r={15} fill="#fff" stroke={col} strokeWidth={3} />}
            <text textAnchor="middle" y={4} fontSize={11} fontWeight={700} fill={txtcol}>
              {SEV_GLYPH[i.sev]}
            </text>
            {i.open > 0 && (
              <g transform="translate(11,-13)">
                <circle r={8} fill="#0f172a" />
                <text y={3} textAnchor="middle" fill="#fff" fontSize={10} fontWeight={700}>
                  {i.open}
                </text>
              </g>
            )}
            <text textAnchor="middle" y={30} fontSize={11} fontWeight={600} fill="#334155">
              {i.fac}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  히스토리 HTML                                                       */
/* ------------------------------------------------------------------ */

function HistoryList({ hist }: { hist: [string, string][] }) {
  return (
    <div>
      {hist.map((h, idx) => (
        <div
          key={idx}
          style={{
            display: 'flex',
            gap: 8,
            fontSize: 12,
            padding: '5px 0',
            borderBottom: '1px solid var(--line)',
          }}
        >
          <span className="muted" style={{ minWidth: 38 }}>{h[0]}</span>
          <span>{h[1]}</span>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  상세 패널                                                          */
/* ------------------------------------------------------------------ */

function DetailPanel({
  item,
  onClose,
}: {
  item: Incident;
  onClose: () => void;
}) {
  return (
    <div style={{ padding: 16, height: '100%', overflowY: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>VOC 상세</div>
        <button className="btn sm" onClick={onClose}>✕</button>
      </div>

      <SevBadge severity={item.sev}>
        {item.fac} · {STATUS_LABEL[item.status]}
      </SevBadge>

      <div
        style={{
          background: 'var(--panel-2)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 12,
          margin: '10px 0',
          fontSize: 13.5,
          lineHeight: 1.6,
        }}
      >
        &quot;{item.text}&quot;
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
        <span className="pill">{item.sent} {item.conf.toFixed(2)}</span>
        <span className="pill">{item.cat}</span>
        <span className="pill">확신도 {Math.round(item.conf * 100)}%</span>
      </div>

      <hr style={{ border: 'none', borderTop: '1px solid var(--line)', margin: '12px 0' }} />

      <label className="form-label" style={{ display: 'block' }}>상태</label>
      <select
        className="form-select"
        style={{ marginTop: 6, marginBottom: 4, padding: '9px 10px', borderRadius: 9, fontSize: 13 }}
        defaultValue={item.status}
      >
        {Object.entries(STATUS_LABEL).map(([k, v]) => (
          <option key={k} value={k}>{v}</option>
        ))}
      </select>

      <div style={{ fontSize: 11.5, color: 'var(--sev-danger)', marginBottom: 12 }}>
        ⏱ 접수 후 {item.elapsed}분 경과
        {item.sev === 'danger' && item.status === 'recv' && ' · 30분 초과 시 재알림'}
      </div>

      <label className="form-label" style={{ display: 'block' }}>처리 메모</label>
      <div style={{ display: 'flex', gap: 6, margin: '6px 0 14px' }}>
        <input
          className="form-input"
          placeholder="메모 입력 후 Enter"
          style={{ flex: 1, padding: '9px 10px', borderRadius: 9, fontSize: 13 }}
        />
      </div>

      <label className="form-label" style={{ display: 'block' }}>이력</label>
      <div style={{ marginTop: 8 }}>
        <HistoryList hist={item.hist} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  메인 화면                                                           */
/* ------------------------------------------------------------------ */

type TabKey = 'alert' | 'inbox' | 'schedule';

export default function MonitoringPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('alert');
  const [filterZone, setFilterZone] = useState('');
  const [filterSev, setFilterSev] = useState<Severity | ''>('');
  const [filterSt, setFilterSt] = useState<VOCStatus | ''>('');
  const [detailItem, setDetailItem] = useState<Incident | null>(null);
  const [lastSync, setLastSync] = useState('14:23:05');
  const [refreshing, setRefreshing] = useState(false);

  const filteredItems = useMemo(() => {
    return INC.filter((i) => {
      if (filterZone && i.zone !== filterZone) return false;
      if (filterSev && i.sev !== filterSev) return false;
      if (filterSt && i.status !== filterSt) return false;
      return true;
    });
  }, [filterZone, filterSev, filterSt]);

  const openItems = useMemo(
    () => INC.filter((i) => i.open > 0).sort((a, b) => ({ danger: 0, warn: 1, ok: 2 }[a.sev] - { danger: 0, warn: 1, ok: 2 }[b.sev])),
    [],
  );

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    setTimeout(() => {
      const d = new Date();
      setLastSync(
        `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`,
      );
      setRefreshing(false);
    }, 700);
  }, []);

  const handleDangerFilter = useCallback(() => {
    setFilterSev('danger');
  }, []);

  const handleMarkerClick = useCallback((id: string) => {
    const found = INC.find((i) => i.id === id);
    if (found) setDetailItem(found);
  }, []);

  if (INC.length === 0) {
    return (
      <Layout>
        <EmptyState message="오늘 접수된 VOC가 없습니다" />
      </Layout>
    );
  }

  return (
    <Layout>
      {/* KPI 바 */}
      <div className="kpi-bar">
        <span><b>오늘 VOC</b> {KPI.todayVoc}</span>
        <span className="sep">·</span>
        <span><b>미해결</b> {KPI.unresolved}</span>
        <span className="sep">·</span>
        <span><b>평균 처리</b> {KPI.avgProcess}분</span>
        <span className="sep">·</span>
        <button className="kpi-danger" onClick={handleDangerFilter}>
          위험 미처리 {KPI.dangerUnhandled} ⚠
        </button>
        <span style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--muted)' }}>
          마지막 갱신 {lastSync} · polling 12s
        </span>
        <button className="btn sm" style={{ marginLeft: 4 }} onClick={handleRefresh}>
          {refreshing ? <span className="spinny" /> : '지금 새로고침'}
        </button>
      </div>

      {/* 3열 그리드 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: detailItem ? '300px 1fr 360px' : '300px 1fr 0',
          transition: 'grid-template-columns 0.3s',
        }}
      >
        {/* 왼쪽: 알림/알림함/근무표 */}
        <div style={{ borderRight: '1px solid var(--line)', minHeight: 560, display: 'flex', flexDirection: 'column' }}>
          {/* 탭 */}
          <div style={{ display: 'flex', borderBottom: '1px solid var(--line)' }}>
            {([
              ['alert', '알림'],
              ['inbox', '알림함'],
              ['schedule', '근무표'],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                className={`l3tab ${activeTab === key ? 'on' : ''}`}
                onClick={() => setActiveTab(key)}
              >
                {label}
                {key === 'inbox' && (
                  <span
                    style={{
                      position: 'absolute',
                      top: 7,
                      right: 22,
                      background: 'var(--sev-danger)',
                      color: '#fff',
                      fontSize: 9,
                      padding: '0 5px',
                      borderRadius: 8,
                    }}
                  >
                    2
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* 알림 탭 */}
          {activeTab === 'alert' && (
            <div style={{ padding: 10, overflowY: 'auto', flex: 1 }}>
              {openItems.length > 0 ? openItems.map((i) => (
                <button
                  key={i.id}
                  className={`alert-item ${i.sev === 'danger' ? 'danger' : ''} ${detailItem?.id === i.id ? 'active' : ''}`}
                  onClick={() => handleMarkerClick(i.id)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <SevBadge severity={i.sev}>{i.fac} {STATUS_LABEL[i.status]}</SevBadge>
                    <span className="muted" style={{ fontSize: 11 }}>{i.ago}</span>
                  </div>
                  <div className="muted" style={{ fontSize: 11.5, marginTop: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    &quot;{i.text}&quot;
                  </div>
                  {i.sev === 'danger' && (
                    <div style={{ fontSize: 11, color: 'var(--sev-danger)', fontWeight: 600, marginTop: 5 }}>
                      ⏱ 접수 후 {i.elapsed}분 · SLA 주의
                    </div>
                  )}
                </button>
              )) : (
                <EmptyState message="오늘 접수된 VOC가 없습니다" />
              )}
            </div>
          )}

          {/* 알림함 탭 */}
          {activeTab === 'inbox' && (
            <div style={{ padding: 10 }}>
              <div className="muted" style={{ fontSize: 11, fontWeight: 700, margin: '4px 6px 8px' }}>
                읽지 않음 2
              </div>
              <div style={{ padding: '11px 12px', border: '1px solid var(--line)', borderRadius: 9, marginBottom: 8, background: '#fff' }}>
                <div style={{ fontSize: 12 }}>
                  <SevBadge severity="danger">피자힐 위험 알림</SevBadge>
                  <span className="muted"> · 3분 전</span>
                </div>
                <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>&quot;대기 40분째입니다&quot;</div>
              </div>
              <div style={{ padding: '11px 12px', border: '1px solid var(--line)', borderRadius: 9, marginBottom: 8, background: '#fff' }}>
                <div style={{ fontSize: 12 }}>
                  🌐 외부 리뷰 위험 <span className="muted">· 3시간 전</span>
                </div>
                <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>네이버 &quot;예약과 다른 객실 배정&quot;</div>
              </div>
              <div style={{ padding: '11px 12px', border: '1px solid var(--line)', borderRadius: 9, background: 'var(--panel-2)', opacity: 0.7 }}>
                <div style={{ fontSize: 12 }}>
                  <SevBadge severity="warn">리버파크 주의</SevBadge>
                  <span className="muted"> · 12분 전</span>
                  <span className="muted" style={{ float: 'right' }}>읽음</span>
                </div>
              </div>
            </div>
          )}

          {/* 근무표 탭 */}
          {activeTab === 'schedule' && (
            <div style={{ padding: 14 }}>
              <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 10 }}>
                근무표 <span className="muted" style={{ fontWeight: 400 }}>(조회 전용)</span>
              </div>
              <select className="form-select" style={{ marginBottom: 12, padding: 8, borderRadius: 8 }}>
                <option>피자힐</option>
                <option>리버파크</option>
              </select>
              {[
                ['월', '김OO', '09:00–21:00'],
                ['화', '이OO', '09:00–21:00'],
                ['수', '박OO', '12:00–24:00'],
                ['목', '김OO', '09:00–21:00'],
              ].map((r) => (
                <div key={r[0]} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 4px', borderBottom: '1px solid var(--line)', fontSize: 12.5 }}>
                  <span style={{ width: 24, color: 'var(--muted)' }}>{r[0]}</span>
                  <span style={{ flex: 1 }}>{r[1]}</span>
                  <span className="muted">{r[2]}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 중앙: 지도 */}
        <div style={{ position: 'relative', padding: '12px 12px 0' }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <select
              className="form-select"
              style={{ padding: '7px 10px', borderRadius: 8, fontSize: 12.5, width: 'auto' }}
              value={filterZone}
              onChange={(e) => setFilterZone(e.target.value)}
            >
              <option value="">구역: 전체</option>
              {Object.keys(ZONES).map((z) => (
                <option key={z} value={z}>{z}</option>
              ))}
            </select>
            <select
              className="form-select"
              style={{ padding: '7px 10px', borderRadius: 8, fontSize: 12.5, width: 'auto' }}
              value={filterSev}
              onChange={(e) => setFilterSev(e.target.value as Severity | '')}
            >
              <option value="">심각도: 전체</option>
              <option value="danger">위험</option>
              <option value="warn">주의</option>
              <option value="ok">정상</option>
            </select>
            <select
              className="form-select"
              style={{ padding: '7px 10px', borderRadius: 8, fontSize: 12.5, width: 'auto' }}
              value={filterSt}
              onChange={(e) => setFilterSt(e.target.value as VOCStatus | '')}
            >
              <option value="">상태: 전체</option>
              {Object.entries(STATUS_LABEL).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 14, alignItems: 'center', fontSize: 11.5, color: 'var(--muted)' }}>
              <span><SevBadge severity="danger">위험</SevBadge></span>
              <span><SevBadge severity="warn">주의</SevBadge></span>
              <span><SevBadge severity="ok">정상</SevBadge></span>
            </div>
          </div>

          <div className="map-container" onClick={(e) => {
            const target = e.target as SVGElement;
            const g = target.closest('g');
            const id = g?.getAttribute('data-id');
            if (id) handleMarkerClick(id);
          }}>
            <MapSvg items={filteredItems} />
          </div>
          <div className="map-note">
            변형 가이드맵 (Leaflet CRS.Simple + ImageOverlay 대체 시안) · 마커 클릭 → 상세
          </div>
        </div>

        {/* 오른쪽: 상세 패널 */}
        {detailItem && (
          <div className="detail-panel">
            <DetailPanel item={detailItem} onClose={() => setDetailItem(null)} />
          </div>
        )}
      </div>
    </Layout>
  );
}

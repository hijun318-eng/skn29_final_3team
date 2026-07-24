/**
 * SP-05b 보고서 에디터 화면
 * @see SensePlace_목업_v1.2.html — #sp05b
 */

import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../components/Layout.tsx';
import { SyntheticTag } from '../components/Badge.tsx';
import { INC } from '../data/mockData.ts';

/* ------------------------------------------------------------------ */
/*  블록 타입                                                           */
/* ------------------------------------------------------------------ */

type BlockKind = 'kpi' | 'trend' | 'table' | 'chart' | 'text';

interface Block {
  id: string;
  kind: BlockKind;
  title: string;
  draft: string;
  used: boolean;
}

const BLOCK_CATALOG: Omit<Block, 'id' | 'used'>[] = [
  { kind: 'kpi', title: 'KPI 요약', draft: '오늘 VOC 24건 · 미해결 7건 · 위험 1건 미처리' },
  { kind: 'trend', title: 'VOC 추이 (7일)', draft: '일 평균 18.1건, 목요일 피크 24건' },
  { kind: 'table', title: '위험 VOC 상위', draft: '피자힐 대기 40분 / 객실동 에어컨 소음' },
  { kind: 'chart', title: '구역별 미해결', draft: '객실동 3 / 다이닝 2 / 레저 1 / MICE 1' },
  { kind: 'text', title: '텍스트 블록', draft: '' },
];

/* ------------------------------------------------------------------ */
/*  메인 화면                                                           */
/* ------------------------------------------------------------------ */

export default function ReportEditorPage() {
  const navigate = useNavigate();
  const [blocks, setBlocks] = useState<Block[]>(() =>
    BLOCK_CATALOG.map((b, i) => ({
      ...b,
      id: `b-${i}`,
      used: i < 3,
    }))
  );
  const [nlText, setNlText] = useState('');
  const [toast, setToast] = useState('');
  const [dragId, setDragId] = useState<string | null>(null);
  const [hoverSlot, setHoverSlot] = useState<number | null>(null);
  const [confirmDialog, setConfirmDialog] = useState(false);

  const activeBlocks = blocks.filter((b) => b.used);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(''), 2000);
  };

  const addBlock = useCallback((blockId: string) => {
    setBlocks((prev) =>
      prev.map((b) => (b.id === blockId ? { ...b, used: true } : b))
    );
    showToast('블록 추가됨');
  }, []);

  const removeBlock = useCallback((blockId: string) => {
    setBlocks((prev) =>
      prev.map((b) => (b.id === blockId ? { ...b, used: false } : b))
    );
  }, []);

  const handleDragStart = useCallback((blockId: string) => {
    setDragId(blockId);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, slotIndex: number) => {
    e.preventDefault();
    setHoverSlot(slotIndex);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent, slotIndex: number) => {
    e.preventDefault();
    if (!dragId) return;

    setBlocks((prev) => {
      const active = prev.filter((b) => b.used);
      const fromIdx = active.findIndex((b) => b.id === dragId);
      if (fromIdx < 0) return prev;

      const [moved] = active.splice(fromIdx, 1);
      active.splice(slotIndex, 0, moved);

      const newMap = new Map(active.map((b) => [b.id, true]));
      return prev.map((b) => ({
        ...b,
        used: newMap.has(b.id) ? true : false,
      }));
    });

    setDragId(null);
    setHoverSlot(null);
  }, [dragId]);

  const handleDragEnd = useCallback(() => {
    setDragId(null);
    setHoverSlot(null);
  }, []);

  return (
    <Layout>
      <div className="frame-desktop" style={{ margin: 20 }}>
        {/* 상단 툴바 */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid var(--line)', gap: 10 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--brand-2)' }}>Weekly Report</span>
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>07/14~07/20 · 초안</span>
          <SyntheticTag />
          <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--muted)' }}>자동 저장: 12분 전</span>
          <button className="btn sm" style={{ marginLeft: 4 }} onClick={() => navigate('/reports')}>
            ← 목록
          </button>
          <button className="btn sm primary" onClick={() => setConfirmDialog(true)}>
            확정
          </button>
        </div>

        {/* 드로어 + 캔버스 */}
        <div className="editor-grid">
          {/* 좌측 드로어 */}
          <div className="editor-drawer">
            <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 10 }}>블록 목록</div>
            {blocks.map((b) => (
              <div
                key={b.id}
                className={`dcard ${b.used ? 'used' : ''}`}
                draggable={!b.used}
                onDragStart={() => !b.used && handleDragStart(b.id)}
                onDragEnd={handleDragEnd}
                onClick={() => !b.used && addBlock(b.id)}
                style={{ cursor: b.used ? 'default' : 'grab' }}
              >
                <div style={{ fontWeight: 700, fontSize: 12 }}>{b.title}</div>
                <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 4 }}>
                  {b.draft ? b.draft.slice(0, 40) + (b.draft.length > 40 ? '…' : '') : '(텍스트 입력)'}
                </div>
                <div style={{ fontSize: 10.5, marginTop: 4 }}>
                  {b.used ? (
                    <span style={{ color: '#047857', fontWeight: 600 }}>✓ 캔버스에 있음</span>
                  ) : (
                    <span style={{ color: 'var(--brand)', fontWeight: 600 }}>+ 추가</span>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* 우측 캔버스 */}
          <div className="editor-canvas">
            {/* NL 입력 */}
            <div className="nlbox">
              <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--brand-2)', marginBottom: 6 }}>
                ✏️ 자연어로 보고서를 만들어 보세요
              </div>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                예: "지난주 위험 VOC TOP3 넣고, 구역별 미해결 차트 추가해줘"
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  className="form-input"
                  placeholder="자연어 지시문 입력…"
                  value={nlText}
                  onChange={(e) => setNlText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && nlText.trim()) {
                      showToast('블록을 구성 중입니다…');
                      setNlText('');
                    }
                  }}
                  style={{ flex: 1, padding: '8px 10px', fontSize: 12.5 }}
                />
                <button
                  className="btn sm primary"
                  onClick={() => {
                    if (nlText.trim()) {
                      showToast('블록을 구성 중입니다…');
                      setNlText('');
                    }
                  }}
                >
                  반영
                </button>
              </div>
            </div>

            {/* 블록 슬롯 */}
            {activeBlocks.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--muted)', fontSize: 13 }}>
                왼쪽에서 블록을 드래그하거나 클릭하여 추가하세요
              </div>
            ) : (
              activeBlocks.map((b, idx) => (
                <div
                  key={b.id}
                  className={`rblk ${dragId === b.id ? 'dragging' : ''}`}
                  draggable
                  onDragStart={() => handleDragStart(b.id)}
                  onDragOver={(e) => handleDragOver(e, idx)}
                  onDrop={(e) => handleDrop(e, idx)}
                  onDragEnd={handleDragEnd}
                  style={{
                    boxShadow: hoverSlot === idx ? '0 0 0 2px var(--brand)' : undefined,
                  }}
                >
                  <div className="rhandle">
                    <span style={{ cursor: 'grab' }}>⋮⋮</span>
                    <span style={{ fontSize: 12, color: 'var(--brand-2)' }}>{b.title}</span>
                    <span style={{ marginLeft: 'auto', fontSize: 10.5, color: 'var(--muted)' }}>
                      #block:{b.id}
                    </span>
                    <button
                      className="btn sm"
                      style={{ marginLeft: 6, color: '#dc2626', border: 'none' }}
                      onClick={() => removeBlock(b.id)}
                    >
                      ✕
                    </button>
                  </div>

                  {/* 블록 종류별 내용 */}
                  {b.kind === 'kpi' && (
                    <div style={{ display: 'flex', gap: 14, fontSize: 12.5, color: '#475569', padding: '4px 0' }}>
                      <span>VOC 24건</span>
                      <span style={{ color: '#cbd5e1' }}>·</span>
                      <span>미해결 7건</span>
                      <span style={{ color: '#cbd5e1' }}>·</span>
                      <span style={{ color: '#dc2626', fontWeight: 700 }}>위험 1건 미처리</span>
                    </div>
                  )}

                  {b.kind === 'trend' && (
                    <div style={{ fontSize: 12.5, color: '#475569', padding: '4px 0' }}>
                      📊 일 평균 18.1건 · 목요일 피크(24건) · 전주 대비 +12%
                    </div>
                  )}

                  {b.kind === 'table' && (
                    <table style={{ width: '100%', fontSize: 12.5, borderCollapse: 'collapse' }}>
                      <thead>
                        <tr style={{ color: '#64748b', fontWeight: 600, textAlign: 'left' }}>
                          <th style={{ padding: '4px 0' }}>시설</th>
                          <th>증상</th>
                          <th>경과</th>
                        </tr>
                      </thead>
                      <tbody>
                        {INC.filter((i) => i.sev === 'danger' || i.sev === 'warn').slice(0, 3).map((inc) => (
                          <tr key={inc.id} style={{ borderTop: '1px solid var(--line)' }}>
                            <td style={{ padding: '5px 0', fontWeight: 600 }}>{inc.fac}</td>
                            <td style={{ color: '#475569' }}>{inc.text.slice(0, 20)}…</td>
                            <td style={{ color: '#64748b' }}>{inc.ago}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}

                  {b.kind === 'chart' && (
                    <div style={{ fontSize: 12.5, color: '#475569', padding: '4px 0' }}>
                      📊 객실동 3 / 다이닝 2 / 레저 1 / MICE 1 / 인프라 0
                    </div>
                  )}

                  {b.kind === 'text' && (
                    <textarea
                      className="form-textarea"
                      placeholder="텍스트 입력…"
                      style={{ minHeight: 60, fontSize: 12.5, padding: '8px 10px' }}
                    />
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* 확정 다이얼로그 */}
      {confirmDialog && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.45)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 999,
          }}
          onClick={() => setConfirmDialog(false)}
        >
          <div
            className="card"
            style={{ padding: 24, width: 420, maxWidth: '90vw' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>확정하시겠어요?</div>
            <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>
              확정 후에는 읽기 전용이 됩니다. 사본을 만들어 수정할 수 있습니다.
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn sm" onClick={() => setConfirmDialog(false)}>취소</button>
              <button
                className="btn sm primary"
                onClick={() => {
                  setConfirmDialog(false);
                  showToast('보고서가 확정되었습니다');
                }}
              >
                확정
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 토스트 */}
      {toast && <div className="toast">{toast}</div>}
    </Layout>
  );
}

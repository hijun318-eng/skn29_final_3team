/**
 * SP-06 외부 리뷰 화면
 * @see SensePlace_목업_v1.2.html — #sp06
 */

import { useState } from 'react';
import { Layout } from '../components/Layout.tsx';
import { SevBadge, StatusBadge, SyntheticTag } from '../components/Badge.tsx';
import { REV } from '../data/mockData.ts';
import type { Review } from '../data/mockData.ts';

/* ------------------------------------------------------------------ */
/*  유사 VOC 상태 매핑 (리뷰 sim 데이터용)                                */
/* ------------------------------------------------------------------ */

function simStatus(s: string): 'done' | 'prog' {
  return s === '완료' ? 'done' : 'prog';
}

/* ------------------------------------------------------------------ */
/*  메인 화면                                                           */
/* ------------------------------------------------------------------ */

export default function ExternalReviewPage() {
  const [selected, setSelected] = useState<Review | null>(REV[0] ?? null);

  return (
    <Layout>
      <div className="frame-desktop" style={{ margin: 20 }}>
        <div className="review-grid">
          {/* 좌측: 리뷰 목록 */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid var(--line)', gap: 10 }}>
              <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--brand-2)' }}>외부 리뷰</span>
              <SyntheticTag />
              <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--muted)' }}>07/24 기준</span>
            </div>

            {/* 필터 바 */}
            <div style={{ display: 'flex', gap: 6, padding: '10px 16px', borderBottom: '1px solid var(--line)', flexWrap: 'wrap' }}>
              <select className="btn sm">
                <option>위험도: 전체</option>
                <option>위험</option>
                <option>주의</option>
                <option>양호</option>
              </select>
              <select className="btn sm">
                <option>출처: 전체</option>
                <option>네이버</option>
                <option>구글</option>
                <option>트립어드바이저</option>
              </select>
              <select className="btn sm">
                <option>감성: 전체</option>
                <option>긍정</option>
                <option>부정</option>
              </select>
              <input className="form-input" placeholder="검색…" style={{ width: 120, padding: '4px 8px', fontSize: 12 }} />
            </div>

            {/* 리뷰 항목 */}
            {REV.map((r) => (
              <button
                key={r.id}
                className={`review-item ${selected?.id === r.id ? 'active' : ''}`}
                onClick={() => setSelected(r)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <SevBadge severity={r.sev} />
                  <span style={{ fontWeight: 700, fontSize: 13 }}>{r.text}</span>
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--muted)', display: 'flex', gap: 8 }}>
                  <span>#{r.src}</span>
                  <span>{r.ago}</span>
                  <span>감성 {r.sent}</span>
                  <span>신뢰 {r.conf}</span>
                </div>
                {r.sim.length > 0 && (
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
                    유사 VOC {r.sim.length}건
                  </div>
                )}
              </button>
            ))}
          </div>

          {/* 우측: 상세 패널 */}
          <div style={{ borderLeft: '1px solid var(--line)', overflow: 'auto' }}>
            {selected ? (
              <div>
                {/* 상단 헤더 */}
                <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <SevBadge severity={selected.sev} />
                    <span style={{ fontWeight: 800, fontSize: 16 }}>{selected.text}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                    {selected.time} · #{selected.src}
                  </div>
                </div>

                {/* 본문 */}
                <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--line)' }}>
                  <div style={{ fontSize: 13, lineHeight: 1.65, color: '#475569' }}>
                    {selected.full}
                  </div>
                </div>

                {/* 메타 */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, padding: '14px 20px', borderBottom: '1px solid var(--line)', fontSize: 12.5 }}>
                  <div>
                    <div style={{ color: 'var(--muted)', marginBottom: 4 }}>감성</div>
                    <div style={{ fontWeight: 600 }}>{selected.sent}</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--muted)', marginBottom: 4 }}>카테고리</div>
                    <div style={{ fontWeight: 600 }}>{selected.cat}</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--muted)', marginBottom: 4 }}>모델 신뢰도</div>
                    <div style={{ fontWeight: 600 }}>{(selected.conf * 100).toFixed(0)}%</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--muted)', marginBottom: 4 }}>유사 VOC</div>
                    <div style={{ fontWeight: 600 }}>{selected.sim.length}건</div>
                  </div>
                </div>

                {/* 유사 VOC 섹션 */}
                <div style={{ padding: '16px 20px' }}>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: 'var(--brand-2)' }}>
                    🔗 유사 VOC 링크
                  </div>
                  {selected.sim.length === 0 ? (
                    <div style={{ fontSize: 12.5, color: 'var(--muted)' }}>유사 VOC가 없습니다.</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {selected.sim.map((s, i) => (
                        <div key={i} className="card" style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ fontWeight: 600, fontSize: 13, flex: 1 }}>{s[0]}</span>
                          <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>{s[1]}</span>
                          <StatusBadge status={simStatus(s[2])} />
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* 액션 버튼 */}
                <div style={{ padding: '12px 20px', borderTop: '1px solid var(--line)', display: 'flex', gap: 8 }}>
                  <button className="btn sm">내부 VOC 생성</button>
                  <button className="btn sm">모니터링으로 보기</button>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--muted)' }}>
                왼쪽에서 리뷰를 선택하세요
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}

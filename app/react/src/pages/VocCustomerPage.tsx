/**
 * SP-02 고객 VOC 제출 화면 (모바일 프레임)
 * @see SensePlace_목업_v1.2.html — #sp02
 */

import { useState, useCallback } from 'react';
import { Layout } from '../components/Layout.tsx';
import { ZONES } from '../data/ontology.ts';

export default function VocCustomerPage() {
  const [text, setText] = useState('');
  const [zone, setZone] = useState('');
  const [facility, setFacility] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = text.trim().length > 0 && facility.length > 0;
  const facilities = zone ? (ZONES[zone] ?? []) : [];

  const handleSubmit = useCallback(() => {
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    setTimeout(() => {
      setSubmitted(true);
      setSubmitting(false);
    }, 900);
  }, [canSubmit, submitting]);

  const handleAgain = () => {
    setText('');
    setZone('');
    setFacility('');
    setSubmitted(false);
    setSubmitting(false);
  };

  return (
    <Layout showTopbar={false}>
      <div style={{ display: 'flex', justifyContent: 'center', padding: 28 }}>
        <div className="frame-mobile">
          <div className="notch" />

          {/* 상단 바 */}
          <div
            style={{
              background: 'var(--brand-2)',
              color: '#fff',
              padding: '13px 16px',
              borderRadius: '16px 16px 0 0',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 14 }}>SensePlace · 고객의 소리</div>
            <span
              className="demo-tag"
              style={{
                background: 'rgba(255,255,255,.15)',
                borderColor: 'rgba(255,255,255,.3)',
                color: '#e0f2fe',
              }}
            >
              데모
            </span>
          </div>

          {/* 폼 영역 */}
          {!submitted && (
            <div
              style={{
                border: '1px solid var(--line)',
                borderTop: 'none',
                borderRadius: '0 0 16px 16px',
                padding: 16,
              }}
            >
              {/* 예약 정보 */}
              <div
                style={{
                  background: 'var(--panel-2)',
                  border: '1px solid var(--line)',
                  borderRadius: 10,
                  padding: '13px 14px',
                  marginBottom: 16,
                }}
              >
                <div style={{ fontSize: 11.5, color: 'var(--muted)', fontWeight: 700, marginBottom: 6 }}>
                  ▣ 내 예약
                </div>
                <div style={{ fontWeight: 700 }}>그랜드 워커힐 · 객실 1203</div>
                <div className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>
                  07/23(목) ~ 07/25(토) · 2박
                </div>
              </div>

              {/* 텍스트 입력 */}
              <label style={{ fontSize: 13, fontWeight: 600 }}>어떤 점이 불편하셨나요?</label>
              <div style={{ position: 'relative', margin: '8px 0 16px' }}>
                <textarea
                  className="form-textarea"
                  maxLength={1000}
                  rows={4}
                  placeholder="자유롭게 남겨 주세요"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <span
                  style={{
                    position: 'absolute',
                    right: 10,
                    bottom: 8,
                    fontSize: 11,
                    color: 'var(--muted)',
                  }}
                >
                  {text.length}/1000
                </span>
              </div>

              {/* 장소 선택 */}
              <label style={{ fontSize: 13, fontWeight: 600 }}>장소</label>
              <select
                className="form-select"
                style={{ marginTop: 8 }}
                value={zone}
                onChange={(e) => { setZone(e.target.value); setFacility(''); }}
              >
                <option value="">구역 선택</option>
                {Object.keys(ZONES).map((z) => (
                  <option key={z} value={z}>{z}</option>
                ))}
              </select>
              <select
                className="form-select"
                style={{ marginTop: 8, marginBottom: 18, color: facility ? 'var(--ink)' : '#94a3b8' }}
                value={facility}
                onChange={(e) => setFacility(e.target.value)}
                disabled={!zone}
              >
                <option value="">시설 선택</option>
                {facilities.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>

              {/* 제출 */}
              <button
                className="btn primary"
                style={{ width: '100%', padding: 13 }}
                disabled={!canSubmit}
                onClick={handleSubmit}
              >
                {submitting ? '제출 중…' : '제출하기'}
              </button>
              <div className="note" style={{ textAlign: 'center', marginTop: 10 }}>
                제출 시 3초 내 접수 확인 · 감성/심각도는 비동기 산정
              </div>
            </div>
          )}

          {/* 완료 영역 */}
          {submitted && (
            <div
              style={{
                border: '1px solid var(--line)',
                borderTop: 'none',
                borderRadius: '0 0 16px 16px',
                padding: '40px 20px',
                textAlign: 'center',
              }}
            >
              <div
                style={{
                  width: 64,
                  height: 64,
                  borderRadius: '50%',
                  background: 'var(--sev-ok-soft)',
                  color: 'var(--sev-ok)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 32,
                  margin: '0 auto 16px',
                }}
              >
                ✓
              </div>
              <div style={{ fontWeight: 700, fontSize: 16 }}>접수되었습니다. 감사합니다.</div>
              <div className="muted" style={{ fontSize: 13, marginTop: 8 }}>
                담당 부서가 확인 후 조치합니다.
              </div>
              <button className="btn" style={{ marginTop: 22 }} onClick={handleAgain}>
                추가로 남기기
              </button>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}

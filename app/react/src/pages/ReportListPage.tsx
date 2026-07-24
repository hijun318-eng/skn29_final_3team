/**
 * SP-05a 보고서 목록 화면
 * @see SensePlace_목업_v1.2.html — #sp05a
 */

import { useNavigate } from 'react-router-dom';
import { Layout } from '../components/Layout.tsx';
import { StatusBadge } from '../components/Badge.tsx';

/* ------------------------------------------------------------------ */
/*  합성 보고서 데이터                                                   */
/* ------------------------------------------------------------------ */

interface ReportRow {
  type: string;
  period: string;
  status: 'draft' | 'done';
  author: string;
  modified: string;
}

const REPORTS: ReportRow[] = [
  { type: '주간', period: '07/14~07/20', status: 'draft', author: '윤OO', modified: '10분 전 수정' },
  { type: '주간', period: '07/07~07/13', status: 'done', author: '윤OO', modified: '' },
  { type: '월간', period: '06월', status: 'done', author: '박OO', modified: '' },
  { type: '분기', period: '2026 Q2', status: 'done', author: '정OO', modified: '' },
];

/* ------------------------------------------------------------------ */
/*  메인 화면                                                           */
/* ------------------------------------------------------------------ */

export default function ReportListPage() {
  const navigate = useNavigate();

  return (
    <Layout>
      <div style={{ maxWidth: 1000, margin: '0 auto', padding: 20 }}>
        {/* 헤더 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <h3 style={{ fontSize: 16 }}>보고서</h3>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <select className="btn sm">
              <option>유형: 전체</option>
              <option>주간</option>
              <option>월간</option>
              <option>분기</option>
            </select>
            <select className="btn sm">
              <option>기간: 전체</option>
            </select>
            <select className="btn sm">
              <option>상태: 전체</option>
              <option>초안</option>
              <option>확정</option>
            </select>
            <button
              className="btn primary sm"
              onClick={() => navigate('/reports/editor')}
            >
              ＋ 새 보고서
            </button>
          </div>
        </div>

        {/* 테이블 */}
        <div className="card" style={{ overflow: 'hidden' }}>
          <div className="rpt-header">
            <span>유형</span>
            <span>기간</span>
            <span>상태</span>
            <span>작성자</span>
            <span style={{ textAlign: 'right' }}>동작</span>
          </div>
          {REPORTS.map((r, idx) => (
            <div
              key={idx}
              className="rpt-row"
              onClick={(e) => {
                if (!(e.target as HTMLElement).closest('button')) {
                  navigate('/reports/editor');
                }
              }}
            >
              <span style={{ fontWeight: 600 }}>{r.type}</span>
              <span>{r.period}</span>
              <span><StatusBadge status={r.status} /></span>
              <span className="muted">{r.author}</span>
              <span style={{ textAlign: 'right' }}>
                {r.modified ? (
                  <span className="muted" style={{ fontSize: 12 }}>{r.modified}</span>
                ) : (
                  <>
                    <button
                      className="btn sm"
                      onClick={() => navigate('/reports/editor')}
                    >
                      열람
                    </button>{' '}
                    <button className="btn sm">사본</button>
                  </>
                )}
              </span>
            </div>
          ))}
        </div>

        <div className="note">
          행 클릭 = 열람 · 초안은 이어서 편집, 확정은 읽기 전용 + [사본]
        </div>
      </div>
    </Layout>
  );
}

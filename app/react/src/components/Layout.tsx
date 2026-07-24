/**
 * 공용 레이아웃 — 사이드 레일 #0b1120 + 스테이지 + 상단 바
 * @see SensePlace_목업_v1.2.html — .app, .rail, .stage, .topbar
 */

import type { ReactNode } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';

/* ------------------------------------------------------------------ */
/*  네비게이션 정의                                                     */
/* ------------------------------------------------------------------ */

interface NavItem {
  code: string;
  label: string;
  path: string;
  section: '고객 화면' | '직원 화면';
  adminOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { code: 'SP-02', label: '고객 VOC 제출', path: '/voc', section: '고객 화면' },
  { code: 'SP-01', label: '로그인', path: '/login', section: '직원 화면' },
  { code: 'SP-03', label: '실시간 모니터링', path: '/monitoring', section: '직원 화면' },
  { code: 'SP-04', label: '대화형 조회', path: '/chat', section: '직원 화면' },
  { code: 'SP-05a', label: '보고서 목록', path: '/reports', section: '직원 화면' },
  { code: 'SP-05b', label: '보고서 에디터', path: '/reports/editor', section: '직원 화면' },
  { code: 'SP-06', label: '외부 리뷰', path: '/external-review', section: '직원 화면', adminOnly: true },
];

/* ------------------------------------------------------------------ */
/*  상단 바                                                            */
/* ------------------------------------------------------------------ */

const TOP_NAV = [
  { label: '모니터링', path: '/monitoring' },
  { label: '대화형 조회', path: '/chat' },
  { label: '보고서', path: '/reports' },
  { label: '외부 리뷰', path: '/external-review', admin: true },
];

function Topbar() {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <div className="topbar">
      <div className="topbar-brand">SensePlace</div>
      <nav className="topbar-nav">
        {TOP_NAV.map((item) => {
          const active = location.pathname.startsWith(item.path);
          return (
            <button
              key={item.path}
              className={`topnav ${active ? 'on' : ''}`}
              onClick={() => navigate(item.path)}
            >
              {item.label}
              {item.admin && (
                <span style={{ fontSize: 10, opacity: 0.6 }}> (관리자)</span>
              )}
            </button>
          );
        })}
      </nav>
      <div className="topbar-right">
        <span className="conn">
          <span className="live" />실시간 연결
        </span>
        <span className="synthetic">합성 데이터 v1.0</span>
        <span className="user-chip">
          <span className="avatar">정</span>
          정승현{' '}
          <span className="role-badge">운영자</span>{' '}
          <span className="muted" style={{ fontSize: 11 }}>▾</span>
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  사이드 레일                                                         */
/* ------------------------------------------------------------------ */

interface RailProps {
  activePath: string;
}

function Rail({ activePath }: RailProps) {
  const navigate = useNavigate();
  const sections = [...new Set(NAV_ITEMS.map((n) => n.section))];

  return (
    <aside className="rail">
      <div className="rail-brand">
        <div className="logo">
          <span className="dot" />
          SensePlace
        </div>
        <div className="sub">호텔 운영 지원 · 화면 목업 v1.2</div>
      </div>

      {sections.map((section) => (
        <div key={section}>
          <div className="rail-sec">{section}</div>
          {NAV_ITEMS.filter((n) => n.section === section).map((item) => (
            <button
              key={item.code}
              className={`nav-item ${activePath === item.path ? 'on' : ''}`}
              onClick={() => navigate(item.path)}
            >
              <span className="code">{item.code}</span>
              {item.label}
            </button>
          ))}
        </div>
      ))}

      <div className="rail-foot">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span className="env-tag">STAGING</span>
          <span className="conn" style={{ fontSize: 11 }}>
            <span className="live" />배포 준비
          </span>
        </div>
        build 2026.07.24 · v1.2.0-rc<br />
        워커힐 단지 VOC 모니터링
      </div>
    </aside>
  );
}

/* ------------------------------------------------------------------ */
/*  레이아웃                                                            */
/* ------------------------------------------------------------------ */

interface LayoutProps {
  children: ReactNode;
  showTopbar?: boolean;
}

export function Layout({ children, showTopbar = true }: LayoutProps) {
  const location = useLocation();

  return (
    <div className="app-shell">
      <Rail activePath={location.pathname} />
      <main className="stage">
        {showTopbar && <Topbar />}
        {children}
      </main>
    </div>
  );
}

/**
 * 심각도/상태 뱃지 공용 컴포넌트
 * @see SensePlace_목업_v1.2.html — .sev, .badge-st
 */

import type { ReactNode } from 'react';

/* ------------------------------------------------------------------ */
/*  심각도 (Severity)                                                  */
/* ------------------------------------------------------------------ */

const SEV_GLYPH: Record<string, string> = {
  danger: '●',
  warn: '◐',
  ok: '○',
};

const SEV_LABEL: Record<string, string> = {
  danger: '위험',
  warn: '주의',
  ok: '정상',
};

const SEV_CLASS: Record<string, string> = {
  danger: 'sev-danger',
  warn: 'sev-warn',
  ok: 'sev-ok',
};

interface SevBadgeProps {
  severity: string;
  showGlyph?: boolean;
  children?: ReactNode;
}

export function SevBadge({ severity, showGlyph = true, children }: SevBadgeProps) {
  const cls = SEV_CLASS[severity] ?? 'sev-ok';
  return (
    <span className={`sev ${cls}`}>
      {showGlyph && <span className="sev-g">{SEV_GLYPH[severity]}</span>}
      {children ?? SEV_LABEL[severity]}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  상태 (Status)                                                      */
/* ------------------------------------------------------------------ */

const ST_LABEL: Record<string, string> = {
  recv: '접수',
  check: '확인',
  prog: '진행중',
  done: '완료',
};

const ST_CLASS: Record<string, string> = {
  recv: 'st-recv',
  check: 'st-check',
  prog: 'st-prog',
  done: 'st-done',
};

interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const cls = ST_CLASS[status] ?? 'st-recv';
  return <span className={`badge-st ${cls}`}>{ST_LABEL[status] ?? status}</span>;
}

/* ------------------------------------------------------------------ */
/*  합성 데이터 태그                                                   */
/* ------------------------------------------------------------------ */

export function SyntheticTag() {
  return <span className="synthetic">합성 데이터 v1.0</span>;
}

export function DemoTag() {
  return <span className="demo-tag">데모</span>;
}

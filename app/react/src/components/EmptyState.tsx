/**
 * 빈 상태 표시 컴포넌트
 */

import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon?: string;
  message?: string;
  description?: string;
  children?: ReactNode;
}

export function EmptyState({
  icon = '📭',
  message = '데이터가 없습니다',
  description,
  children,
}: EmptyStateProps) {
  return (
    <div className="state-empty">
      <div style={{ fontSize: 36, marginBottom: 12 }}>{icon}</div>
      <p style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{message}</p>
      {description && (
        <p style={{ color: 'var(--muted)', fontSize: 13 }}>{description}</p>
      )}
      {children && <div style={{ marginTop: 14 }}>{children}</div>}
    </div>
  );
}

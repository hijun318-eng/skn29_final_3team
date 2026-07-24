/**
 * 오류 상태 표시 컴포넌트
 */

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
}

export function ErrorState({
  message = '데이터를 불러오지 못했습니다.',
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="state-empty">
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: '50%',
          background: 'var(--sev-danger-soft)',
          color: 'var(--sev-danger)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 28,
          margin: '0 auto 14px',
        }}
      >
        !
      </div>
      <p style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{message}</p>
      <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 16 }}>
        잠시 후 다시 시도해 주세요.
      </p>
      {onRetry && (
        <button className="btn primary" onClick={onRetry}>
          다시 시도
        </button>
      )}
    </div>
  );
}

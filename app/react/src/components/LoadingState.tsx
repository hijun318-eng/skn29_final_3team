/**
 * 로딩 상태 표시 컴포넌트
 * @see SensePlace_목업_v1.2.html — .spinny
 */

interface LoadingStateProps {
  message?: string;
}

export function LoadingState({ message = '불러오는 중…' }: LoadingStateProps) {
  return (
    <div className="state-empty">
      <span className="spinny" />
      <p style={{ marginTop: 12, color: 'var(--muted)', fontSize: 14 }}>{message}</p>
    </div>
  );
}

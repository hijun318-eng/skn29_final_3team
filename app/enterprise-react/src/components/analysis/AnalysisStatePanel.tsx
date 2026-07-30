import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleX,
  Clock3,
  FileWarning,
  LoaderCircle,
  SearchX,
} from "lucide-react";
import { resolveViewState, type AnalysisRun, type AnalysisViewState } from "../../contracts/analysis";

const VIEW_COPY: Record<AnalysisViewState, { title: string; description: string; icon: typeof CheckCircle2 }> = {
  LOADING: { title: "분석 중", description: "승인된 분석 경로를 확인하고 있습니다.", icon: LoaderCircle },
  EMPTY: { title: "결과 없음", description: "조건을 바꾸거나 기간을 넓혀 다시 질문해 보세요.", icon: SearchX },
  READY: { title: "분석 완료", description: "검증된 결과와 근거를 표시합니다.", icon: CheckCircle2 },
  DELAYED: { title: "응답 지연", description: "일부 원천 응답을 기다리고 있습니다.", icon: Clock3 },
  PARTIAL: { title: "부분 완료", description: "성공한 원천과 실패한 원천을 구분해 표시합니다.", icon: AlertTriangle },
  ERROR: { title: "분석 실패", description: "안전한 범위에서 다시 시도하거나 관리자에게 문의하세요.", icon: CircleX },
  FORBIDDEN: { title: "접근 불가", description: "현재 역할에는 이 분석 범위가 허용되지 않습니다.", icon: Ban },
  INSUFFICIENT_EVIDENCE: { title: "근거 부족", description: "검증 근거가 확보될 때까지 결과를 표시하지 않습니다.", icon: FileWarning },
  CANCELLED: { title: "분석 취소", description: "새 질문으로 다시 시작할 수 있습니다.", icon: CircleX },
};

export function AnalysisStatePanel({ run }: { run: AnalysisRun }) {
  const viewState = resolveViewState(run);
  const copy = VIEW_COPY[viewState];
  const Icon = copy.icon;
  const showResult = viewState === "READY" || viewState === "PARTIAL";

  return (
    <section className={`analysis-state analysis-state--${viewState.toLowerCase()}`} aria-live="polite">
      <header>
        <Icon size={18} aria-hidden="true" />
        <div><b>{copy.title}</b><span>{viewState}</span></div>
      </header>
      <p>{run.error?.message ?? run.summary ?? copy.description}</p>
      {showResult && <div className="analysis-summary"><small>API 제공 요약</small><strong>{run.summary}</strong></div>}
      {viewState === "PARTIAL" && (
        <ul>{run.sources.map((source) => <li key={source.urn}>{source.name}: {source.status === "success" ? "성공" : "실패"}</li>)}</ul>
      )}
      <footer><code>{run.status}</code><span>request {run.requestId}</span></footer>
    </section>
  );
}

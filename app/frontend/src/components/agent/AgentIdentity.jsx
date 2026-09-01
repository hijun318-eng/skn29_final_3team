/** 데이터 분석 탭에서 전문 Agent의 역할과 실제 실행 조합을 일관되게 표시한다. */
import { BarChart3, Database, FileText, Layers3 } from "lucide-react";


/** 화면 전용 Agent 식별자를 서버 route 이름과 분리해 고정한다. */
export const AGENT_KIND = Object.freeze({
  analysis: "ANALYSIS",
  rag: "RAG",
  ml: "ML",
});

const AGENT_PRESENTATION = Object.freeze({
  [AGENT_KIND.analysis]: {
    label: "Analysis Agent",
    description: "승인된 운영 데이터의 지표와 기간을 분석합니다.",
    scope: "운영 데이터 분석",
    icon: BarChart3,
  },
  [AGENT_KIND.rag]: {
    label: "RAG Agent",
    description: "승인된 내부 문서를 검색하고 인용 근거와 함께 답합니다.",
    scope: "내부 문서 근거",
    icon: FileText,
  },
  [AGENT_KIND.ml]: {
    label: "ML Agent",
    description: "HGBR 예측 Tool로 객실 수요를 계산합니다.",
    scope: "객실 수요 예측",
    icon: Database,
  },
});

const SUPERVISOR_RECEIPT_SCHEMA = "SupervisorCompositionReceipt.v1";
const SUPERVISOR_AGENT_KIND = Object.freeze({
  ANALYSIS_WORKFLOW: AGENT_KIND.analysis,
  INTERNAL_GUIDELINE: AGENT_KIND.rag,
  ML_PREDICTION: AGENT_KIND.ml,
});

/** 검증된 서버 receipt에 포함된 Agent만 화면 식별자로 변환한다. */
export function supervisorAgentKinds(receipt) {
  if (!receipt || receipt.schema_version !== SUPERVISOR_RECEIPT_SCHEMA) return null;
  if (!/^model-supervisor:sha256:[a-f0-9]{64}$/.test(receipt.plan_ref || "")) return null;
  if (!Array.isArray(receipt.agents) || receipt.agents.length < 2 || receipt.agents.length > 3) return null;
  if (new Set(receipt.agents).size !== receipt.agents.length) return null;
  if (!receipt.agents.includes(receipt.primary_agent)) return null;
  if (!receipt.agents.every((kind) => SUPERVISOR_AGENT_KIND[kind])) return null;
  if (!Array.isArray(receipt.evidence_refs) || receipt.evidence_refs.length === 0) return null;
  if (new Set(receipt.evidence_refs).size !== receipt.evidence_refs.length) return null;
  if (!receipt.evidence_refs.includes(receipt.plan_ref)) return null;
  return receipt.agents.map((kind) => SUPERVISOR_AGENT_KIND[kind]);
}

/** 화면 run에 실제 포함된 전문 Agent 결과 종류를 실행 순서대로 반환한다. */
export function agentKindsForRun(run) {
  const kinds = [];
  if (
    run?.evidence
    || run?.artifact
    || run?.table
    || run?.chart
    || (Array.isArray(run?.metrics) && run.metrics.length > 0)
  ) kinds.push(AGENT_KIND.analysis);
  if (run?.rag) kinds.push(AGENT_KIND.rag);
  if (run?.mlPrediction) kinds.push(AGENT_KIND.ml);
  if (kinds.length === 0) {
    if (run?.error?.service_context === "INTERNAL_GUIDELINE") kinds.push(AGENT_KIND.rag);
    else if (run?.error?.service_context === "ML_PREDICTION") kinds.push(AGENT_KIND.ml);
    else kinds.push(AGENT_KIND.analysis);
  }
  return kinds;
}

/** 첫 화면에서 현재 대화에 연결된 전문 Agent의 책임 범위를 안내한다. */
export function AgentCapabilityOverview({ ragEnabled = false, mlEnabled = false }) {
  const kinds = [
    AGENT_KIND.analysis,
    ragEnabled ? AGENT_KIND.rag : null,
    mlEnabled ? AGENT_KIND.ml : null,
  ].filter(Boolean);
  return (
    <section className="agent-capability-overview" aria-label="사용 가능한 전문 Agent">
      {kinds.map((kind) => {
        const profile = AGENT_PRESENTATION[kind];
        const Icon = profile.icon;
        return (
          <article key={kind}>
            <span aria-hidden="true"><Icon size={17} /></span>
            <div>
              <h3>{profile.label}</h3>
              <p>{profile.description}</p>
            </div>
          </article>
        );
      })}
    </section>
  );
}

/** 한 응답을 만든 Agent 또는 Agent 협업 구성을 결과 위에 간결하게 표시한다. */
export function AgentExecutionBar({ run }) {
  const supervisorKinds = supervisorAgentKinds(run?.supervisorComposition);
  if (supervisorKinds) {
    return (
      <section className="agent-execution-tree" aria-label="Supervisor 실행 결과">
        <header>
          <span className="agent-execution-tree__icon" aria-hidden="true"><Layers3 size={16} /></span>
          <div>
            <small>Supervisor</small>
            <strong>{supervisorKinds.length}개 작업 완료</strong>
          </div>
        </header>
        <ul>
          {supervisorKinds.map((kind) => {
            const profile = AGENT_PRESENTATION[kind];
            const Icon = profile.icon;
            return (
              <li key={kind}>
                <span aria-hidden="true"><Icon size={14} /></span>
                <strong>{profile.label}</strong>
                <em>완료</em>
              </li>
            );
          })}
        </ul>
      </section>
    );
  }
  const kinds = agentKindsForRun(run);
  const composite = kinds.length > 1;
  const PrimaryIcon = composite ? Layers3 : AGENT_PRESENTATION[kinds[0]].icon;
  return (
    <div className={`agent-execution-bar ${composite ? "is-composite" : ""}`} aria-label="실행 Agent">
      <span className="agent-execution-bar__icon" aria-hidden="true"><PrimaryIcon size={15} /></span>
      <div>
        <small>{composite ? "전문 Agent 협업" : "전문 Agent"}</small>
        <strong>{kinds.map((kind) => AGENT_PRESENTATION[kind].label).join(" · ")}</strong>
      </div>
      <span className="agent-execution-bar__scope">
        {composite ? `${kinds.length}개 Agent` : AGENT_PRESENTATION[kinds[0]].scope}
      </span>
    </div>
  );
}

/** 분석 차단·실패 원인을 사용자 행동으로 연결하는 단일 진단 상태 UI 모듈이다.
 *
 * Backend의 안정적인 error code와 권한으로 필터링된 선택지만 입력으로 사용한다. SQL,
 * 내부 예외, request/trace 식별자는 표시하지 않으며 원인·다음 단계·행동을 중복 없이 조립한다.
 */
import {
  CalendarRange,
  CircleSlash2,
  DatabaseZap,
  ListFilter,
  LockKeyhole,
  RotateCcw,
  SearchX,
  ShieldAlert,
  TimerReset,
  TriangleAlert,
} from "lucide-react";
import type {
  AnalysisRun,
  AnalysisViewState,
  DisambiguationOption,
} from "../../contracts/analysis";
import { REQUIRED_ACTION_COPY } from "./AnalysisStatePanelParts";
import "./analysis-failure-state.css";

type FailureTone = "clarification" | "restricted" | "empty" | "service" | "cancelled";

interface FailurePresentation {
  tone: FailureTone;
  category: string;
  title: string;
  reason: string;
  nextStep: string;
  retryLabel?: string;
}

const SERVICE_ERROR_CODES = new Set([
  "CONTEXT_SOURCE_FAILED",
  "SOURCE_NOT_READY",
  "MODEL_TIMEOUT",
  "MODEL_ENDPOINT_UNAVAILABLE",
  "CIRCUIT_OPEN",
  "TRINO_CONNECTION_FAILED",
  "QUERY_TIMEOUT",
  "QUERY_SOURCE_FAILED",
  "RATE_LIMITED",
  "DEPENDENCY_UNAVAILABLE",
  "NETWORK_UNAVAILABLE",
]);

const RESULT_GUARD_CODES = new Set([
  "MODEL_CONTRACT_INVALID",
  "MODEL_OUTPUT_UNGROUNDED",
  "RESULT_VALIDATION_FAILED",
  "RESULT_EVIDENCE_MISSING",
  "INSUFFICIENT_EVIDENCE",
]);

const TONE_ICON = {
  clarification: ListFilter,
  restricted: LockKeyhole,
  empty: SearchX,
  service: DatabaseZap,
  cancelled: CircleSlash2,
};

function messageOr(fallback: string, message?: string) {
  const value = message?.trim();
  return value || fallback;
}

function defaultNextStep(run: AnalysisRun) {
  const action = run.error?.required_action ?? "NONE";
  return REQUIRED_ACTION_COPY[action] ?? "";
}

function filterSummary(filters: Record<string, unknown> | undefined) {
  const entries = Object.entries(filters ?? {}).map(([field, value]) => {
    const column = field.split(".").at(-1)?.replace(/_/g, " ") ?? field;
    return `${column}: ${String(value ?? "없음")}`;
  });
  return entries.length ? [...new Set(entries)].join(" · ") : "추가 필터 없음";
}

function timeEvidenceSummary(run: AnalysisRun) {
  if (run.evidence?.period) {
    return `${run.evidence.period.start} ~ ${run.evidence.period.endExclusive} 미포함`;
  }
  if (run.evidence?.snapshot) {
    return `${run.evidence.snapshot.cutoff} 이전 최신 스냅샷`;
  }
  return "확인된 기간 없음";
}

/**
 * 분석 실행의 typed failure를 원인·다음 행동이 분리된 사용자 표시 모델로 변환한다.
 * @param run 서버 응답을 정규화한 분석 실행.
 * @param viewState 결과·권한·취소를 반영한 최종 화면 상태.
 * @returns 기술 식별자 없이 렌더링할 진단 표시 모델.
 */
export function analysisFailurePresentation(
  run: AnalysisRun,
  viewState: AnalysisViewState,
): FailurePresentation {
  const error = run.error;
  const code = error?.code ?? "";
  const choices = run.disambiguationOptions?.length
    || error?.disambiguation_options?.length
    || error?.suggestions?.length;

  if (viewState === "CANCELLED" || code === "REQUEST_CANCELLED") {
    return {
      tone: "cancelled",
      category: "분석 취소",
      title: "분석을 취소했습니다",
      reason: "취소한 요청의 결과는 생성하거나 표시하지 않습니다.",
      nextStep: "필요하면 질문을 수정해 새 분석을 시작하세요.",
    };
  }

  if (error?.clarification_type === "period") {
    return {
      tone: "clarification",
      category: "입력 확인",
      title: choices ? "분석 기간을 선택해 주세요" : "분석 기간이 필요합니다",
      reason: messageOr("분석할 기간이 지정되지 않았습니다.", error.message),
      nextStep: choices
        ? "아래의 조회 가능한 기간 중 하나를 선택하면 분석을 이어갑니다."
        : "질문에 시작일·종료일 또는 하나의 상대 기간을 포함해 주세요.",
    };
  }

  if (error?.clarification_type === "metric") {
    return {
      tone: "clarification",
      category: "입력 확인",
      title: choices ? "분석 지표를 선택해 주세요" : "분석 지표가 필요합니다",
      reason: messageOr("질문에서 분석할 지표를 확정하지 못했습니다.", error.message),
      nextStep: choices
        ? "아래의 승인된 지표 중 질문에 맞는 기준을 선택하세요."
        : "분석할 지표와 기간을 포함해 질문을 수정해 주세요.",
    };
  }

  if (code === "AUTHENTICATION_REQUIRED") {
    return {
      tone: "restricted",
      category: "로그인 필요",
      title: "로그인 후 분석할 수 있습니다",
      reason: "현재 로그인 상태를 확인할 수 없어 분석을 중단했습니다.",
      nextStep: "다시 로그인한 뒤 분석을 재개하세요.",
    };
  }

  if (code === "ACCESS_DENIED") {
    return {
      tone: "restricted",
      category: "접근 제한",
      title: "이 분석에 접근할 수 없습니다",
      reason: "현재 계정에는 요청한 지표 또는 데이터 범위를 조회할 권한이 없습니다.",
      nextStep: "현재 계정에서 사용할 수 있는 지표나 분석 범위로 질문을 바꿔 주세요.",
    };
  }

  if (code === "OUT_OF_DATA_RANGE") {
    return {
      tone: "empty",
      category: "기간 확인",
      title: "조회 가능한 기간을 벗어났습니다",
      reason: messageOr("입력한 기간에는 조회 가능한 데이터가 없습니다.", error?.message),
      nextStep: "안내된 데이터 범위 안의 기간으로 질문을 수정해 주세요.",
    };
  }

  if (code === "EMPTY_RESULT") {
    return {
      tone: "empty",
      category: "결과 없음",
      title: "조건에 맞는 결과가 없습니다",
      reason: messageOr("입력한 기간과 분석 조건에 해당하는 데이터가 없습니다.", error?.message),
      nextStep: "기간을 넓히거나 호텔·분류 조건을 바꿔 다시 분석해 주세요.",
    };
  }

  if (code === "FILTER_VALUE_NOT_FOUND") {
    return {
      tone: "empty",
      category: "조건 확인",
      title: "입력한 분석 조건을 찾지 못했습니다",
      reason: messageOr("현재 데이터에서 요청한 호텔이나 분류 조건을 확인할 수 없습니다.", error?.message),
      nextStep: "호텔명이나 분류 조건을 확인한 뒤 질문을 수정해 주세요.",
    };
  }

  if (code === "METRIC_NOT_AVAILABLE") {
    return {
      tone: "empty",
      category: "지표 지원 범위",
      title: "이 지표는 아직 직접 분석할 수 없습니다",
      reason: messageOr("요청한 값은 다른 지표 계산에만 사용하는 내부 지표입니다.", error?.message),
      nextStep: "같은 업무 목적을 나타내는 공개 지표를 선택하거나, 필요한 지표의 공개 승인을 요청해 주세요.",
    };
  }

  if (code === "GRAIN_VIOLATION") {
    return {
      tone: "clarification",
      category: "분석 단위 확인",
      title: "요청한 분석 단위를 함께 사용할 수 없습니다",
      reason: messageOr("지표와 분류 기준의 분석 단위가 서로 맞지 않습니다.", error?.message),
      nextStep: "비교할 지표나 분류 기준을 줄여 다시 분석해 주세요.",
    };
  }

  if (code === "SEMANTIC_CONTRACT_INVALID") {
    return {
      tone: "restricted",
      category: "분석 계약 확인",
      title: "이 지표 조합을 안전하게 분석할 수 없습니다",
      reason: messageOr(
        "선택한 지표와 분류 기준을 연결하는 승인 관계 또는 분석 단위 계약이 없습니다.",
        error?.message,
      ),
      nextStep: "지표나 분류 기준을 줄여 다시 질문하거나, 필요한 관계 계약의 승인을 요청해 주세요.",
    };
  }

  if (["CONTEXT_INCOMPLETE", "INSUFFICIENT_CONTEXT"].includes(code)) {
    return {
      tone: "clarification",
      category: "조건 보완",
      title: "분석 조건이 부족합니다",
      reason: messageOr("질문에서 분석할 지표 또는 기간을 확인하지 못했습니다.", error?.message),
      nextStep: defaultNextStep(run) || "분석할 지표와 기간을 포함해 질문을 수정해 주세요.",
    };
  }

  if (code === "DATA_ASSET_NOT_FOUND") {
    return {
      tone: "empty",
      category: "지원 범위 확인",
      title: "승인된 분석 지표를 찾지 못했습니다",
      reason: "요청한 내용과 연결되는 승인된 호텔 데이터 지표가 없습니다.",
      nextStep: "분석하려는 호텔 업무 지표와 기간을 명확히 입력해 주세요.",
    };
  }

  if (code === "SQL_POLICY_BLOCKED") {
    return {
      tone: "restricted",
      category: "안전 정책",
      title: "안전한 분석 범위를 벗어난 요청입니다",
      reason: messageOr("요청한 방식은 승인된 읽기 전용 분석 정책에 맞지 않습니다.", error?.message),
      nextStep: defaultNextStep(run) || "질문의 지표·기간·분류 조건을 조정해 다시 분석해 주세요.",
    };
  }

  if (RESULT_GUARD_CODES.has(code) || viewState === "INSUFFICIENT_EVIDENCE") {
    return {
      tone: "restricted",
      category: "결과 보호",
      title: "결과를 안전하게 표시할 수 없습니다",
      reason: "분석 결과에 필요한 검증 근거나 계약이 완전하지 않아 값을 숨겼습니다.",
      nextStep: "검증 가능한 데이터가 준비된 뒤 다시 분석해 주세요.",
    };
  }

  if (SERVICE_ERROR_CODES.has(code)) {
    const timeout = ["MODEL_TIMEOUT", "QUERY_TIMEOUT"].includes(code);
    return {
      tone: "service",
      category: timeout ? "응답 지연" : "서비스 상태",
      title: timeout ? "제한 시간 안에 분석을 마치지 못했습니다" : "현재 분석 서비스를 사용할 수 없습니다",
      reason: timeout
        ? "데이터 조회 또는 결과 생성에 예상보다 오래 걸려 분석을 중단했습니다."
        : "분석에 필요한 데이터 서비스가 준비되지 않았거나 연결되지 않았습니다.",
      nextStep: error?.retryable
        ? "잠시 후 같은 질문을 다시 분석해 주세요."
        : "서비스가 준비된 뒤 다시 분석해 주세요.",
      retryLabel: error?.retryable ? "같은 질문 다시 분석" : undefined,
    };
  }

  if (!error && viewState === "EMPTY") {
    return {
      tone: "empty",
      category: "결과 없음",
      title: "조건에 맞는 결과가 없습니다",
      reason: "입력한 기간과 분석 조건에 해당하는 데이터가 없습니다.",
      nextStep: "기간을 넓히거나 호텔·분류 조건을 바꿔 다시 분석해 주세요.",
    };
  }

  return {
    tone: "service",
    category: "분석 중단",
    title: "분석을 완료하지 못했습니다",
    reason: "분석 처리 중 확인이 필요한 문제가 발생해 결과를 생성하지 않았습니다.",
    nextStep: error?.retryable
      ? "잠시 후 같은 질문을 다시 분석해 주세요."
      : defaultNextStep(run) || "질문의 조건을 확인한 뒤 다시 분석해 주세요.",
    retryLabel: error?.retryable ? "같은 질문 다시 분석" : undefined,
  };
}

function selectableOptions(run: AnalysisRun): DisambiguationOption[] {
  const structured = run.disambiguationOptions ?? run.error?.disambiguation_options ?? [];
  const fallbackType = run.error?.clarification_type ?? "metric";
  const values = structured.length
    ? structured
    : (run.error?.suggestions ?? []).map((label) => ({
        label,
        clarification_type: fallbackType,
        value: label,
      }));
  return [...new Map(values.map((option) => [option.label, option])).values()];
}

/** 실패 상태 하나를 원인·다음 단계·선택 또는 재시도 행동의 단일 카드로 렌더링한다. */
export function AnalysisFailureState({
  run,
  viewState,
  onSuggestion,
  onRetry,
  suggestionsDisabled = false,
}: {
  run: AnalysisRun;
  viewState: AnalysisViewState;
  onSuggestion?: (suggestion: string) => void;
  onRetry?: () => void;
  suggestionsDisabled?: boolean;
}) {
  const presentation = analysisFailurePresentation(run, viewState);
  const Icon = TONE_ICON[presentation.tone];
  const options = selectableOptions(run);
  const emptyEvidence = run.error?.code === "EMPTY_RESULT" ? run.evidence : undefined;

  return (
    <article className="analysis-diagnostic" data-tone={presentation.tone}>
      <header className="analysis-diagnostic__header">
        <span className="analysis-diagnostic__icon" aria-hidden="true"><Icon size={20} /></span>
        <div>
          <span className="analysis-diagnostic__category">{presentation.category}</span>
          <h3>{presentation.title}</h3>
        </div>
      </header>
      <div className="analysis-diagnostic__body">
        <section aria-label="분석 중단 원인">
          <span className="analysis-diagnostic__label"><TriangleAlert size={13} aria-hidden="true" />멈춘 이유</span>
          <p>{presentation.reason}</p>
        </section>
        <section className="analysis-diagnostic__next" aria-label="다음 단계">
          <span className="analysis-diagnostic__label">
            {presentation.tone === "clarification" && <ListFilter size={13} aria-hidden="true" />}
            {presentation.tone === "restricted" && <ShieldAlert size={13} aria-hidden="true" />}
            {presentation.tone === "empty" && <CalendarRange size={13} aria-hidden="true" />}
            {presentation.tone === "service" && <TimerReset size={13} aria-hidden="true" />}
            {presentation.tone === "cancelled" && <CircleSlash2 size={13} aria-hidden="true" />}
            다음 단계
          </span>
          <p>{presentation.nextStep}</p>
        </section>
      </div>
      {emptyEvidence && (
        <section className="analysis-diagnostic__evidence" aria-label="결과 없음 조회 근거">
          <span className="analysis-diagnostic__label"><SearchX size={13} aria-hidden="true" />확인한 범위</span>
          <dl>
            <div><dt>기간</dt><dd>{timeEvidenceSummary(run)}</dd></div>
            <div><dt>조건</dt><dd>{filterSummary(emptyEvidence.filters)}</dd></div>
            <div><dt>데이터 출처</dt><dd>{run.sources.map((source) => source.name).join(" · ") || "확인된 출처 없음"}</dd></div>
          </dl>
        </section>
      )}
      {options.length > 0 && (
        <section className="analysis-diagnostic__choices" aria-label={run.error?.clarification_type === "period" ? "분석 기간 선택" : "분석 지표 선택"}>
          <div className="analysis-diagnostic__choices-heading">
            <span>{run.error?.clarification_type === "period" ? "조회 가능한 기간" : "승인된 지표"}</span>
            <small>하나를 선택하세요</small>
          </div>
          <div className="analysis-diagnostic__options">
            {options.map((option) => {
              const label = option.label || option.value || option.metric_id || "";
              const isPeriod = option.clarification_type === "period";
              return (
                <button type="button" key={option.value || option.metric_id || label} disabled={suggestionsDisabled || !onSuggestion} onClick={() => onSuggestion?.(label)}>
                  <span className="analysis-diagnostic__option-icon" aria-hidden="true">{isPeriod ? <CalendarRange size={16} /> : <ListFilter size={16} />}</span>
                  <span><strong>{label}</strong>{option.description && <small>{option.description}</small>}</span>
                  <em>{isPeriod ? "기간" : "지표"}</em>
                </button>
              );
            })}
          </div>
        </section>
      )}
      {presentation.retryLabel && onRetry && options.length === 0 && (
        <footer className="analysis-diagnostic__actions">
          <button type="button" className="analysis-diagnostic__action" onClick={onRetry}><RotateCcw size={15} aria-hidden="true" />{presentation.retryLabel}</button>
        </footer>
      )}
    </article>
  );
}

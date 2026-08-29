/** AnalysisStatePanel이 사용하는 표시 문구·정렬 규칙·진행 상태 표현을 담은 모듈이다.
 *
 * 상태 패널 본체는 화면 조립과 상호작용을 담당하고, 이 모듈은 그 조립에 필요한 순수
 * 변환과 표시 전용 조각만 소유한다. 서버가 확정한 상태를 다시 판정하지 않는다.
 */
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
import type {
  AnalysisProcessStep,
  AnalysisProcessViewModel,
  AnalysisRun,
  AnalysisViewState,
  ProcessState,
} from "../../contracts/analysis";
import { metricDisplayLabel } from "../../utils/presentation";

/** 기존 import 경로를 사용하는 화면·테스트를 위해 과정 ViewModel 타입을 다시 공개한다. */
export type { AnalysisProcessStep, AnalysisProcessViewModel, ProcessState } from "../../contracts/analysis";

/** 결과 표의 정렬 상태. direction이 빈 문자열이면 정렬 해제를 뜻한다. */
export type TableSort = { column: string; direction: "" | "asc" | "desc" };

/** ViewModel 생성 시 서버에서 확인한 단계가 없으면 일반 상태 한 단계만 허용한다. */
export interface AnalysisProcessViewModelInput extends Omit<AnalysisProcessViewModel, "steps"> {
  steps?: AnalysisProcessStep[];
}

const TERMINAL_PROCESS_STATE: Record<AnalysisProcessViewModel["status"], ProcessState> = {
  running: "active",
  success: "complete",
  blocked: "blocked",
  failed: "failed",
  cancelled: "cancelled",
};

/** 서버가 확정한 분석 뷰 상태별 제목·설명·아이콘. 상태 판정은 하지 않고 표시만 담당한다. */
export const VIEW_COPY: Record<AnalysisViewState, { title: string; description: string; icon: typeof CheckCircle2 }> = {
  LOADING: { title: "분석 중", description: "분석 요청을 처리하고 있습니다.", icon: LoaderCircle },
  EMPTY: { title: "결과 없음", description: "조건이나 기간을 바꾸어 다시 요청해 주세요.", icon: SearchX },
  READY: { title: "분석 결과", description: "요청한 조건의 핵심 결과를 표시합니다.", icon: CheckCircle2 },
  DELAYED: { title: "응답 지연", description: "데이터 소스의 응답을 기다리고 있습니다.", icon: Clock3 },
  PARTIAL: { title: "일부 데이터 결과", description: "확인 가능한 결과와 응답하지 않은 소스를 구분해 표시합니다.", icon: AlertTriangle },
  ERROR: { title: "분석 실패", description: "요청을 다시 확인하거나 잠시 후 재시도해 주세요.", icon: CircleX },
  FORBIDDEN: { title: "접근 불가", description: "현재 역할에는 이 분석 범위가 허용되지 않습니다.", icon: Ban },
  INSUFFICIENT_EVIDENCE: { title: "근거 부족", description: "검증 근거를 확보하지 못해 결과를 표시하지 않습니다.", icon: FileWarning },
  CANCELLED: { title: "분석 취소", description: "새 요청으로 다시 시작할 수 있습니다.", icon: CircleX },
};

/** 서버가 지정한 required_action 코드별 사용자 안내 문구. 코드가 없으면 표시하지 않는다. */
export const REQUIRED_ACTION_COPY: Record<string, string> = {
  RETRY: "잠시 후 같은 질문을 다시 분석해 주세요.",
  AUTHENTICATE: "로그인한 뒤 다시 시도해 주세요.",
  REQUEST_ACCESS: "현재 계정에서 사용할 수 있는 지표나 분석 범위로 질문을 바꿔 주세요.",
  PROVIDE_CONTEXT: "분석할 지표나 기간을 질문에 추가해 주세요.",
  MODIFY_REQUEST: "질문의 범위나 조건을 수정해 다시 전송해 주세요.",
  CONTACT_SUPPORT: "현재는 분석을 계속할 수 없습니다. 잠시 후 다시 확인해 주세요.",
};

/**
 * 경과 시간대별 진행 안내 문구를 만든다. 내부 처리 단계를 추측하지 않는다.
 * @param {number} elapsed - 요청 시작 후 경과 초.
 * @returns {string} 표시용 안내 문구.
 */
export function progressMessage(elapsed: number) {
  if (elapsed >= 60) return "평소보다 오래 걸리고 있지만 요청은 중단되지 않았습니다. 필요하면 분석을 취소할 수 있습니다.";
  return "서버가 확인한 현재 상태와 경과 시간만 표시합니다.";
}

/**
 * 서버 progress를 표시용 ViewModel로 정규화한다. progress가 없으면 경과 시간으로 세부 단계를 만들지 않는다.
 * @param {AnalysisProcessViewModelInput} input - 요청 종류, 상태, 경과 시간과 선택적인 서버 단계.
 * @returns {AnalysisProcessViewModel} 화면에서 바로 사용할 과정 ViewModel.
 */
export function createAnalysisProcessViewModel(input: AnalysisProcessViewModelInput): AnalysisProcessViewModel {
  const fallbackLabel = input.kind === "PRESENTATION"
    ? "요청한 보기를 준비하고 있습니다"
    : "분석 요청을 처리하고 있습니다";

  return {
    kind: input.kind,
    status: input.status,
    elapsedSeconds: Math.max(0, Math.floor(input.elapsedSeconds)),
    cancelRequested: input.cancelRequested,
    steps: input.steps?.length
      ? input.steps.map((step) => ({ ...step }))
      : [{ id: `${input.kind.toLowerCase()}-status`, label: fallbackLabel, state: TERMINAL_PROCESS_STATE[input.status] }],
  };
}

const PROCESS_STATE_COPY: Record<ProcessState, string> = {
  pending: "대기",
  active: "진행 중",
  complete: "완료",
  blocked: "진행 불가",
  failed: "실패",
  cancelled: "취소됨",
};

function processStepClass(state: ProcessState) {
  if (state === "complete") return "done";
  if (state === "active") return "active";
  if (["blocked", "failed", "cancelled"].includes(state)) return "failed";
  return "";
}

function processStepMarker(state: ProcessState, index: number) {
  if (state === "complete") return "✓";
  if (state === "active") return "•";
  if (state === "cancelled") return "–";
  if (state === "blocked" || state === "failed") return "×";
  return String(index + 1);
}

/** 서버가 확인한 과정 단계만 렌더링하며 ANALYSIS와 PRESENTATION 안내 문맥을 분리한다. */
export function AnalysisProgress({ model }: { model: AnalysisProcessViewModel }) {
  const isPresentation = model.kind === "PRESENTATION";
  const isTerminal = model.status !== "running";
  const displayedSteps: AnalysisProcessStep[] = isPresentation
    ? [{
        id: "presentation-response",
        label: "요청한 보기 구성",
        state: model.cancelRequested ? "cancelled" as const : TERMINAL_PROCESS_STATE[model.status],
      }]
    : model.steps;
  const completedStepCount = displayedSteps.filter((step) => step.state === "complete").length;
  return (
    <section
      className={`analysis-trace ${isTerminal ? "analysis-trace--complete" : "analysis-trace--indeterminate"}`}
      aria-label={isPresentation ? "보기 준비 상태" : "분석 진행 상태"}
      aria-live="polite"
      data-process-kind={model.kind}
      data-process-status={model.status}
      data-process-flow="vertical"
    >
      <header>
        <div>
          <small>{isPresentation ? "표현 준비" : "분석 과정"}</small>
          <h3>{isTerminal
            ? (isPresentation ? "요청한 형태로 답변을 구성했습니다" : "분석 과정을 완료했습니다")
            : (isPresentation ? "요청한 형태로 답변을 구성하고 있습니다" : "승인된 범위에서 분석하고 있습니다")}</h3>
        </div>
        <span>
          {model.cancelRequested
            ? "취소 요청됨"
            : isTerminal
              ? `${completedStepCount}/${displayedSteps.length} 단계 완료`
              : `${completedStepCount}/${displayedSteps.length} 단계 · ${model.elapsedSeconds}초`}
        </span>
      </header>
      <ol>
        {displayedSteps.map((step, index) => (
          <li key={step.id} className={processStepClass(step.state)} data-state={step.state}>
            <i aria-hidden="true">{processStepMarker(step.state, index)}</i>
            <div>
              <b>{step.label}</b>
              {step.description && <small>{step.description}</small>}
            </div>
            <em>{PROCESS_STATE_COPY[step.state]}</em>
          </li>
        ))}
      </ol>
      {!isPresentation && model.status === "running" && <p>{progressMessage(model.elapsedSeconds)}</p>}
      <p className="analysis-progress-boundary">
        {isPresentation
          ? "요청한 형식에 맞춰 답변을 준비합니다."
          : "서버가 반환한 실행 트레이스를 업무 단계로 묶어 표시합니다."}
      </p>
    </section>
  );
}

/**
 * 결과 컬럼의 표시 라벨을 승인된 지표 metadata에서 찾는다.
 * @param {string} column - 결과 컬럼(result field) 이름.
 * @param {AnalysisRun} run - 지표 metadata를 담은 실행 결과.
 * @returns {string} 지표 라벨, 없으면 컬럼 이름 그대로.
 */
export function columnLabel(column: string, run: AnalysisRun) {
  if (column === "period") return "기간";
  const metric = run.metrics.find((item) => item.resultField === column)
    ?? run.evidence?.metrics.find((item) => item.resultField === column);
  return metric ? metricDisplayLabel(metric) : column;
}

/**
 * 결과 컬럼의 단위를 승인된 지표 metadata에서 찾는다.
 * @param {string} column - 결과 컬럼(result field) 이름.
 * @param {AnalysisRun} run - 지표 metadata를 담은 실행 결과.
 * @returns {string|null} 지표 단위, 없으면 null.
 */
export function columnUnit(column: string, run: AnalysisRun) {
  return run.metrics.find((item) => item.resultField === column)?.unit
    ?? run.evidence?.metrics.find((item) => item.resultField === column)?.unit
    ?? null;
}

/**
 * 제목에서 바로 이어 반복된 단어를 제거해 읽기 쉽게 만든다.
 * @param {string} value - 원본 제목.
 * @returns {string} 중복 단어를 정리한 제목.
 */
export function tidyAnalysisTitle(value: string) {
  const words = value.trim().split(/\s+/);
  return words.filter((word, index) => index === 0 || word !== words[index - 1]).join(" ");
}

/**
 * 컬럼 헤더를 눌렀을 때 이동할 다음 정렬 상태를 계산한다(오름차순 → 내림차순 → 해제).
 * @param {TableSort} current - 현재 정렬 상태.
 * @param {string} column - 사용자가 누른 컬럼.
 * @returns {TableSort} 다음 정렬 상태.
 */
export function nextTableSort(current: TableSort, column: string): TableSort {
  if (current.column !== column) return { column, direction: "asc" };
  if (current.direction === "asc") return { column, direction: "desc" };
  return { column: "", direction: "" };
}

/**
 * 표 정렬 비교자. 빈 값은 항상 뒤로 보내고, 숫자는 수치로, 그 외는 한국어 로케일로 비교한다.
 * @param {unknown} left - 왼쪽 값.
 * @param {unknown} right - 오른쪽 값.
 * @returns {number} 음수/0/양수 비교 결과.
 */
export function compareTableValues(left: unknown, right: unknown) {
  if (left === null || left === undefined || left === "") return right === null || right === undefined || right === "" ? 0 : 1;
  if (right === null || right === undefined || right === "") return -1;
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (!Number.isNaN(leftNumber) && !Number.isNaN(rightNumber) && Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber;
  }
  return String(left).localeCompare(String(right), "ko", { numeric: true });
}

/** 분석 결과의 시각화 노출 형태(요약, KPI, 차트, 표, 전체)를 정의하는 타입이다. */

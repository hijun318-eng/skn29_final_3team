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
import type { AnalysisRun, AnalysisViewState } from "../../contracts/analysis";

/** 결과 표의 정렬 상태. direction이 빈 문자열이면 정렬 해제를 뜻한다. */
export type TableSort = { column: string; direction: "" | "asc" | "desc" };

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
  if (elapsed >= 30) return "데이터 조회와 결과 검증을 계속 진행하고 있습니다. 완료되는 즉시 결과를 표시합니다.";
  if (elapsed >= 10) return "분석이 계속 진행 중입니다. 현재 단계와 경과 시간을 자동으로 갱신합니다.";
  return "질문은 그대로 보존됩니다. 현재 상태와 경과 시간을 자동으로 갱신합니다.";
}

/** 서버 내부 단계를 추측하지 않고 경과시간과 취소 가능한 진행 상태만 표시한다. */
export function AnalysisProgress({ elapsed }: { elapsed: number }) {
  return (
    <section className="analysis-trace analysis-trace--indeterminate" aria-label="분석 진행 상태" aria-live="polite">
      <header>
        <div>
          <small>현재 상태</small>
          <h3>승인된 범위에서 분석하고 있습니다</h3>
        </div>
        <span>{elapsed}초 경과</span>
      </header>
      <p>{progressMessage(elapsed)}</p>
      <p className="analysis-progress-boundary">
        서버가 확정한 결과와 근거가 준비되면 이 화면에 표시합니다. 내부 처리 순서는 추측해 표시하지 않습니다.
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
  return run.metrics.find((item) => item.resultField === column)?.label
    ?? run.evidence?.metrics.find((item) => item.resultField === column)?.label
    ?? column;
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

/** 보고서 API·상태·시각 값을 사용자 표시 문자열로 안전하게 변환하는 모듈이다. */
import { ReportApiError } from "../../api/reportClient";

/** 보고서 오류를 민감한 내부 정보 없이 사용자 메시지로 축약한다. */
export function reportApiError(error: unknown): string {
  if (error instanceof ReportApiError) return error.message;
  if (error instanceof TypeError) {
    return "서버에 연결할 수 없습니다. 네트워크 연결을 확인한 뒤 다시 시도해 주세요.";
  }
  return error instanceof Error ? error.message : "보고서 요청을 처리하지 못했습니다.";
}

/** 서버 requiredAction을 안전한 후속 조치 문구로 변환한다. */
export function reportApiRequiredAction(error: unknown): string {
  if (error instanceof ReportApiError) return error.requiredAction;
  if (error && typeof error === "object" && "requiredAction" in error) {
    const requiredAction = (error as { requiredAction?: unknown }).requiredAction;
    if (typeof requiredAction === "string") return requiredAction;
  }
  return error instanceof TypeError ? "RETRY" : "NONE";
}

/** ISO 시각을 서울 시간으로 표시하며 누락값은 명시적으로 표시한다. */
export function formatSeoulTime(value?: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Seoul",
  }).format(new Date(value));
}

/** 정의 상태 프로토콜을 사용자 라벨로 변환하고 미지원 값은 확인 필요로 닫는다. */
export function reportStatusLabel(status?: string | null): string {
  return status === "approved" ? "확정" : "초안";
}

const RUN_STATUS_LABELS: Readonly<Record<string, string>> = Object.freeze({
  queued: "대기 중",
  running: "실행 중",
  success: "완료",
  partial: "일부 완료",
  failed: "실패",
  cancelled: "취소됨",
});

/** 실행 상태 프로토콜을 사용자 라벨로 변환하고 미지원 값은 확인 필요로 닫는다. */
export function reportRunStatusLabel(status?: string | null): string {
  return RUN_STATUS_LABELS[String(status || "").toLowerCase()] || "확인 필요";
}

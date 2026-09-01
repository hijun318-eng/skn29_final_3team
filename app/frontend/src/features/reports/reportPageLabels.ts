/** 보고서 API·상태·시각 값을 사용자 표시 문자열로 안전하게 변환하는 모듈이다. */
import { ReportApiError } from "../../api/reportClient.ts";

/** 보고서 오류를 민감한 내부 정보 없이 사용자 메시지로 축약한다. */
export function reportApiError(error: unknown): string {
  if (error instanceof ReportApiError) {
    if (error.code === "REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED") {
      return "요청한 페이지 수와 실제 렌더 결과가 일치하지 않아 저장하지 않았습니다. 변경안을 조정한 뒤 다시 검토해 주세요.";
    }
    if (error.code === "EXTERNAL_TRANSFER_DISCLOSURE_STALE") {
      return "외부 전송 동의 요청이 만료되었거나 전송 범위가 변경되었습니다. 요청을 다시 실행해 새 범위를 확인해 주세요.";
    }
    if (error.code === "EXTERNAL_TRANSFER_DISCLOSURE_NOT_FOUND") {
      return "확인할 외부 전송 동의 요청을 찾지 못했습니다. Assistant 요청을 다시 실행해 주세요.";
    }
    if (error.status === 401) return "로그인이 만료되었습니다. 다시 로그인해 주세요.";
    if (error.status === 403) return "이 정보를 볼 권한이 없습니다. 관리자에게 권한을 확인해 주세요.";
    if (error.status === 404) return "연결된 정보를 찾을 수 없습니다.";
    if (error.status === 409) return "다른 변경 사항이 먼저 저장되었습니다. 최신 상태를 다시 불러와 주세요.";
    if (error.status === 429) return "요청이 많아 잠시 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.";
    if (error.status >= 500) return "보고서 서비스가 응답하지 않습니다. 잠시 후 다시 시도해 주세요.";
    if (error.status === 400 || error.status === 422) return "요청 내용을 확인해 주세요.";
    return "보고서 요청을 처리하지 못했습니다. 다시 시도해 주세요.";
  }
  if (error instanceof TypeError) {
    return "네트워크에 연결할 수 없습니다. 연결을 확인한 뒤 다시 시도해 주세요.";
  }
  return "보고서 요청을 처리하지 못했습니다. 다시 시도해 주세요.";
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

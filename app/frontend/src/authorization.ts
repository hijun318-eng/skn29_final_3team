/** 서버가 확정한 Capability를 화면 노출에 적용하는 프런트엔드 권한 표현 모듈이다. */

export const CAPABILITY = {
  runAnalysis: "analysis.run",
  readAnalysis: "analysis.read",
  draftReport: "report.draft",
  manageReport: "report.manage",
  manageData: "data.manage",
  manageSystem: "system.manage",
} as const;

/** Backend 공개 계약이 반환할 수 있는 서비스 Capability 문자열의 허용 집합이다. */
export type ServiceCapability = typeof CAPABILITY[keyof typeof CAPABILITY];

/** Backend 인증 계약이 반환할 수 있는 사용자 Role 문자열의 허용 집합이다. */
export type ServiceRole = "analyst" | "admin";

/** 서버 세션이 반환한 Capability 배열만으로 화면 기능 노출 여부를 판정한다. */
export function hasCapability(
  capabilities: readonly ServiceCapability[] | undefined,
  capability: ServiceCapability,
): boolean {
  return Boolean(capabilities?.includes(capability));
}

/** 감사 가능한 서버 Role을 사용자 화면의 짧은 한국어 레이블로 표시한다. */
export function roleLabel(role: ServiceRole | string): string {
  return role === "admin" ? "시스템 관리자" : "분석 사용자";
}

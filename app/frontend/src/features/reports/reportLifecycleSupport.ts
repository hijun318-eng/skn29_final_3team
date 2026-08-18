/** 보고서 lifecycle의 정의 정렬·identity 비교를 제공하는 순수 helper 모듈이다. */
import type { ReportDefinitionVersion } from "../../contracts/report.ts";

/** 보고서 실행 내역을 점진 표시하는 페이지 크기다. */ export const REPORT_RUN_PAGE_SIZE = 10;

/** 정의를 수정시각·버전 역순으로 정렬하되 원본 배열은 변경하지 않는다. */
export function sortReportDefinitions(
  definitions: readonly ReportDefinitionVersion[],
): ReportDefinitionVersion[] {
  return [...definitions].sort((left, right) => (
    right.version - left.version || left.title.localeCompare(right.title, "ko-KR")
  ));
}

/** 두 정의가 같은 immutable ID·버전을 가리키는지 판정한다. */
export function isSameReportDefinition(
  left: ReportDefinitionVersion,
  right: ReportDefinitionVersion,
): boolean {
  return left.definitionId === right.definitionId && left.version === right.version;
}

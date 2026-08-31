/** Report Assistant 브라우저 복구 key와 서버 세션의 보고서 scope 검증을 제공한다. */
import type {
  ReportAssistantSessionResponse,
  ReportDefinitionVersion,
} from "../../contracts/report.ts";

type ReportAssistantDefinitionScope = Pick<
  ReportDefinitionVersion,
  "definitionId" | "version"
>;

const REPORT_ASSISTANT_SESSION_KEY_PREFIX = "answervice.report-assistant:v2";

/** Artifact 선택과 무관한 보고서 draft identity로 세션 복구 key를 만든다. */
export function reportAssistantSessionStorageKey(
  definition: ReportAssistantDefinitionScope | null | undefined,
): string {
  const definitionId = definition?.definitionId?.trim();
  const version = definition?.version;
  if (!definitionId || !Number.isInteger(version) || Number(version) < 1) return "";
  return `${REPORT_ASSISTANT_SESSION_KEY_PREFIX}:${encodeURIComponent(definitionId)}:${version}`;
}

/** 서버에서 복구한 세션이 현재 보고서 draft 또는 그 세션이 만든 revision인지 판정한다. */
export function reportAssistantSessionMatchesDefinition(
  session: ReportAssistantSessionResponse | null | undefined,
  definition: ReportAssistantDefinitionScope | null | undefined,
): boolean {
  if (!session || !definition || session.definition_id !== definition.definitionId) return false;
  if (session.definition_version === definition.version) return true;
  return session.phase === "completed" && session.result_revision === definition.version;
}

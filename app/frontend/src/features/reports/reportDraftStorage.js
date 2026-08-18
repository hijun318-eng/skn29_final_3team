/** 새 서버 저장 전 복구용 session draft snapshot을 versioned 형식으로 관리하는 모듈이다. */
import {
  REPORT_DOCUMENT_SCHEMA_VERSION,
  validateReportDocument,
} from "./reportDocument.ts";
import {
  frontendBlocksFromDocument,
  frontendBlocksToDocument,
} from "./reportDraftOperations.js";

/** 브라우저 임시 draft snapshot의 호환성 버전이다. */ export const FRONTEND_REPORT_DRAFT_VERSION = "ANSWER-REPORT-DRAFT-v2";

/** 정의 ID·버전을 충돌 없는 sessionStorage key로 인코딩한다. */
export function frontendDraftStorageKey(definitionId, version) {
  return `answervice:report-draft:v2:${definitionId}:${version}`;
}

/** 현재 편집 상태를 versioned·검증 가능한 session snapshot으로 복제한다. */
export function createFrontendDraftSnapshot({
  definitionId,
  version,
  title,
  orientation,
  currencyPolicy,
  blocks,
}) {
  const converted = frontendBlocksToDocument({
    definitionId,
    title,
    orientation,
    currencyPolicy,
    blocks,
  });
  if (!converted.ok) return converted;
  const normalizedBlocks = frontendBlocksFromDocument(converted.document, blocks);
  return {
    ok: true,
    snapshot: {
      schemaVersion: FRONTEND_REPORT_DRAFT_VERSION,
      definitionRef: { definitionId, version },
      document: converted.document,
      blocks: normalizedBlocks,
    },
  };
}

/** 주입된 Storage에 draft를 저장하며 quota/권한 실패를 false로 반환한다. */
export function saveFrontendDraft(storage, snapshot) {
  storage.setItem(
    frontendDraftStorageKey(snapshot.definitionRef.definitionId, snapshot.definitionRef.version),
    JSON.stringify(snapshot),
  );
}

/** 정확한 버전·정의와 일치하는 snapshot만 복원하고 손상 데이터는 null로 버린다. */
export function loadFrontendDraft(storage, definitionId, version) {
  const serialized = storage.getItem(frontendDraftStorageKey(definitionId, version));
  if (!serialized) return null;
  try {
    const snapshot = JSON.parse(serialized);
    if (
      snapshot.schemaVersion !== FRONTEND_REPORT_DRAFT_VERSION
      || snapshot.definitionRef?.definitionId !== definitionId
      || snapshot.definitionRef?.version !== version
      || !Array.isArray(snapshot.blocks)
    ) return null;
    const validation = validateReportDocument(snapshot.document);
    if (!validation.valid || snapshot.document.schemaVersion !== REPORT_DOCUMENT_SCHEMA_VERSION) return null;
    return {
      orientation: snapshot.document.orientation,
      currencyPolicy: snapshot.document.currencyPolicy,
      blocks: frontendBlocksFromDocument(snapshot.document, snapshot.blocks),
    };
  } catch {
    return null;
  }
}

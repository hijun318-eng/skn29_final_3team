/** versioned 편집 문서의 타입·검증·순수 연산 공개 표면을 제공하는 barrel 모듈이다. */
export {
  A4_PAGE_LAYOUT,
  CURRENCY_DISPLAY_UNITS,
  PRESENTATION_MODES,
  REPORT_DOCUMENT_SCHEMA_VERSION,
  REPORT_GRID_COLUMNS,
} from "./reportDocumentTypes.ts";
/** 편집 문서의 공개 TypeScript 타입을 재노출한다. */
export type {
  ArtifactReference,
  ArtifactReportBlock,
  CreateReportDocumentInput,
  CurrencyDisplayPolicy,
  CurrencyDisplayUnit,
  DocumentOperationResult,
  InsertArtifactInput,
  MarkdownReportBlock,
  PageBreakReportBlock,
  PresentationMode,
  ReportDocumentBlock,
  ReportDocumentPage,
  ReportDocumentV2,
  ReportDropPlacement,
  ReportOrientation,
  ValidationResult,
} from "./reportDocumentTypes.ts";
/** 문서 전체 검증 진입점을 재노출한다. */
export { validateReportDocument } from "./reportDocumentValidation.ts";
/** 원본 보존 문서 연산 진입점을 재노출한다. */
export {
  compactReportDocument,
  createReportDocument,
  deleteReportBlock,
  insertArtifactBlock,
  moveReportBlock,
  parseReportDocument,
  serializeReportDocument,
  setReportOrientation,
} from "./reportDocumentOperations.ts";

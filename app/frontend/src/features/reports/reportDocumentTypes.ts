/** API와 분리된 A4 편집 문서의 schema·block·operation 타입을 정의하는 모듈이다. */
/** 프런트 편집 문서 직렬화의 호환성 버전이다. */ export const REPORT_DOCUMENT_SCHEMA_VERSION = "REPORT-DOCUMENT-v2" as const;
/** A4 편집기와 drag 계산이 공유하는 grid 열 수다. */ export const REPORT_GRID_COLUMNS = 12 as const;

/** 방향별 실제 A4 크기와 배치 가능 row 계약이다. */ export const A4_PAGE_LAYOUT = Object.freeze({
  portrait: Object.freeze({ widthMm: 210, heightMm: 297, contentRows: 30 }),
  landscape: Object.freeze({ widthMm: 297, heightMm: 210, contentRows: 18 }),
});

/** artifact 상세 수준으로 허용된 표현 모드다. */ export const PRESENTATION_MODES = Object.freeze(["summary", "standard", "detail"] as const);
/** 편집기에서 선택 가능한 통화 배율 집합이다. */ export const CURRENCY_DISPLAY_UNITS = Object.freeze([
  "auto",
  "one",
  "thousand",
  "million",
  "hundredMillion",
  "billion",
] as const);

/** A4 문서 방향 타입이다. */ export type ReportOrientation = keyof typeof A4_PAGE_LAYOUT;
/** artifact 표현 상세 수준 타입이다. */ export type PresentationMode = (typeof PRESENTATION_MODES)[number];
/** 통화 배율 타입이다. */ export type CurrencyDisplayUnit = (typeof CURRENCY_DISPLAY_UNITS)[number];

/** 문서 전역 통화 코드·배율·반올림 표시 정책이다. */ export interface CurrencyDisplayPolicy {
  currencyCode: string;
  displayUnit: CurrencyDisplayUnit;
  unitPlacement: "header" | "value";
  maximumFractionDigits: number;
}

/** 영속 artifact의 ID와 선택적 버전/checksum 참조다. */ export interface ArtifactReference {
  artifactId: string;
  version?: string | number;
  checksum?: string;
}

interface ReportBlockBase {
  id: string;
  title: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** governed artifact를 참조하는 문서 블록이다. */ export interface ArtifactReportBlock extends ReportBlockBase {
  kind: "artifact";
  artifactRef: ArtifactReference;
  presentationMode: PresentationMode;
  visibleViews: string[];
}

/** 사용자가 작성한 Markdown 문서 블록이다. */ export interface MarkdownReportBlock extends ReportBlockBase {
  kind: "markdown";
  markdown: string;
}

/** 명시적 A4 페이지 분리 표식 블록이다. */ export interface PageBreakReportBlock extends ReportBlockBase {
  kind: "pageBreak";
  label?: string;
}

/** 편집 문서에 허용되는 블록 합집합이다. */ export type ReportDocumentBlock = ArtifactReportBlock | MarkdownReportBlock | PageBreakReportBlock;

/** 순서와 방향이 확정된 하나의 A4 페이지다. */ export interface ReportDocumentPage {
  id: string;
  index: number;
  size: "A4";
  orientation: ReportOrientation;
  blocks: ReportDocumentBlock[];
}

/** API payload와 의도적으로 분리된 프런트 소유 편집 모델이다. */
export interface ReportDocumentV2 {
  schemaVersion: typeof REPORT_DOCUMENT_SCHEMA_VERSION;
  id: string;
  title: string;
  orientation: ReportOrientation;
  presentationMode: PresentationMode;
  currencyPolicy: CurrencyDisplayPolicy;
  pages: ReportDocumentPage[];
}

/** 문서 검증 성공 여부와 정확한 경로별 오류 목록이다. */ export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

/** 문서 연산의 원본 보존 성공/실패 결과다. */ export type DocumentOperationResult =
  | { ok: true; document: ReportDocumentV2; errors: [] }
  | { ok: false; document: ReportDocumentV2; errors: string[] };

/** 키보드·포인터 삽입이 공유하는 상대 배치 명령이다. */ export type ReportDropPlacement =
  | { type: "end"; pageId?: string }
  | { type: "before" | "after"; targetBlockId: string }
  | { type: "side"; targetBlockId: string; edge: "left" | "right" };

/** 새 artifact 블록 삽입에 필요한 검증 전 입력이다. */ export interface InsertArtifactInput {
  blockId: string;
  title: string;
  artifactRef: ArtifactReference;
  presentationMode?: PresentationMode;
  visibleViews: string[];
  width?: 6 | 12;
  height?: number;
  placement?: ReportDropPlacement;
}

/** 빈 편집 문서 생성에 필요한 식별자·표시 정책 입력이다. */ export interface CreateReportDocumentInput {
  id: string;
  title: string;
  orientation?: ReportOrientation;
  presentationMode?: PresentationMode;
  currencyPolicy?: Partial<CurrencyDisplayPolicy>;
}

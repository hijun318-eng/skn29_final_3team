/** 보고서 draft hook의 입력·상태·명령 반환 타입을 정의하는 모듈이다. */
import type { MutableRefObject } from "react";
import type {
  DraftLayoutBlock,
  ReportCurrencyDisplayUnit,
  ReportOrientation,
} from "../../contracts/report.ts";

/** 편집기에 필요한 kind·artifact 출처·표현 설정을 확장한 draft 블록이다. */ export type DraftReportBlock = DraftLayoutBlock & {
  readonly artifactChecksum?: string;
  readonly artifactDefinitionId?: string;
  readonly artifactDefinitionVersion?: number;
  readonly artifactRequestId?: string;
  readonly artifactSourceKind?: string;
  readonly sourceKind?: string;
  readonly requestId?: string;
  readonly analysisDefinitionId?: string;
  readonly analysisDefinitionVersion?: number;
};

/** draft 전역 통화 표시 정책이다. */ export interface DraftCurrencyPolicy {
  readonly currencyCode: string;
  readonly displayUnit: ReportCurrencyDisplayUnit;
  readonly unitPlacement: string;
  readonly maximumFractionDigits: number;
}

/** 편집기 artifact renderer가 소비하는 최소 분석 결과 계약이다. */ export interface DraftArtifactData {
  readonly artifact_id?: string;
  readonly artifact_checksum?: string;
  readonly query_id?: string;
  readonly chart?: unknown;
  readonly [key: string]: unknown;
}

/** 분석 실행 또는 정의에서 유래한 artifact library 항목이다. */ export interface DraftArtifactSource {
  readonly artifactId: string;
  readonly title?: string;
  readonly definitionTitle?: string;
  readonly artifactChecksum?: string;
  readonly sourceKind?: string;
  readonly artifactSourceKind?: string;
  readonly definitionId?: string;
  readonly definitionVersion?: number;
  readonly requestId?: string;
  readonly artifactRequestId?: string;
  readonly analysisDefinitionId?: string;
  readonly analysisDefinitionVersion?: number;
  readonly queryId?: string;
  readonly question?: string;
  readonly sourceUrns?: readonly string[];
}

/** 새 편집 블록을 만드는 일반 template 입력이다. */ export interface DraftBlockTemplate {
  readonly id: string;
  readonly blockTitle?: string;
  readonly content?: string;
  readonly w: number;
  readonly h: number;
}

/** drag 또는 키보드 삽입의 대상 위치다. */ export interface DraftInsertPosition {
  readonly x?: number;
  readonly y?: number;
  readonly w?: number;
  readonly requestedX?: number;
  readonly pageId?: string;
  readonly placement?: unknown;
}

/** 저장소 key와 API 명령을 고정하는 정의 ID·버전이다. */ export interface ReportDraftIdentity {
  readonly definitionId?: string;
  readonly version?: number;
  readonly title?: string;
}

/** draft hook의 영속소·artifact 조회·focus 요청 의존성이다. */ export interface UseReportDraftStateOptions {
  readonly editable: boolean;
  readonly artifacts?: Readonly<Record<string, DraftArtifactData | undefined>>;
  readonly artifactSources?: readonly DraftArtifactSource[];
  readonly selectedArtifactId?: string;
  readonly templates?: ReadonlyMap<string, DraftBlockTemplate>;
  readonly identity?: ReportDraftIdentity;
  readonly initialBlocks?: readonly DraftReportBlock[];
  readonly initialOrientation?: ReportOrientation;
  readonly initialCurrencyPolicy?: Partial<DraftCurrencyPolicy>;
  readonly onError?: (message: string) => void;
  readonly onNotice?: (message: string) => void;
  readonly onFocusRequest?: (blockId: string) => void;
}

/** 서버 정의나 최종문서로 draft 전체를 재설정하는 입력이다. */ export interface ResetReportDraftInput {
  readonly blocks: readonly DraftReportBlock[];
  readonly savedBlocks?: readonly DraftReportBlock[];
  readonly orientation?: ReportOrientation;
  readonly savedOrientation?: ReportOrientation;
  readonly currencyPolicy?: Partial<DraftCurrencyPolicy>;
  readonly savedCurrencyPolicy?: Partial<DraftCurrencyPolicy>;
  readonly selectedBlockId?: string;
  readonly dirty?: boolean;
}

/** undo/redo 가능 여부와 안정된 명령 callback 계약이다. */ export interface ReportDraftHistory {
  readonly past: readonly (readonly DraftReportBlock[])[];
  readonly future: readonly (readonly DraftReportBlock[])[];
}

/** 이전 블록을 불변 갱신하고 선택 ID를 함께 반환할 수 있는 updater다. */ export type DraftBlocksUpdater = (
  current: readonly DraftReportBlock[],
) => readonly DraftReportBlock[];

/** 로컬 draft와 서버 저장의 동기화 상태다. */ export type DraftSaveState = "saved" | "unsaved" | "saving" | "error";

/** editor가 소비하는 draft 값과 안정된 변경 명령의 공개 반환 계약이다. */ export interface UseReportDraftStateResult {
  readonly blocks: readonly DraftReportBlock[];
  readonly orderedBlocks: readonly DraftReportBlock[];
  readonly blocksRef: MutableRefObject<readonly DraftReportBlock[]>;
  readonly savedBlocksRef: MutableRefObject<readonly DraftReportBlock[]>;
  readonly selectedBlockId: string;
  readonly selectedBlock: DraftReportBlock | null;
  readonly history: ReportDraftHistory;
  readonly canUndo: boolean;
  readonly canRedo: boolean;
  readonly isDirty: boolean;
  readonly saveFailed: boolean;
  readonly saveState: DraftSaveState;
  readonly editorAnnouncement: string;
  readonly reportOrientation: ReportOrientation;
  readonly reportCurrencyPolicy: DraftCurrencyPolicy;
  readonly savedOrientationRef: MutableRefObject<ReportOrientation>;
  readonly currencyPolicyRef: MutableRefObject<DraftCurrencyPolicy>;
  readonly savedCurrencyPolicyRef: MutableRefObject<DraftCurrencyPolicy>;
  readonly selectBlock: (blockId: string) => void;
  readonly announce: (message: string) => void;
  readonly resetDraft: (input: ResetReportDraftInput) => void;
  readonly resetBlocks: (blocks: readonly DraftReportBlock[], dirty?: boolean) => void;
  readonly commitBlocks: (updater: DraftBlocksUpdater | readonly DraftReportBlock[], record?: boolean) => boolean;
  readonly beginSave: () => void;
  readonly markSaved: () => void;
  readonly markSaveFailed: () => void;
  readonly clearSaveFailure: () => void;
  readonly undo: () => void;
  readonly redo: () => void;
  readonly updateBlock: (blockId: string, change: Partial<DraftReportBlock>, record?: boolean) => void;
  readonly moveBlock: (blockId: string, deltaX: number, deltaY: number) => void;
  readonly resizeBlock: (
    blockId: string,
    width: number,
    height?: number,
    position?: { readonly x?: number; readonly y?: number },
  ) => void;
  readonly compactLayout: () => boolean;
  readonly setBlockSetting: (blockId: string, name: string, value: unknown) => void;
  readonly addTemplateBlock: (
    templateId: string,
    position?: DraftInsertPosition | null,
    settings?: { readonly chartType?: string },
  ) => boolean;
  readonly insertArtifact: (artifactId: string, position?: DraftInsertPosition | null) => boolean;
  readonly addWholeArtifact: (artifactId: string, position?: DraftInsertPosition | null) => boolean;
  readonly duplicateBlock: (blockId: string) => void;
  readonly deleteBlock: (blockId: string) => void;
  readonly fitHydratedArtifactViews: (
    artifacts?: Readonly<Record<string, DraftArtifactData | undefined>>,
  ) => boolean;
  readonly changeOrientation: (orientation: ReportOrientation) => boolean;
  readonly changeCurrencyDisplayUnit: (displayUnit: ReportCurrencyDisplayUnit) => void;
}

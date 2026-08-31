/** 프런트 draft의 artifact 적응·layout·영속 순수 연산 공개 표면을 제공하는 barrel 모듈이다. */
export {
  ARTIFACT_VIEW_LABELS,
  ATOMIC_ARTIFACT_VIEWS,
  DEFAULT_FRONTEND_CURRENCY_POLICY,
  artifactMetricCards,
  artifactViewTitle,
  artifactViewBlockSettings,
  availableArtifactViews,
  estimateArtifactBlockLayout,
  estimateArtifactViewBlockLayout,
  fitFrontendArtifactBlock,
  fitFrontendArtifactViewBlock,
  wholeArtifactSettings,
} from "./reportArtifactLayout.js";
/** 분석 실행을 보고서 artifact source로 바꾸는 adapter를 재노출한다. */
export {
  adaptAnalysisRunArtifact,
  analysisArtifactTitle,
  analysisRunArtifactSources,
  analysisTimeLabel,
  reportAssistantArtifactOptions,
  reportAssistantRepresentativeBlock,
} from "./reportAnalysisArtifacts.js";
/** editor 블록과 versioned 문서를 연결하는 순수 연산을 재노출한다. */
export {
  canonicalDraftBlockContent,
  deleteFrontendBlock,
  frontendBlocksToDocument,
  frontendTextBlockLayout,
  insertFrontendArtifact,
  keyboardEndDropPosition,
  moveFrontendBlock,
  orientFrontendBlocks,
  reportArtifactLibrarySources,
} from "./reportDraftOperations.js";
/** session draft snapshot 연산을 재노출한다. */
export {
  FRONTEND_REPORT_DRAFT_VERSION,
  createFrontendDraftSnapshot,
  frontendDraftStorageKey,
  loadFrontendDraft,
  saveFrontendDraft,
} from "./reportDraftStorage.js";

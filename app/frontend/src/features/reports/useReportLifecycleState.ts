/** 보고서 정의·실행·schedule·assistant·최종 asset API 수명주기를 관리하는 hook 모듈이다. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createAnalysisClient } from "../../api/analysisClient.ts";
import { createReportClient, ReportApiError } from "../../api/reportClient.ts";
import {
  seoulWallClockToIso,
  type ReportBlockRequest,
  type ReportAssistantSessionResponse,
  type ReportAssistantOperationScope,
  type ReportAssistantEvaluationResponse,
  type ReportAssistantReviewResponse,
  type ReportAssistantExternalTransferDisclosure,
  type ReportDefinitionVersion,
  type ReportOrientation,
  type ReportRun,
  type ReportScheduleResponse,
} from "../../contracts/report.ts";
import { createUuid } from "../../utils/createUuid.ts";
import { formatSeoulTime, reportApiError, reportRunStatusLabel } from "./reportPageLabels.ts";
import { isSameReportDefinition, REPORT_RUN_PAGE_SIZE, sortReportDefinitions } from "./reportLifecycleSupport.ts";
import { reportAssistantSessionMatchesDefinition } from "./reportAssistantSessionRecovery.ts";
import type {
  AssistantTrace,
  CreateDefinitionResult,
  DefinitionCollection,
  DefinitionListState,
  DefinitionStatusFilter,
  FinalAssetFormat,
  ManualRunOptions,
  ManualRunResult,
  PendingOperation,
  ScheduleCadence,
  ScheduleFormValues,
  UseReportLifecycleStateOptions,
} from "./reportLifecycleTypes.ts";
import { useFinalReportDocument } from "./useFinalReportDocument.ts";

const EXTERNAL_TRANSFER_ACTION_CANCELLED = Symbol("external-transfer-action-cancelled");

type AssistantExternalTransferAcceptanceAttempt = {
  readonly disclosureId: string;
  readonly generation: number;
};

/** 비동기 동의 응답이 현재 화면의 같은 공개문과 Assistant 세대에 결속됐는지 확인한다. */
export function matchesAssistantExternalTransferAcceptance(
  disclosure: Pick<ReportAssistantExternalTransferDisclosure, "disclosure_id"> | null,
  generation: number,
  attempt: AssistantExternalTransferAcceptanceAttempt,
): boolean {
  return disclosure?.disclosure_id === attempt.disclosureId
    && generation === attempt.generation;
}

/** 세션의 transient 결과 Artifact를 제외한 원래 근거 선택이 현재 선택과 같은지 검증한다. */
export function matchesAssistantArtifactSelection(
  session: Pick<ReportAssistantSessionResponse, "artifact_ids" | "result_artifact_id">,
  artifactIds: readonly string[],
): boolean {
  const resultArtifactId = session.result_artifact_id;
  if (resultArtifactId !== null && session.artifact_ids.at(-1) !== resultArtifactId) {
    return false;
  }
  const boundArtifactIds = resultArtifactId === null
    ? session.artifact_ids
    : session.artifact_ids.slice(0, -1);
  return boundArtifactIds.length === artifactIds.length
    && boundArtifactIds.every((artifactId, index) => artifactId === artifactIds[index]);
}

/** 정의·실행·schedule·최종문서 API 상태를 operation ID로 직렬화하고 안정된 명령을 반환한다. */
export function useReportLifecycleState(options: UseReportLifecycleStateOptions = {}) {
  const reportClient = useMemo(
    () => options.reportClient ?? createReportClient(undefined, fetch),
    [options.reportClient],
  );
  const analysisClient = useMemo(
    () => options.analysisClient ?? createAnalysisClient(fetch),
    [options.analysisClient],
  );
  const isAdmin = options.isAdmin ?? options.role === "admin";
  const autoLoad = options.autoLoad ?? true;

  const [definitions, setDefinitions] = useState<readonly ReportDefinitionVersion[]>([]);
  const [definitionState, setDefinitionState] = useState<DefinitionListState>("loading");
  const [selectedDefinition, setSelectedDefinition] = useState<ReportDefinitionVersion | null>(null);
  const [pendingOperations, setPendingOperations] = useState<readonly PendingOperation[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<DefinitionStatusFilter>("all");
  const [definitionCollection, setDefinitionCollectionState] = useState<DefinitionCollection>("active");
  const [createOpen, setCreateOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");

  const [runs, setRuns] = useState<readonly ReportRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<ReportRun | null>(null);
  const [runQuery, setRunQueryValue] = useState("");
  const [visibleRunCount, setVisibleRunCount] = useState(REPORT_RUN_PAGE_SIZE);
  const setRunQuery = useCallback((value: string) => { setRunQueryValue(value); setVisibleRunCount(REPORT_RUN_PAGE_SIZE); }, []);
  const [schedules, setSchedules] = useState<readonly ReportScheduleResponse[]>([]);
  const [cadence, setCadence] = useState<ScheduleCadence>("daily");
  const [scheduleAt, setScheduleAt] = useState("");
  const [assistantInstruction, setAssistantInstruction] = useState("");
  const [assistantTrace, setAssistantTrace] = useState<AssistantTrace | null>(null);
  const [assistantSession, setAssistantSession] = useState<ReportAssistantSessionResponse | null>(null);
  const [assistantEvaluation, setAssistantEvaluation] = useState<ReportAssistantEvaluationResponse | null>(null);
  const [assistantReview, setAssistantReview] = useState<ReportAssistantReviewResponse | null>(null);
  const [assistantActionError, setAssistantActionError] = useState("");
  const [assistantActionPageCounts, setAssistantActionPageCounts] = useState<{
    readonly exactPageCount: number;
    readonly verifiedPageCount: number;
  } | null>(null);
  const [assistantExternalTransferDisclosure, setAssistantExternalTransferDisclosure] = useState<ReportAssistantExternalTransferDisclosure | null>(null);
  const [assistantExternalTransferConsentPending, setAssistantExternalTransferConsentPending] = useState(false);
  const [assistantSuggestionSet, setAssistantSuggestionSet] = useState<{
    readonly selectedBlockId: string | null;
    readonly suggestions: readonly string[];
  } | null>(null);

  const definitionsRef = useRef(definitions);
  const definitionCollectionRef = useRef<DefinitionCollection>(definitionCollection);
  const definitionsRequestRef = useRef(0);
  const selectedDefinitionRef = useRef(selectedDefinition);
  const assistantSessionRef = useRef(assistantSession);
  const assistantRequestRef = useRef(0);
  const assistantExternalTransferPendingRef = useRef<{
    readonly assistantRequestId: string;
    readonly disclosureId: string;
    readonly generation: number;
    readonly resume: () => void;
    readonly resolveCancelled: () => void;
  } | null>(null);
  const assistantExternalTransferDisclosureRef = useRef<ReportAssistantExternalTransferDisclosure | null>(null);
  const assistantExternalTransferAcceptingRef = useRef<AssistantExternalTransferAcceptanceAttempt | null>(null);
  const runsRequestRef = useRef("");
  definitionsRef.current = definitions;
  definitionCollectionRef.current = definitionCollection;
  selectedDefinitionRef.current = selectedDefinition;
  assistantSessionRef.current = assistantSession;

  const beginOperation = useCallback((name: string, resetFeedback = true) => {
    const operation = { id: createUuid(), name };
    setPendingOperations((current) => [...current, operation]);
    if (resetFeedback) {
      setError("");
      setNotice("");
    }
    return operation.id;
  }, []);

  const endOperation = useCallback((id: string) => {
    setPendingOperations((current) => current.filter((operation) => operation.id !== id));
  }, []);

  const mutate = useCallback(async <T,>(
    name: string,
    action: () => Promise<T> | T,
    isCurrent: () => boolean = () => true,
  ): Promise<T | null> => {
    const operationId = beginOperation(name);
    try {
      return await action();
    } catch (nextError) {
      if (isCurrent()) {
        setError(reportApiError(nextError));
        if (name === "assistant-patch-approval" && nextError instanceof ReportApiError) {
          setAssistantActionError(nextError.code);
          setAssistantActionPageCounts(
            Number.isSafeInteger(nextError.exactPageCount)
              && Number.isSafeInteger(nextError.verifiedPageCount)
              ? {
                  exactPageCount: nextError.exactPageCount as number,
                  verifiedPageCount: nextError.verifiedPageCount as number,
                }
              : null,
          );
        }
      }
      return null;
    } finally {
      endOperation(operationId);
    }
  }, [beginOperation, endOperation]);

  const installAssistantExternalTransferDisclosure = useCallback((
    disclosure: ReportAssistantExternalTransferDisclosure | null,
  ) => {
    assistantExternalTransferDisclosureRef.current = disclosure;
    setAssistantExternalTransferDisclosure(disclosure);
  }, []);

  /** 428 공개문에 결속한 동일 API action을 메모리에 보관하고 명시적 동의 뒤 한 번만 재개한다. */
  const runWithExternalTransferConsent = useCallback(async <T,>(
    assistantRequestId: string,
    generation: number,
    action: () => Promise<T>,
  ): Promise<T | typeof EXTERNAL_TRANSFER_ACTION_CANCELLED> => {
    try {
      return await action();
    } catch (nextError) {
      if (!(nextError instanceof ReportApiError)
        || nextError.status !== 428
        || nextError.code !== "EXTERNAL_TRANSFER_CONSENT_REQUIRED") {
        throw nextError;
      }
      const disclosure = nextError.externalTransferDisclosure
        ?? await reportClient.getAssistantExternalTransferDisclosure(
          nextError.assistantRequestId || assistantRequestId,
        );
      if (disclosure.assistant_request_id !== assistantRequestId) {
        throw new Error("외부 전송 공개문이 현재 Report Assistant 세션과 일치하지 않습니다.");
      }
      if (assistantRequestRef.current !== generation) return EXTERNAL_TRANSFER_ACTION_CANCELLED;
      assistantExternalTransferPendingRef.current?.resolveCancelled();
      return await new Promise<T | typeof EXTERNAL_TRANSFER_ACTION_CANCELLED>((resolve, reject) => {
        const pending = {
          assistantRequestId,
          disclosureId: disclosure.disclosure_id,
          generation,
          resolveCancelled: () => resolve(EXTERNAL_TRANSFER_ACTION_CANCELLED),
          resume: () => { void action().then(resolve, reject); },
        };
        assistantExternalTransferPendingRef.current = pending;
        setAssistantExternalTransferConsentPending(false);
        installAssistantExternalTransferDisclosure(disclosure);
        setError("");
        setNotice("");
      });
    }
  }, [installAssistantExternalTransferDisclosure, reportClient]);

  const clearAssistantExternalTransferConsent = useCallback(() => {
    const pending = assistantExternalTransferPendingRef.current;
    assistantExternalTransferPendingRef.current = null;
    assistantExternalTransferAcceptingRef.current = null;
    setAssistantExternalTransferConsentPending(false);
    installAssistantExternalTransferDisclosure(null);
    pending?.resolveCancelled();
  }, [installAssistantExternalTransferDisclosure]);

  const recoverAssistantExternalTransferDisclosure = useCallback(async (
    assistantRequestId: string,
    generation: number,
    expectedCurrentDisclosureId?: string | null,
  ) => {
    const isCurrentRecovery = () => assistantRequestRef.current === generation
      && (expectedCurrentDisclosureId === undefined
        || (assistantExternalTransferDisclosureRef.current?.disclosure_id ?? null) === expectedCurrentDisclosureId);
    try {
      const disclosure = await reportClient.getAssistantExternalTransferDisclosure(assistantRequestId);
      if (!isCurrentRecovery()) return null;
      installAssistantExternalTransferDisclosure(disclosure);
      return disclosure;
    } catch (nextError) {
      if (nextError instanceof ReportApiError && nextError.status === 404) return null;
      if (isCurrentRecovery()) setError(reportApiError(nextError));
      return null;
    }
  }, [installAssistantExternalTransferDisclosure, reportClient]);

  const declineAssistantExternalTransferConsent = useCallback(() => {
    clearAssistantExternalTransferConsent();
    setNotice("외부 모델 전송에 동의하지 않아 요청을 실행하지 않았습니다.");
  }, [clearAssistantExternalTransferConsent]);

  const acceptAssistantExternalTransferConsent = useCallback(async () => {
    const disclosure = assistantExternalTransferDisclosure;
    if (!disclosure) return null;
    const pendingAction = assistantExternalTransferPendingRef.current;
    const acceptanceAttempt = {
      disclosureId: disclosure.disclosure_id,
      generation: pendingAction?.generation ?? assistantRequestRef.current,
    };
    if (!matchesAssistantExternalTransferAcceptance(
      assistantExternalTransferDisclosureRef.current,
      assistantRequestRef.current,
      acceptanceAttempt,
    )) return null;
    if (pendingAction && (
      pendingAction.assistantRequestId !== disclosure.assistant_request_id
      || pendingAction.disclosureId !== disclosure.disclosure_id
      || pendingAction.generation !== acceptanceAttempt.generation
    )) return null;
    if (assistantExternalTransferAcceptingRef.current
      && matchesAssistantExternalTransferAcceptance(
        assistantExternalTransferDisclosureRef.current,
        assistantRequestRef.current,
        assistantExternalTransferAcceptingRef.current,
      )) return null;
    assistantExternalTransferAcceptingRef.current = acceptanceAttempt;
    setAssistantExternalTransferConsentPending(true);
    let staleDisclosureResponse = false;
    const isCurrentAcceptance = () => matchesAssistantExternalTransferAcceptance(
      assistantExternalTransferDisclosureRef.current,
      assistantRequestRef.current,
      acceptanceAttempt,
    );
    const receipt = await mutate(
      "assistant-external-consent",
      async () => {
        try {
          return await reportClient.acceptAssistantExternalTransferConsent(
            disclosure.assistant_request_id,
            disclosure.disclosure_id,
            disclosure.disclosure_hash,
          );
        } catch (nextError) {
          if (nextError instanceof ReportApiError && [404, 409].includes(nextError.status)) {
            staleDisclosureResponse = true;
            return null;
          }
          throw nextError;
        }
      },
      isCurrentAcceptance,
    );
    if (assistantExternalTransferAcceptingRef.current === acceptanceAttempt) {
      assistantExternalTransferAcceptingRef.current = null;
    }
    if (!isCurrentAcceptance()) return receipt;
    setAssistantExternalTransferConsentPending(false);
    if (staleDisclosureResponse) {
      if (assistantExternalTransferPendingRef.current === pendingAction && pendingAction) {
        assistantExternalTransferPendingRef.current = null;
        pendingAction.resolveCancelled();
      }
      installAssistantExternalTransferDisclosure(null);
      setNotice("동의 정보가 변경되어 최신 공개문을 다시 확인합니다.");
      const latestDisclosure = await recoverAssistantExternalTransferDisclosure(
        disclosure.assistant_request_id,
        acceptanceAttempt.generation,
        null,
      );
      if (!latestDisclosure
        && assistantRequestRef.current === acceptanceAttempt.generation
        && assistantExternalTransferDisclosureRef.current === null) {
        setNotice("동의 정보가 만료되어 요청을 취소했습니다. 요청을 다시 실행해 주세요.");
      }
      return null;
    }
    if (!receipt) return null;
    if (assistantExternalTransferPendingRef.current === pendingAction && pendingAction) {
      assistantExternalTransferPendingRef.current = null;
      installAssistantExternalTransferDisclosure(null);
      pendingAction.resume();
    } else {
      installAssistantExternalTransferDisclosure(null);
      setNotice("외부 모델 전송 동의를 저장했습니다. 요청을 다시 실행해 주세요.");
    }
    return receipt;
  }, [
    assistantExternalTransferDisclosure,
    installAssistantExternalTransferDisclosure,
    mutate,
    recoverAssistantExternalTransferDisclosure,
    reportClient,
  ]);

  const {
    finalDocument,
    finalDocumentState,
    loadFinalDocument: loadFinalDocumentRequest,
  } = useFinalReportDocument({ beginOperation, endOperation, reportClient, setError });
  const loadFinalDocument = useCallback((
    definition: ReportDefinitionVersion | null = selectedDefinitionRef.current,
  ) => loadFinalDocumentRequest(definition), [loadFinalDocumentRequest]);

  const clearFeedback = useCallback(() => {
    setError("");
    setNotice("");
  }, []);
  const clearAssistantTrace = useCallback(() => {
    assistantRequestRef.current += 1;
    clearAssistantExternalTransferConsent();
    assistantSessionRef.current = null;
    setAssistantTrace(null);
    setAssistantSession(null);
    setAssistantEvaluation(null);
    setAssistantReview(null);
    setAssistantSuggestionSet(null);
    setAssistantActionError("");
    setAssistantInstruction("");
  }, [clearAssistantExternalTransferConsent]);
  useEffect(() => () => {
    assistantExternalTransferPendingRef.current?.resolveCancelled();
    assistantExternalTransferPendingRef.current = null;
  }, []);
  useEffect(() => {
    if (!assistantActionError) setAssistantActionPageCounts(null);
  }, [assistantActionError]);
  const ensureAssistantEditable = useCallback(() => {
    if (!selectedDefinitionRef.current?.archivedAt) return true;
    setError("삭제된 보고서에서는 AI 도우미를 사용할 수 없습니다. 먼저 보고서를 복원해 주세요.");
    return false;
  }, []);

  const selectDefinition = useCallback((definition: ReportDefinitionVersion | null) => {
    setSelectedDefinition(definition);
    setAssistantReview(null);
    setAssistantSuggestionSet(null);
  }, []);

  const upsertDefinition = useCallback((definition: ReportDefinitionVersion) => {
    setDefinitions((current) => sortReportDefinitions([
      definition,
      ...current.filter((item) => !isSameReportDefinition(item, definition)),
    ]));
    setSelectedDefinition(definition);
    setAssistantReview(null);
    setAssistantSuggestionSet(null);
    return definition;
  }, []);

  const loadDefinitionsFor = useCallback(async (collection: DefinitionCollection) => {
    const request = definitionsRequestRef.current + 1;
    definitionsRequestRef.current = request;
    definitionCollectionRef.current = collection;
    setDefinitionCollectionState(collection);
    if (collection === "archived") setCreateOpen(false);
    setDefinitionState("loading");
    const items = await mutate(
      "definitions",
      () => reportClient.listDefinitions(collection === "archived"),
      () => definitionsRequestRef.current === request,
    );
    if (definitionsRequestRef.current !== request) return null;
    if (items === null) {
      setDefinitionState("error");
      return null;
    }
    const next = sortReportDefinitions(items);
    definitionsRef.current = next;
    setDefinitions(next);
    setSelectedDefinition((current) => (
      current ? next.find((item) => isSameReportDefinition(item, current)) ?? null : current
    ));
    setDefinitionState(next.length ? "ready" : "empty");
    return next;
  }, [mutate, reportClient]);

  const loadDefinitions = useCallback(
    () => loadDefinitionsFor(definitionCollectionRef.current),
    [loadDefinitionsFor],
  );

  const setDefinitionCollection = useCallback((collection: DefinitionCollection) => {
    if (collection !== "active" && collection !== "archived") return Promise.resolve(null);
    if (collection === definitionCollectionRef.current && definitionState !== "error") {
      return Promise.resolve(definitionsRef.current);
    }
    clearFeedback();
    setSelectedDefinition(null);
    clearAssistantTrace();
    return loadDefinitionsFor(collection);
  }, [clearAssistantTrace, clearFeedback, definitionState, loadDefinitionsFor]);

  const archiveDefinition = useCallback(async (definitionId: string) => {
    const archived = await mutate(
      `archive:${definitionId}`,
      () => reportClient.archiveDefinition(definitionId),
    );
    if (!archived) return null;
    const next = definitionsRef.current.filter((item) => item.definitionId !== definitionId);
    definitionsRef.current = next;
    setDefinitions(next);
    setDefinitionState(next.length ? "ready" : "empty");
    setSelectedDefinition((current) => current?.definitionId === definitionId ? null : current);
    setNotice("보고서를 삭제했습니다. 휴지통에서 확인하거나 복원할 수 있습니다.");
    return archived;
  }, [mutate, reportClient]);

  const restoreDefinition = useCallback(async (definitionId: string) => {
    const restored = await mutate(
      `restore:${definitionId}`,
      () => reportClient.restoreDefinition(definitionId),
    );
    if (!restored) return null;
    const next = definitionsRef.current.filter((item) => item.definitionId !== definitionId);
    definitionsRef.current = next;
    setDefinitions(next);
    setDefinitionState(next.length ? "ready" : "empty");
    setSelectedDefinition((current) => current?.definitionId === definitionId ? null : current);
    setNotice("보고서를 복원했습니다. 활성 보고서에서 다시 편집할 수 있습니다.");
    return restored;
  }, [mutate, reportClient]);

  const fetchDefinition = useCallback((definition: Pick<ReportDefinitionVersion, "definitionId" | "version">) => (
    mutate("definition", () => reportClient.getDefinition(definition.definitionId, definition.version))
  ), [mutate, reportClient]);

  const findLatestDraft = useCallback((definitionId: string) => (
    definitionsRef.current
      .filter((item) => item.definitionId === definitionId && item.status === "draft")
      .sort((left, right) => right.version - left.version)[0] ?? null
  ), []);

  const createDefinition = useCallback(async (): Promise<CreateDefinitionResult | null> => {
    const title = newTitle.trim();
    if (!title) {
      setError("보고서 제목을 입력해 주세요.");
      return null;
    }
    const initialContent = newContent.trim();
    const blocks: ReportBlockRequest[] = initialContent ? [{
      block_id: createUuid(),
      title: "운영 요약",
      columns: 12,
      type: "text",
      x: 0,
      y: 0,
      w: 12,
      h: 4,
      content: initialContent,
    }] : [];
    const definition = await mutate("create", () => reportClient.createDefinition({
      definition_id: createUuid(),
      title,
      blocks,
    }));
    if (!definition) return null;
    upsertDefinition(definition);
    setDefinitionState("ready");
    setCreateOpen(false);
    setNewTitle("");
    setNewContent("");
    clearAssistantTrace();
    return { definition, initialContent };
  }, [clearAssistantTrace, mutate, newContent, newTitle, reportClient, upsertDefinition]);

  const createNextDraft = useCallback(async (definition: ReportDefinitionVersion) => {
    if (definition.archivedAt) {
      setError("삭제된 보고서는 복원한 뒤 새 버전을 만들 수 있습니다.");
      return null;
    }
    if (definition.status !== "approved") return definition;
    const draft = await mutate("next-draft", () => reportClient.createNextDraft(
      definition.definitionId,
      definition.version,
    ));
    if (!draft) return null;
    upsertDefinition(draft);
    setNotice(`버전 ${draft.version} 초안을 만들었습니다.`);
    return draft;
  }, [mutate, reportClient, upsertDefinition]);

  const approveDefinition = useCallback(async (
    definition: ReportDefinitionVersion,
    input: {
      approvedAt?: string;
      orientation?: ReportOrientation;
      blocks?: ReportDefinitionVersion["blocks"];
    } = {},
  ) => {
    if (definition.archivedAt) {
      setError("삭제된 보고서는 복원한 뒤 확정할 수 있습니다.");
      return null;
    }
    if (definition.status !== "draft") return null;
    const approved = await mutate("approve", () => reportClient.approveDefinition(
      definition.definitionId,
      definition.version,
      input.approvedAt ?? new Date().toISOString(),
      input.orientation,
    ));
    if (!approved) return null;
    const finalized = input.blocks ? { ...approved, blocks: [...input.blocks] } : approved;
    upsertDefinition(finalized);
    setNotice("수정할 수 없는 보고서 확정본을 생성했습니다.");
    return finalized;
  }, [mutate, reportClient, upsertDefinition]);

  const openFinalAsset = useCallback(async (
    format: FinalAssetFormat,
    download = false,
    definition: ReportDefinitionVersion | null = selectedDefinitionRef.current,
  ): Promise<boolean> => {
    if (!definition || definition.status !== "approved") return false;
    const popup = download ? null : window.open("", "_blank");
    if (!download && !popup) {
      setError("팝업이 차단되었습니다. 팝업을 허용하거나 다운로드를 이용해 주세요.");
      return false;
    }
    if (popup) popup.opener = null;
    const operationId = beginOperation(`${format}-${download ? "download" : "open"}`);
    try {
      const body = format === "pdf"
        ? await reportClient.getFinalPdf(definition.definitionId, definition.version)
        : await reportClient.getFinalHtml(definition.definitionId, definition.version);
      const blob = body instanceof Blob ? body : new Blob([body], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      if (download) {
        const link = document.createElement("a");
        link.href = url;
        link.download = `report-v${definition.version}.${format}`;
        document.body.append(link);
        link.click();
        link.remove();
      } else if (popup) {
        popup.location.href = url;
      }
      window.setTimeout(() => URL.revokeObjectURL(url), download ? 1000 : 60000);
      setNotice(download ? "보고서 확정본을 다운로드했습니다." : "보고서 확정본을 새 창에서 열었습니다.");
      return true;
    } catch (nextError) {
      popup?.close();
      setError(reportApiError(nextError));
      return false;
    } finally {
      endOperation(operationId);
    }
  }, [beginOperation, endOperation, reportClient]);

  const loadRuns = useCallback(async (
    definition: ReportDefinitionVersion | null = selectedDefinitionRef.current,
  ) => {
    if (!definition) return null;
    const requestId = createUuid();
    runsRequestRef.current = requestId;
    const items = await mutate("runs", () => reportClient.listRuns(definition.definitionId));
    if (items === null || runsRequestRef.current !== requestId) return items;
    setRuns([...items]);
    setVisibleRunCount(REPORT_RUN_PAGE_SIZE);
    setSelectedRun(items[0] ?? null);
    return items;
  }, [mutate, reportClient]);

  const runDefinition = useCallback(async (
    definition: ReportDefinitionVersion | null = selectedDefinitionRef.current,
    runOptions: ManualRunOptions = {},
  ): Promise<ManualRunResult | null> => {
    if (definition?.archivedAt) {
      setError("삭제된 보고서는 실행할 수 없습니다. 먼저 복원해 주세요.");
      return null;
    }
    if (!definition || definition.status !== "approved") return null;
    const receipt = await mutate("run", () => reportClient.createManualRun({
      definition_id: definition.definitionId,
      version: definition.version,
      idempotency_key: runOptions.idempotencyKey ?? createUuid(),
    }));
    if (!receipt) return null;
    const run = receipt.run_id
      ? await mutate("run-detail", () => reportClient.getRun(receipt.run_id as string))
      : null;
    if (run) {
      setSelectedRun(run);
      setRuns((current) => [run, ...current.filter((item) => item.runId !== run.runId)]);
    }
    setNotice(`최신 데이터로 보고서를 다시 생성하도록 요청했습니다. · ${reportRunStatusLabel(receipt.status)}`);
    return { receipt, run };
  }, [mutate, reportClient]);

  const loadSchedules = useCallback(async () => {
    const items = await mutate("schedules", () => reportClient.listSchedules());
    if (items !== null) setSchedules([...items]);
    return items;
  }, [mutate, reportClient]);

  const createSchedule = useCallback(async (
    definition: ReportDefinitionVersion | null = selectedDefinitionRef.current,
    override: Partial<ScheduleFormValues> = {},
  ) => {
    const values = { cadence, scheduleAt, ...override };
    if (definition?.archivedAt) {
      setError("삭제된 보고서에는 예약을 만들 수 없습니다. 먼저 복원해 주세요.");
      return null;
    }
    if (!definition || definition.status !== "approved" || !values.scheduleAt) return null;
    const schedule = await mutate("schedule-create", () => reportClient.createSchedule({
      schedule_id: createUuid(),
      definition_id: definition.definitionId,
      version: definition.version,
      cadence: values.cadence,
      next_run_at: seoulWallClockToIso(values.scheduleAt),
      timezone: "Asia/Seoul",
    }));
    if (!schedule) return null;
    setSchedules((current) => [...current, schedule]);
    setNotice("서울 시간 기준 예약을 만들었습니다.");
    return schedule;
  }, [cadence, mutate, reportClient, scheduleAt]);

  const setScheduleEnabled = useCallback(async (scheduleId: string, enabled: boolean) => {
    const schedule = await mutate(
      "schedule-update",
      () => reportClient.setScheduleEnabled(scheduleId, enabled),
    );
    if (!schedule) return null;
    setSchedules((current) => current.map((item) => (
      item.schedule_id === scheduleId ? schedule : item
    )));
    setNotice(schedule.enabled ? "예약 실행을 재개했습니다." : "예약 실행을 중지했습니다.");
    return schedule;
  }, [mutate, reportClient]);

  const submitAssistantInstruction = useCallback(async (
    definition: ReportDefinitionVersion,
    artifactId: string,
    instruction: string,
    artifactIds: readonly string[] = [artifactId],
    selectedBlockId: string | null = null,
    operationScope: ReportAssistantOperationScope = "full_report",
  ) => {
    const normalized = instruction.trim();
    if (definition.archivedAt) {
      setError("삭제된 보고서에서는 AI 도우미를 사용할 수 없습니다. 먼저 복원해 주세요.");
      return null;
    }
    if (!artifactId || !normalized || definition.status !== "draft") return null;
    setAssistantActionError("");
    const request = ++assistantRequestRef.current;
    setAssistantSuggestionSet(null);
    let session = assistantSessionRef.current;
    if (
      !session
      || session.definition_id !== definition.definitionId
      || session.definition_version !== definition.version
      || session.artifact_id !== artifactId
      || !matchesAssistantArtifactSelection(session, artifactIds)
      || ["completed", "failed", "cancelled"].includes(session.phase)
    ) {
      session = await mutate("assistant", () => reportClient.createAssistantSession(
        definition.definitionId,
        definition.version,
        artifactId,
        artifactIds.slice(1),
      ), () => assistantRequestRef.current === request);
      if (!session || assistantRequestRef.current !== request) return null;
      setAssistantSession(session);
    }
    const proposal = await mutate("assistant", () => runWithExternalTransferConsent(
      session.assistant_request_id,
      request,
      () => reportClient.submitAssistantMessage(
        session.assistant_request_id,
        normalized,
        session.phase === "waiting_patch_approval" ? session.patch_request_id : null,
        selectedBlockId,
        operationScope,
      ),
    ), () => assistantRequestRef.current === request);
    if (assistantRequestRef.current !== request) return null;
    if (proposal === EXTERNAL_TRANSFER_ACTION_CANCELLED) return {
      status: "external_transfer_declined",
      message: "외부 모델 전송에 동의하지 않아 요청을 실행하지 않았습니다.",
      session: null,
      definition: null,
    };
    if (!proposal) {
      const recovered = await mutate(
        "assistant-recover",
        () => reportClient.getAssistantSession(session.assistant_request_id),
        () => assistantRequestRef.current === request,
      );
      if (recovered && assistantRequestRef.current === request) setAssistantSession(recovered);
      return null;
    }
    setAssistantSession(proposal.session);
    setAssistantReview(null);
    setAssistantSuggestionSet({ selectedBlockId, suggestions: proposal.suggestions });
    setAssistantInstruction("");
    setNotice(proposal.change_kind === "new_data"
      ? "새 데이터 분석 계획을 검토한 뒤 승인해 주세요."
      : proposal.change_kind === "existing_artifact"
        ? "변경안을 검토한 뒤 적용하거나 취소해 주세요."
        : proposal.message);
    return {
      status: proposal.change_kind === "new_data"
        ? "approval_required"
        : proposal.change_kind === "existing_artifact"
          ? "patch_approval_required"
        : proposal.change_kind === "clarification"
          ? "clarification_required"
          : "clarification_required",
      message: proposal.message,
      session: proposal.session,
      definition: null,
    };
  }, [mutate, reportClient, runWithExternalTransferConsent, upsertDefinition]);

  const reviewAssistantReport = useCallback(async (
    definition: ReportDefinitionVersion,
    artifactId: string,
    artifactIds: readonly string[] = [artifactId],
    selectedBlockId: string | null = null,
  ) => {
    if (definition.archivedAt) {
      setError("삭제된 보고서에서는 AI 품질 검토를 실행할 수 없습니다. 먼저 복원해 주세요.");
      return null;
    }
    if (!artifactId || definition.status !== "draft") return null;
    const request = ++assistantRequestRef.current;
    setAssistantSuggestionSet(null);
    let session = assistantSessionRef.current;
    if (
      !session
      || session.definition_id !== definition.definitionId
      || session.definition_version !== definition.version
      || session.artifact_id !== artifactId
      || !matchesAssistantArtifactSelection(session, artifactIds)
      || ["completed", "failed", "cancelled"].includes(session.phase)
    ) {
      session = await mutate("assistant-review", () => reportClient.createAssistantSession(
        definition.definitionId,
        definition.version,
        artifactId,
        artifactIds.slice(1),
      ), () => assistantRequestRef.current === request);
      if (!session || assistantRequestRef.current !== request) return null;
      setAssistantSession(session);
    }
    if (session.phase !== "ready") return null;
    const review = await mutate(
      "assistant-review",
      () => runWithExternalTransferConsent(
        session.assistant_request_id,
        request,
        () => reportClient.reviewAssistantSession(session.assistant_request_id, selectedBlockId),
      ),
      () => assistantRequestRef.current === request,
    );
    if (review === EXTERNAL_TRANSFER_ACTION_CANCELLED) return null;
    if (!review || assistantRequestRef.current !== request) return null;
    setAssistantReview(review);
    setAssistantSuggestionSet({ selectedBlockId, suggestions: review.suggestions });
    setNotice(review.findings.length
      ? "AI 품질 검토를 마쳤습니다. 원하는 항목을 선택해 수정 지시를 확인해 주세요."
      : "AI 품질 검토에서 지원되는 문제를 찾지 못했습니다.");
    return review;
  }, [mutate, reportClient, runWithExternalTransferConsent]);

  const restoreAssistantSession = useCallback(async (
    assistantRequestId: string,
    definition: Pick<ReportDefinitionVersion, "definitionId" | "version">,
  ) => {
    if (!ensureAssistantEditable()) return null;
    setAssistantActionError("");
    const request = ++assistantRequestRef.current;
    const session = await mutate(
      "assistant-recover",
      () => reportClient.getAssistantSession(assistantRequestId),
      () => assistantRequestRef.current === request,
    );
    if (
      !session
      || assistantRequestRef.current !== request
      || !reportAssistantSessionMatchesDefinition(session, definition)
    ) return null;
    setAssistantSession(session);
    setAssistantSuggestionSet(null);
    if (!["completed", "failed", "cancelled"].includes(session.phase)) {
      await recoverAssistantExternalTransferDisclosure(session.assistant_request_id, request);
    }
    return session;
  }, [ensureAssistantEditable, mutate, recoverAssistantExternalTransferDisclosure, reportClient]);

  const retryAssistantSession = useCallback(async () => {
    if (!ensureAssistantEditable()) return null;
    const current = assistantSessionRef.current;
    if (!current?.retryable || current.phase !== "failed") return null;
    setAssistantActionError("");
    const request = ++assistantRequestRef.current;
    const session = await mutate(
      "assistant-retry",
      () => runWithExternalTransferConsent(
        current.assistant_request_id,
        request,
        () => reportClient.retryAssistantSession(current.assistant_request_id),
      ),
      () => assistantRequestRef.current === request,
    );
    if (session === EXTERNAL_TRANSFER_ACTION_CANCELLED) return null;
    if (!session || assistantRequestRef.current !== request) return null;
    setAssistantSession(session);
    setAssistantEvaluation(null);
    setAssistantReview(null);
    setAssistantSuggestionSet(null);
    setAssistantInstruction("");
    setNotice("새 작성 세션을 열었습니다. 요청을 다시 입력해 주세요.");
    return session;
  }, [ensureAssistantEditable, mutate, reportClient, runWithExternalTransferConsent]);

  const cancelAssistantSession = useCallback(async () => {
    if (!ensureAssistantEditable()) return null;
    const current = assistantSessionRef.current;
    if (!current || !["ready", "waiting_patch_approval", "waiting_approval"].includes(current.phase)) {
      return null;
    }
    setAssistantActionError("");
    const request = ++assistantRequestRef.current;
    const session = await mutate(
      "assistant-cancel",
      () => reportClient.cancelAssistantSession(current.assistant_request_id),
      () => assistantRequestRef.current === request,
    );
    if (!session || assistantRequestRef.current !== request) return null;
    setAssistantSession(session);
    setAssistantReview(null);
    setAssistantSuggestionSet(null);
    setNotice("Report Assistant 요청을 취소했습니다. 보고서는 변경되지 않았습니다.");
    return session;
  }, [ensureAssistantEditable, mutate, reportClient]);

  const approveAssistantRequest = useCallback(async () => {
    if (!ensureAssistantEditable()) return null;
    const current = assistantSessionRef.current;
    const requestId = current?.analysis_plan?.request_id;
    if (!current || !requestId) return null;
    setAssistantActionError("");
    const request = ++assistantRequestRef.current;
    const session = await mutate("assistant-approval", () => runWithExternalTransferConsent(
      current.assistant_request_id,
      request,
      () => reportClient.approveAssistantPlan(
        current.assistant_request_id,
        requestId,
      ),
    ), () => assistantRequestRef.current === request);
    if (session === EXTERNAL_TRANSFER_ACTION_CANCELLED) return null;
    if (!session || assistantRequestRef.current !== request) return null;
    setAssistantSession(session);
    setAssistantSuggestionSet(null);
    setNotice("새 분석 결과를 반영한 변경안을 준비했습니다. 적용할 내용을 검토해 주세요.");
    return { session, definition: null };
  }, [ensureAssistantEditable, mutate, reportClient, runWithExternalTransferConsent]);

  const rejectAssistantRequest = useCallback(async () => {
    if (!ensureAssistantEditable()) return null;
    const current = assistantSessionRef.current;
    const requestId = current?.analysis_plan?.request_id;
    if (!current || !requestId) return null;
    setAssistantActionError("");
    const request = ++assistantRequestRef.current;
    const session = await mutate("assistant-rejection", () => reportClient.rejectAssistantPlan(
      current.assistant_request_id,
      requestId,
    ), () => assistantRequestRef.current === request);
    if (!session || assistantRequestRef.current !== request) return null;
    setAssistantSession(session);
    setAssistantSuggestionSet(null);
    setNotice("새 데이터 분석 계획을 거절했습니다.");
    return session;
  }, [ensureAssistantEditable, mutate, reportClient]);

  const approveAssistantPatch = useCallback(async (operationIndexes?: readonly number[]) => {
    if (!ensureAssistantEditable()) return null;
    const current = assistantSessionRef.current;
    const requestId = current?.patch_request_id;
    if (!current || !requestId) return null;
    setAssistantActionError("");
    const request = ++assistantRequestRef.current;
    const session = await mutate("assistant-patch-approval", () => reportClient.approveAssistantPatch(
      current.assistant_request_id,
      requestId,
      operationIndexes,
    ), () => assistantRequestRef.current === request);
    if (!session || assistantRequestRef.current !== request) return null;
    setAssistantSession(session);
    setAssistantSuggestionSet(null);
    if (session.phase !== "completed" || !session.result_revision) return { session, definition: null };
    const definition = await mutate("assistant-revision", () => reportClient.getDefinition(
      session.definition_id,
      session.result_revision as number,
    ), () => assistantRequestRef.current === request);
    if (!definition || assistantRequestRef.current !== request) return { session, definition: null };
    upsertDefinition(definition);
    setNotice(`검토한 변경안을 버전 ${definition.version} 초안으로 저장했습니다.`);
    return { session, definition };
  }, [ensureAssistantEditable, mutate, reportClient, upsertDefinition]);

  const rejectAssistantPatch = useCallback(async () => {
    if (!ensureAssistantEditable()) return null;
    const current = assistantSessionRef.current;
    const requestId = current?.patch_request_id;
    if (!current || !requestId) return null;
    setAssistantActionError("");
    const request = ++assistantRequestRef.current;
    const session = await mutate("assistant-patch-rejection", () => reportClient.rejectAssistantPatch(
      current.assistant_request_id,
      requestId,
    ), () => assistantRequestRef.current === request);
    if (!session || assistantRequestRef.current !== request) return null;
    setAssistantSession(session);
    setAssistantSuggestionSet(null);
    setNotice("AI 변경안을 취소했습니다. 보고서는 변경되지 않았습니다.");
    return session;
  }, [ensureAssistantEditable, mutate, reportClient]);

  useEffect(() => {
    if (!autoLoad) return;
    void loadDefinitions();
    if (isAdmin) void loadSchedules();
  }, [autoLoad, isAdmin, loadDefinitions, loadSchedules]);

  useEffect(() => {
    const session = assistantSession;
    if (!session || !["completed", "failed", "cancelled"].includes(session.phase)) {
      setAssistantEvaluation(null);
      return undefined;
    }
    let active = true;
    void reportClient.getAssistantEvaluation(session.assistant_request_id)
      .then((evaluation) => { if (active) setAssistantEvaluation(evaluation); })
      .catch(() => { if (active) setAssistantEvaluation(null); });
    return () => { active = false; };
  }, [assistantSession, reportClient]);

  const visibleDefinitions = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ko-KR");
    return definitions.filter((definition) => (
      (statusFilter === "all" || definition.status === statusFilter)
      && (!normalized || definition.title.toLocaleLowerCase("ko-KR").includes(normalized))
    ));
  }, [definitions, query, statusFilter]);

  const filteredRuns = useMemo(() => {
    const normalized = runQuery.trim().toLocaleLowerCase("ko-KR");
    return runs.filter((run) => !normalized || [
      reportRunStatusLabel(run.status),
      `v${run.definitionVersion}`,
      formatSeoulTime(run.asOf),
      ...run.blocks.flatMap((block) => [block.failureCode, block.failureMessage]),
    ].filter(Boolean).join(" ").toLocaleLowerCase("ko-KR").includes(normalized));
  }, [runQuery, runs]);

  const visibleRuns = useMemo(
    () => filteredRuns.slice(0, visibleRunCount),
    [filteredRuns, visibleRunCount],
  );
  const selectedSchedules = useMemo(() => selectedDefinition
    ? schedules.filter((item) => (
        item.definition_id === selectedDefinition.definitionId
        && item.version === selectedDefinition.version
      ))
    : [], [schedules, selectedDefinition]);
  const pending = pendingOperations.at(-1)?.name ?? "";
  const showMoreRuns = useCallback(
    () => setVisibleRunCount((current) => current + REPORT_RUN_PAGE_SIZE),
    [],
  );

  return useMemo(() => ({
    reportClient,
    analysisClient,
    definitions,
    definitionState,
    selectedDefinition,
    visibleDefinitions,
    query,
    statusFilter,
    definitionCollection,
    createOpen,
    newTitle,
    newContent,
    pending,
    pendingOperations,
    error,
    notice,
    finalDocument,
    finalDocumentState,
    runs,
    filteredRuns,
    visibleRuns,
    visibleRunCount,
    selectedRun,
    runQuery,
    schedules,
    selectedSchedules,
    cadence,
    scheduleAt,
    assistantInstruction,
    assistantTrace,
    assistantSession,
    assistantEvaluation,
    assistantReview,
    assistantSuggestionSet,
    assistantActionError,
    assistantActionPageCounts,
    assistantExternalTransferDisclosure,
    assistantExternalTransferConsentPending,
    setQuery,
    setStatusFilter,
    setDefinitionCollection,
    setCreateOpen,
    setNewTitle,
    setNewContent,
    setError,
    setNotice,
    setRunQuery,
    setSelectedRun,
    setCadence,
    setScheduleAt,
    setAssistantInstruction,
    acceptAssistantExternalTransferConsent,
    declineAssistantExternalTransferConsent,
    clearFeedback,
    clearAssistantTrace,
    mutate,
    selectDefinition,
    upsertDefinition,
    loadDefinitions,
    archiveDefinition,
    restoreDefinition,
    fetchDefinition,
    findLatestDraft,
    createDefinition,
    createNextDraft,
    approveDefinition,
    loadFinalDocument,
    openFinalAsset,
    loadRuns,
    runDefinition,
    showMoreRuns,
    loadSchedules,
    createSchedule,
    setScheduleEnabled,
    submitAssistantInstruction,
    reviewAssistantReport,
    restoreAssistantSession,
    approveAssistantRequest,
    rejectAssistantRequest,
    approveAssistantPatch,
    rejectAssistantPatch,
    retryAssistantSession,
    cancelAssistantSession,
  }), [
    acceptAssistantExternalTransferConsent, analysisClient, approveAssistantPatch, approveAssistantRequest, approveDefinition, archiveDefinition, assistantInstruction,
    assistantActionError, assistantActionPageCounts, assistantEvaluation, assistantExternalTransferConsentPending, assistantExternalTransferDisclosure,
    assistantReview, assistantSession, assistantSuggestionSet, assistantTrace, cadence,
    clearAssistantTrace, clearFeedback, createDefinition, createNextDraft, createOpen, createSchedule,
    declineAssistantExternalTransferConsent, definitionCollection, definitionState, definitions, error, fetchDefinition, filteredRuns, finalDocument,
    finalDocumentState, findLatestDraft, loadDefinitions, loadFinalDocument, loadRuns,
    loadSchedules, mutate, newContent, newTitle, notice, openFinalAsset, pending,
    pendingOperations, query, rejectAssistantPatch, rejectAssistantRequest, reportClient,
    restoreAssistantSession, restoreDefinition, retryAssistantSession, cancelAssistantSession, runDefinition, runQuery,
    runs, scheduleAt, schedules, selectedDefinition, selectedRun, selectedSchedules,
    selectDefinition, setDefinitionCollection, setScheduleEnabled, showMoreRuns, statusFilter, upsertDefinition,
    reviewAssistantReport, submitAssistantInstruction, visibleDefinitions, visibleRunCount, visibleRuns,
  ]);
}

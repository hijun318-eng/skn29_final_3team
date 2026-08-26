/** 보고서 정의·실행·schedule·assistant·최종 asset API 수명주기를 관리하는 hook 모듈이다. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createAnalysisClient } from "../../api/analysisClient.ts";
import { createReportClient } from "../../api/reportClient.ts";
import {
  seoulWallClockToIso,
  type ReportBlockRequest,
  type ReportDefinitionVersion,
  type ReportOrientation,
  type ReportRun,
  type ReportScheduleResponse,
} from "../../contracts/report.ts";
import { createUuid } from "../../utils/createUuid.ts";
import { formatSeoulTime, reportApiError, reportRunStatusLabel } from "./reportPageLabels.ts";
import { isSameReportDefinition, REPORT_RUN_PAGE_SIZE, sortReportDefinitions } from "./reportLifecycleSupport.ts";
import type {
  AssistantTrace,
  CreateDefinitionResult,
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
  const isAdmin = options.isAdmin ?? false;
  const autoLoad = options.autoLoad ?? true;

  const [definitions, setDefinitions] = useState<readonly ReportDefinitionVersion[]>([]);
  const [definitionState, setDefinitionState] = useState<DefinitionListState>("loading");
  const [selectedDefinition, setSelectedDefinition] = useState<ReportDefinitionVersion | null>(null);
  const [pendingOperations, setPendingOperations] = useState<readonly PendingOperation[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<DefinitionStatusFilter>("all");
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

  const definitionsRef = useRef(definitions);
  const selectedDefinitionRef = useRef(selectedDefinition);
  const runsRequestRef = useRef("");
  definitionsRef.current = definitions;
  selectedDefinitionRef.current = selectedDefinition;

  const beginOperation = useCallback((name: string) => {
    const operation = { id: createUuid(), name };
    setPendingOperations((current) => [...current, operation]);
    setError("");
    setNotice("");
    return operation.id;
  }, []);

  const endOperation = useCallback((id: string) => {
    setPendingOperations((current) => current.filter((operation) => operation.id !== id));
  }, []);

  const mutate = useCallback(async <T,>(
    name: string,
    action: () => Promise<T> | T,
  ): Promise<T | null> => {
    const operationId = beginOperation(name);
    try {
      return await action();
    } catch (nextError) {
      setError(reportApiError(nextError));
      return null;
    } finally {
      endOperation(operationId);
    }
  }, [beginOperation, endOperation]);

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
  const clearAssistantTrace = useCallback(() => setAssistantTrace(null), []);

  const selectDefinition = useCallback((definition: ReportDefinitionVersion | null) => {
    setSelectedDefinition(definition);
  }, []);

  const upsertDefinition = useCallback((definition: ReportDefinitionVersion) => {
    setDefinitions((current) => sortReportDefinitions([
      definition,
      ...current.filter((item) => !isSameReportDefinition(item, definition)),
    ]));
    setSelectedDefinition(definition);
    return definition;
  }, []);

  const loadDefinitions = useCallback(async () => {
    setDefinitionState("loading");
    const items = await mutate("definitions", () => reportClient.listDefinitions());
    if (items === null) {
      setDefinitionState("error");
      return null;
    }
    const next = sortReportDefinitions(items);
    setDefinitions(next);
    setSelectedDefinition((current) => (
      current ? next.find((item) => isSameReportDefinition(item, current)) ?? current : current
    ));
    setDefinitionState(next.length ? "ready" : "empty");
    return next;
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
    const blockId = createUuid();
    const blocks: ReportBlockRequest[] = initialContent ? [{
      block_id: blockId,
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
    return { definition, blockId, initialContent };
  }, [clearAssistantTrace, mutate, newContent, newTitle, reportClient, upsertDefinition]);

  const createNextDraft = useCallback(async (definition: ReportDefinitionVersion) => {
    if (definition.status !== "approved") return definition;
    const draft = await mutate("next-draft", () => reportClient.createNextDraft(
      definition.definitionId,
      definition.version,
    ));
    if (!draft) return null;
    upsertDefinition(draft);
    setNotice(`v${draft.version} 초안을 만들었습니다.`);
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
    setNotice(`보고서 실행을 요청했습니다. · ${reportRunStatusLabel(receipt.status)}`);
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

  const requestAssistantDraft = useCallback(async (
    artifactId: string,
    instruction: string,
    requestOptions: { upsert?: boolean } = {},
  ) => {
    const normalizedInstruction = instruction.trim();
    if (!artifactId || !normalizedInstruction) return null;
    const result = await mutate(
      "assistant",
      () => reportClient.createAssistantDraft(artifactId, normalizedInstruction),
    );
    if (!result) return null;
    if (requestOptions.upsert !== false) upsertDefinition(result.definition);
    setAssistantTrace({ requestId: result.requestId, ...result.trace });
    setAssistantInstruction("");
    setNotice("AI 초안을 만들었습니다. 게시하거나 확정하기 전에 내용을 검토해 주세요.");
    return result;
  }, [mutate, reportClient, upsertDefinition]);

  useEffect(() => {
    if (!autoLoad) return;
    void loadDefinitions();
    if (isAdmin) void loadSchedules();
  }, [autoLoad, isAdmin, loadDefinitions, loadSchedules]);

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
    setQuery,
    setStatusFilter,
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
    clearFeedback,
    clearAssistantTrace,
    mutate,
    selectDefinition,
    upsertDefinition,
    loadDefinitions,
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
    requestAssistantDraft,
  }), [
    analysisClient, approveDefinition, assistantInstruction, assistantTrace, cadence,
    clearAssistantTrace, clearFeedback, createDefinition, createNextDraft, createOpen, createSchedule,
    definitionState, definitions, error, fetchDefinition, filteredRuns, finalDocument,
    finalDocumentState, findLatestDraft, loadDefinitions, loadFinalDocument, loadRuns,
    loadSchedules, mutate, newContent, newTitle, notice, openFinalAsset, pending,
    pendingOperations, query, reportClient, requestAssistantDraft, runDefinition, runQuery,
    runs, scheduleAt, schedules, selectedDefinition, selectedRun, selectedSchedules,
    selectDefinition, setScheduleEnabled, showMoreRuns, statusFilter, upsertDefinition,
    visibleDefinitions, visibleRunCount, visibleRuns,
  ]);
}

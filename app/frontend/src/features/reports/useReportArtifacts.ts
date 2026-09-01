/** 보고서 artifact와 저장 분석 library의 병렬 hydration·근거 검증을 소유하는 hook 모듈이다. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  adaptAnalysisRunArtifact,
  analysisArtifactTitle,
  analysisRunArtifactSources,
  reportArtifactLibrarySources,
} from "./reportDraftV2";
import { reportApiError, reportApiRequiredAction } from "./reportPageLabels";
import { reportEvidenceReady } from "./reportArtifactEvidence";

type ArtifactState = { status: string; message: string; requiredAction?: string };

type UseReportArtifactsOptions = {
  analysisClient: any;
  definitions: any[];
  onHydrated: (artifacts: Record<string, any>, definition: any) => void;
  reportClient: any;
  selectedDefinition: any;
  setNotice: (message: string) => void;
};

function isAnalysisSource(source: any): boolean {
  return source?.sourceKind === "analysisRun" || source?.artifactSourceKind === "analysisRun";
}

/** 선택 정의의 artifact와 분석 library를 generation별로 hydrate하며 근거 미완료 결과는 저장하지 않는다. */
export function useReportArtifacts({
  analysisClient,
  definitions,
  onHydrated,
  reportClient,
  selectedDefinition,
  setNotice,
}: UseReportArtifactsOptions) {
  const [artifacts, setArtifacts] = useState<Record<string, any>>({});
  const [artifactStates, setArtifactStates] = useState<Record<string, ArtifactState>>({});
  const [artifactSources, setArtifactSources] = useState<any[]>([]);
  const [analysisLibraryState, setAnalysisLibraryState] = useState({ status: "idle", message: "" });
  const [artifactSelection, setArtifactSelection] = useState("");
  const loadGenerationRef = useRef(0);

  const invalidateLoads = useCallback(() => {
    loadGenerationRef.current += 1;
  }, []);

  useEffect(() => () => {
    loadGenerationRef.current += 1;
  }, []);

  const hydrateSource = useCallback(async (source: any, definition: any) => {
    const artifactId = source.artifactId;
    const analysisSource = isAnalysisSource(source);
    const analysisRun = analysisSource
      ? await analysisClient.getRunArtifact(source.requestId || source.artifactRequestId)
      : null;
    const artifact = analysisSource
      ? adaptAnalysisRunArtifact(analysisRun)
      : await reportClient.getArtifact(source.definitionId, source.definitionVersion, artifactId);
    if (!artifact || !reportEvidenceReady(artifact)) {
      throw new Error("검증 근거가 완전하지 않아 보고서 결과를 표시하지 않습니다.");
    }
    const hydratedSource = {
      ...source,
      queryId: artifact.query_id,
      artifactChecksum: source.artifactChecksum || artifact.artifact_checksum,
      sourceUrns: artifact.evidence.sources.map((item: any) => item.urn),
      ...(analysisSource ? {
        sourceKind: "analysisRun",
        artifactSourceKind: "analysisRun",
        requestId: analysisRun.requestId,
        artifactRequestId: analysisRun.requestId,
        title: analysisArtifactTitle(artifact, source.definitionTitle, source),
      } : {}),
    };
    return { artifact, artifactId, hydratedSource };
  }, [analysisClient, reportClient]);

  const loadArtifacts = useCallback(async (definition: any, includeLibrary = false) => {
    const generation = loadGenerationRef.current + 1;
    loadGenerationRef.current = generation;
    const isCurrentLoad = () => loadGenerationRef.current === generation;
    const reportSources = reportArtifactLibrarySources(definition, includeLibrary ? definitions : [definition]);
    let discoveredAnalysisSources: any[] = [];
    let libraryState = { status: "idle", message: "" };
    if (includeLibrary) {
      setAnalysisLibraryState({ status: "loading", message: "저장된 분석 결과를 확인하는 중입니다." });
      const [definitionResult, runResult] = await Promise.allSettled([
        analysisClient.listDefinitions(),
        analysisClient.listRuns(),
      ]);
      if (runResult.status === "fulfilled") {
        discoveredAnalysisSources = analysisRunArtifactSources(
          runResult.value,
          definitionResult.status === "fulfilled" ? definitionResult.value : [],
        );
        libraryState = definitionResult.status === "fulfilled"
          ? { status: "ready", message: "" }
          : { status: "partial", message: "일부 분석 결과는 지표와 기간으로 표시합니다." };
      } else {
        libraryState = { status: "error", message: "분석 결과 목록을 불러오지 못했습니다. 이미 연결된 결과는 계속 사용할 수 있습니다." };
      }
    } else {
      setAnalysisLibraryState({ status: "idle", message: "" });
    }

    if (!isCurrentLoad()) return false;

    const sourcesByArtifact = new Map(reportSources.filter((source: any) => source.artifactId).map((source: any) => [source.artifactId, source]));
    for (const source of discoveredAnalysisSources) {
      const existing: any = sourcesByArtifact.get(source.artifactId);
      sourcesByArtifact.set(source.artifactId, existing ? { ...source, ...existing, title: source.title, definitionTitle: source.definitionTitle } : source);
    }
    const sources: any[] = [...sourcesByArtifact.values()];
    const ids = sources.map((source) => source.artifactId);
    setArtifactSources(sources);
    setArtifacts({});
    setArtifactStates(Object.fromEntries(ids.map((artifactId) => [artifactId, { status: "loading", message: "" }])));

    const loaded = await Promise.all(sources.map(async (source) => {
      try {
        const result = await hydrateSource(source, definition);
        const status = result.artifact.table?.rows?.length === 0 ? "empty" : "success";
        if (isCurrentLoad()) {
          setArtifactStates((current) => ({ ...current, [result.artifactId]: { status, message: "" } }));
        }
        return result;
      } catch (error) {
        if (isCurrentLoad()) {
          setArtifactStates((current) => ({ ...current, [source.artifactId]: { status: "error", message: reportApiError(error), requiredAction: reportApiRequiredAction(error) } }));
        }
        return { artifact: null, artifactId: source.artifactId, hydratedSource: source };
      }
    }));
    if (!isCurrentLoad()) return false;
    const artifactMap = Object.fromEntries(loaded.map(({ artifactId, artifact }) => [artifactId, artifact]));
    setArtifacts(artifactMap);
    onHydrated(artifactMap, definition);
    setArtifactSources(loaded.map(({ hydratedSource }) => hydratedSource));

    const unavailableCount = loaded.filter(({ artifact, hydratedSource }) => !artifact && isAnalysisSource(hydratedSource)).length;
    if (includeLibrary) setAnalysisLibraryState(libraryState.status === "error"
      ? libraryState
      : unavailableCount
        ? { status: "partial", message: [libraryState.message, `${unavailableCount}개 분석 결과를 사용할 수 없어 목록에서 제외했습니다.`].filter(Boolean).join(" ") }
        : libraryState);
    const availableIds = loaded.filter(({ artifact }) => artifact).map(({ artifactId }) => artifactId);
    setArtifactSelection((current) => availableIds.includes(current) ? current : availableIds[0] || "");
    return true;
  }, [analysisClient, definitions, hydrateSource, onHydrated]);

  const retryArtifact = useCallback(async (artifactId: string) => {
    if (!selectedDefinition || !artifactId) return;
    const generation = loadGenerationRef.current;
    const isCurrentLoad = () => loadGenerationRef.current === generation;
    const source = artifactSources.find((item) => item.artifactId === artifactId);
    if (!source) return;
    setArtifactStates((current) => ({ ...current, [artifactId]: { status: "loading", message: "" } }));
    try {
      const result = await hydrateSource({
        ...source,
        definitionId: source.definitionId || selectedDefinition.definitionId,
        definitionVersion: source.definitionVersion ?? selectedDefinition.version,
      }, selectedDefinition);
      if (!isCurrentLoad()) return;
      setArtifacts((current) => ({ ...current, [artifactId]: result.artifact }));
      onHydrated({ [artifactId]: result.artifact }, selectedDefinition);
      setArtifactSources((current) => current.map((item) => item.artifactId === artifactId ? result.hydratedSource : item));
      setArtifactStates((current) => ({ ...current, [artifactId]: { status: result.artifact.table?.rows?.length === 0 ? "empty" : "success", message: "" } }));
      setNotice("분석 결과를 다시 불러왔습니다.");
    } catch (error) {
      if (!isCurrentLoad()) return;
      setArtifactStates((current) => ({ ...current, [artifactId]: { status: "error", message: reportApiError(error), requiredAction: reportApiRequiredAction(error) } }));
    }
  }, [artifactSources, hydrateSource, onHydrated, selectedDefinition, setNotice]);

  const artifactOptions = useMemo(() => {
    const seen = new Set<string>();
    return artifactSources.filter((source) => {
      if (!source.artifactId || !artifacts[source.artifactId] || seen.has(source.artifactId)) return false;
      seen.add(source.artifactId);
      return true;
    });
  }, [artifactSources, artifacts]);

  return {
    analysisLibraryState,
    artifactOptions,
    artifactSelection,
    artifactSources,
    artifactStates,
    artifacts,
    invalidateLoads,
    loadArtifacts,
    retryArtifact,
    setArtifactSelection,
  };
}

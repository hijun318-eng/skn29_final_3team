/** 최종문서 조회의 timeout·취소·generation·pending 정리를 소유하는 hook 모듈이다. */
import { useCallback, useEffect, useRef, useState } from "react";

import { ReportApiError } from "../../api/reportClient.ts";
import type { ReportDefinitionVersion, ReportDocument } from "../../contracts/report.ts";
import { reportApiError } from "./reportPageLabels.ts";
import type { FinalDocumentState } from "./reportLifecycleTypes.ts";

const FINAL_DOCUMENT_TIMEOUT_MS = 15_000;

type FinalDocumentClient = {
  getFinalDocument: (
    definitionId: string,
    version: number,
    signal?: AbortSignal,
  ) => Promise<ReportDocument>;
};

type UseFinalReportDocumentOptions = {
  beginOperation: (name: string) => string;
  endOperation: (id: string) => void;
  reportClient: FinalDocumentClient;
  setError: (message: string) => void;
};

/** 최종문서 요청을 15초·generation·AbortSignal로 격리하고 stale 응답은 null로 폐기한다. */
export function useFinalReportDocument({
  beginOperation,
  endOperation,
  reportClient,
  setError,
}: UseFinalReportDocumentOptions) {
  const [finalDocument, setFinalDocument] = useState<ReportDocument | null>(null);
  const [finalDocumentState, setFinalDocumentState] = useState<FinalDocumentState>("idle");
  const requestRef = useRef("");
  const abortRef = useRef<AbortController | null>(null);

  const cancelFinalDocumentLoad = useCallback(() => {
    const operationId = requestRef.current;
    requestRef.current = "";
    abortRef.current?.abort();
    abortRef.current = null;
    if (operationId) endOperation(operationId);
    setFinalDocument(null);
    setFinalDocumentState("idle");
  }, [endOperation]);

  useEffect(() => cancelFinalDocumentLoad, [cancelFinalDocumentLoad]);

  const loadFinalDocument = useCallback(async (
    definition: ReportDefinitionVersion | null,
  ): Promise<ReportDocument | null> => {
    cancelFinalDocumentLoad();
    if (!definition || definition.status !== "approved") return null;

    const operationId = beginOperation("final-document");
    const controller = new AbortController();
    let timedOut = false;
    requestRef.current = operationId;
    abortRef.current = controller;
    setFinalDocumentState("loading");
    let timeout = 0;
    try {
      // AbortSignal을 무시하는 주입 client도 전역 pending을 영구 점유하지 못하도록 race 자체에 시간 한도를 둔다.
      const document = await Promise.race([
        reportClient.getFinalDocument(
          definition.definitionId,
          definition.version,
          controller.signal,
        ),
        new Promise<never>((_, reject) => {
          timeout = window.setTimeout(() => {
            timedOut = true;
            controller.abort();
            reject(new DOMException("Final document request timed out", "AbortError"));
          }, FINAL_DOCUMENT_TIMEOUT_MS);
        }),
      ]);
      // 취소 뒤 늦게 완료된 이전 정의의 metadata가 현재 draft 방향·통화 정책을 덮지 못하게 반환도 차단한다.
      if (requestRef.current !== operationId) return null;
      setFinalDocument(document);
      setFinalDocumentState("ready");
      return document;
    } catch (nextError) {
      if (requestRef.current !== operationId) return null;
      if (timedOut) {
        setFinalDocumentState("error");
        setError("확정 문서 정보를 15초 안에 불러오지 못했습니다. 다시 시도해 주세요.");
      } else if (nextError instanceof ReportApiError && nextError.status === 404) {
        setFinalDocumentState("missing");
      } else if (nextError instanceof DOMException && nextError.name === "AbortError") {
        setFinalDocumentState("idle");
      } else {
        setFinalDocumentState("error");
        setError(reportApiError(nextError));
      }
      return null;
    } finally {
      window.clearTimeout(timeout);
      if (requestRef.current === operationId) requestRef.current = "";
      if (abortRef.current === controller) abortRef.current = null;
      endOperation(operationId);
    }
  }, [beginOperation, cancelFinalDocumentLoad, endOperation, reportClient, setError]);

  return { cancelFinalDocumentLoad, finalDocument, finalDocumentState, loadFinalDocument };
}

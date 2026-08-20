/** 서버 보고서 제목의 편집값·저장 기준·이탈 경고를 draft 수명주기에 맞춰 관리한다. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface ReportIdentity {
  readonly definitionId?: string;
  readonly version?: number;
  readonly title?: string;
}

interface UseReportTitleDraftOptions {
  readonly editable: boolean;
  readonly identity?: ReportIdentity | null;
}

/** 제목을 브라우저 전용 데이터로 만들지 않고 서버 definition의 저장 기준과 비교한다. */
export function useReportTitleDraft({ editable, identity }: UseReportTitleDraftOptions) {
  const identityKey = `${identity?.definitionId ?? ""}:${identity?.version ?? ""}`;
  const serverTitle = identity?.title ?? "";
  const [title, setTitle] = useState(serverTitle);
  const savedTitleRef = useRef(serverTitle);

  useEffect(() => {
    savedTitleRef.current = serverTitle;
    setTitle(serverTitle);
  }, [identityKey, serverTitle]);

  const isDirty = editable && title !== savedTitleRef.current;
  const changeTitle = useCallback((value: string) => {
    if (editable) setTitle(value);
  }, [editable]);
  const markSaved = useCallback((value: string) => {
    savedTitleRef.current = value;
    setTitle(value);
  }, []);

  useEffect(() => {
    if (!isDirty) return undefined;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [isDirty]);

  return useMemo(() => ({ title, isDirty, changeTitle, markSaved }), [
    changeTitle, isDirty, markSaved, title,
  ]);
}

/** 보고서 lifecycle hook의 API port·상태·명령 입력 타입을 정의하는 모듈이다. */
import type { AnalysisClient } from "../../api/analysisClient.ts";
import type { createReportClient } from "../../api/reportClient.ts";
import type {
  ManualRunCommandResponse,
  ReportDefinitionVersion,
  ReportRun,
} from "../../contracts/report.ts";

/** 보고서 HTTP factory가 생성하는 비동기 port 타입이다. */ export type ReportClient = ReturnType<typeof createReportClient>;
/** 정의 목록의 독립 로딩 상태다. */ export type DefinitionListState = "loading" | "ready" | "empty" | "error";
/** 최종문서 요청의 취소 가능한 상태다. */ export type FinalDocumentState = "idle" | "loading" | "ready" | "missing" | "error";
/** 정의 목록에서 허용되는 상태 필터다. */ export type DefinitionStatusFilter = "all" | "draft" | "approved";
/** 정의 목록의 비파괴 lifecycle 범위다. */ export type DefinitionCollection = "active" | "archived";
/** 서버 schedule이 지원하는 반복 주기다. */ export type ScheduleCadence = "daily" | "weekly" | "monthly";
/** 최종문서 다운로드에서 지원하는 asset 형식이다. */ export type FinalAssetFormat = "html" | "pdf";

/** lifecycle hook의 client·오류 focus·최종문서 의존성 주입 계약이다. */ export interface UseReportLifecycleStateOptions {
  readonly role?: string;
  readonly isAdmin?: boolean;
  readonly autoLoad?: boolean;
  readonly reportClient?: ReportClient;
  readonly analysisClient?: AnalysisClient;
}

/** 중복 응답을 구분하는 operation 식별자와 종류다. */ export interface PendingOperation {
  readonly id: string;
  readonly name: string;
}

/** 새 정의 생성과 초기 draft를 묶은 명령 결과다. */ export interface CreateDefinitionResult {
  readonly definition: ReportDefinitionVersion;
  readonly initialContent: string;
}

/** 수동 실행의 선택적 멱등 식별자 입력이다. 기준일은 서버가 소유한다. */ export interface ManualRunOptions {
  readonly idempotencyKey?: string;
}

/** 수동 실행 응답과 최신 실행 목록을 묶은 결과다. */ export interface ManualRunResult {
  readonly receipt: ManualRunCommandResponse;
  readonly run: ReportRun | null;
}

/** schedule 생성 폼의 검증 전 입력이다. */ export interface ScheduleFormValues {
  readonly cadence: ScheduleCadence;
  readonly scheduleAt: string;
}

/** assistant 초안 생성의 감사 가능한 단계·결과 trace다. */ export interface AssistantTrace {
  readonly requestId: string;
  readonly model_version: string;
  readonly prompt_id: string;
  readonly prompt_version: string;
  readonly prompt_hash: string;
  readonly attempts: number;
  readonly duration_ms: number;
}

import axios from 'axios';

// ===== API 클라이언트 =====

export const api = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ===== 응답 Envelope 타입 =====

export interface APIResponse<T> {
  data: T;
  meta: {
    page?: number;
    per_page?: number;
    total?: number;
    request_id: string;
  };
  error: APIError | null;
}

export interface APIError {
  code: ErrorCode;
  message: string;
  details?: Record<string, string>;
}

// ===== 에러 코드 =====

export type ErrorCode =
  | 'E_AUTH'       // 인증 실패
  | 'E_SCOPE'      // 권한 부족
  | 'E_VALIDATION' // 입력 검증 실패
  | 'E_NOT_FOUND'  // 리소스 없음
  | 'E_CONFLICT'   // 충돌
  | 'E_RATE_LIMIT' //_RATE_LIMIT 초과
  | 'E_EXTERNAL'   // 외부 서비스 오류
  | 'E_TIMEOUT'    // 시간 초과
  | 'E_INTERNAL'   // 내부 서버 오류
  | 'E_UNAVAILABLE'; // 서비스 사용 불가

// ===== 사용자 관련 타입 =====

export type UserRole = 'admin' | 'operator' | 'staff' | 'guest';

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  avatar_url?: string;
}

export interface LoginRequest {
  staff_id: string;
  password: string;
}

export interface LoginResponse {
  user: User;
  access_token: string;
  refresh_token: string;
}

// ===== VOC 관련 타입 =====

export type Severity = 'danger' | 'warn' | 'ok';
export type VOCStatus = 'recv' | 'check' | 'prog' | 'done';

export interface Zone {
  id: string;
  name: string;
  facilities: Facility[];
}

export interface Facility {
  id: string;
  name: string;
  zone_id: string;
}

export interface VOCEntity {
  id: string;
  text: string;
  zone: string;
  facility: string;
  severity: Severity;
  status: VOCStatus;
  sentiment: 'positive' | 'negative' | 'neutral';
  confidence: number;
  category: string;
  created_at: string;
  updated_at: string;
}

export interface VOCTimelineEntry {
  timestamp: string;
  action: string;
  operator?: string;
}

// ===== 보고서 관련 타입 =====

export type ReportType = 'weekly' | 'monthly' | 'quarterly';
export type ReportStatus = 'draft' | 'done';

export interface Report {
  id: string;
  type: ReportType;
  period: string;
  status: ReportStatus;
  author: string;
  created_at: string;
  updated_at: string;
}

export type ReportBlockKind = 'text' | 'chart' | 'fail';

export interface ReportBlock {
  id: string;
  kind: ReportBlockKind;
  title: string;
  body?: string;
  chart?: ChartData;
}

export interface ChartData {
  bars: number[];
  labels?: string[];
  summary: string;
  intent: string;
}

// ===== 대화형 조회 타입 =====

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  chart?: ChartData;
  created_at: string;
}

// ===== 외부 리뷰 타입 =====

export type ExternalSource = 'naver' | 'google' | 'tripadvisor' | 'agoda';

export interface ExternalReview {
  id: string;
  source: ExternalSource;
  rating: number;
  text: string;
  author: string;
  date: string;
  sentiment: 'positive' | 'negative' | 'neutral';
  severity: Severity;
}

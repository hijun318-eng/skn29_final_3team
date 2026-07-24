/**
 * 합성 데이터 (목업 v1.2)
 * 실제 API 호출 없이 프론트엔드 UI 검증용
 */

import type { Severity, VOCStatus } from '../lib/api.ts';

/* ------------------------------------------------------------------ */
/*  VOC 사고 (SP-03 모니터링)                                          */
/* ------------------------------------------------------------------ */

export interface Incident {
  id: string;
  fac: string;
  zone: string;
  x: number;
  y: number;
  sev: Severity;
  status: VOCStatus;
  open: number;
  text: string;
  sent: string;
  conf: number;
  cat: string;
  ago: string;
  elapsed: number;
  hist: [string, string][];
}

export const INC: Incident[] = [
  {
    id: 'v1', fac: '피자힐', zone: '다이닝', x: 340, y: 250,
    sev: 'danger', status: 'prog', open: 2,
    text: '대기 40분째입니다. 예약했는데 자리가 없다고 하네요.',
    sent: '부정', conf: 0.91, cat: '대기·혼잡', ago: '3분 전', elapsed: 28,
    hist: [['14:02', '접수 (자동)'], ['14:10', '확인 · 이OO'], ['14:15', '진행중 · 이OO']],
  },
  {
    id: 'v2', fac: '리버파크', zone: '레저·웰니스', x: 520, y: 180,
    sev: 'warn', status: 'check', open: 1,
    text: '수영장 물이 조금 차가운 편이에요.',
    sent: '부정', conf: 0.68, cat: '온도·환경', ago: '12분 전', elapsed: 12,
    hist: [['13:58', '접수 (자동)'], ['14:06', '확인 · 박OO']],
  },
  {
    id: 'v3', fac: '컨벤션 센터', zone: 'MICE·엔터', x: 250, y: 400,
    sev: 'ok', status: 'done', open: 0,
    text: '행사장 안내가 친절했습니다. 감사합니다!',
    sent: '긍정', conf: 0.95, cat: '직원 서비스', ago: '1시간 전', elapsed: 62,
    hist: [['12:40', '접수 (자동)'], ['12:52', '확인 · 김OO'], ['13:05', '완료 · 김OO']],
  },
  {
    id: 'v4', fac: '그랜드 워커힐', zone: '객실동', x: 180, y: 150,
    sev: 'warn', status: 'recv', open: 3,
    text: '객실 에어컨에서 소음이 납니다.',
    sent: '부정', conf: 0.74, cat: '시설 고장', ago: '6분 전', elapsed: 6,
    hist: [['14:12', '접수 (자동)']],
  },
  {
    id: 'v5', fac: '주차타워', zone: '인프라', x: 600, y: 420,
    sev: 'ok', status: 'check', open: 1,
    text: '주차 자리 안내가 헷갈렸어요.',
    sent: '중립', conf: 0.55, cat: '예약·안내', ago: '20분 전', elapsed: 20,
    hist: [['13:52', '접수 (자동)'], ['14:00', '확인 · 최OO']],
  },
  {
    id: 'v6', fac: '빛의 시어터', zone: 'MICE·엔터', x: 430, y: 410,
    sev: 'ok', status: 'done', open: 0,
    text: '공연 음향이 훌륭했습니다.',
    sent: '긍정', conf: 0.93, cat: '소음', ago: '2시간 전', elapsed: 120,
    hist: [['12:00', '접수 (자동)'], ['12:20', '완료 · 김OO']],
  },
];

/* ------------------------------------------------------------------ */
/*  대화형 조회 Q&A (SP-04)                                           */
/* ------------------------------------------------------------------ */

export interface QAPair {
  question: string;
  intent: string;
  period: string;
  place: string;
  n: string;
  bars: number[];
  labels?: string[];
  summary: string;
  unit: string;
}

export const QA: QAPair[] = [
  {
    question: '지난주 피자힐 평균 대기시간 보여줘',
    intent: 'avg_wait_time', period: '07/14~07/20', place: '피자힐', n: '표본 7일',
    bars: [8, 10, 14, 18, 14, 11, 9], summary: '평균 대기 12.4분 (전주 대비 +2.1분)', unit: '분',
  },
  {
    question: '이번 주 VOC 추이',
    intent: 'voc_trend', period: '07/14~07/20', place: '전체', n: '표본 7일',
    bars: [12, 18, 15, 24, 20, 16, 22], summary: '일 평균 18.1건, 목요일 피크(24건)', unit: '건',
  },
  {
    question: '구역별 미해결 현황',
    intent: 'unresolved_by_zone', period: '실시간', place: '전체 구역', n: '5개 구역',
    bars: [3, 2, 1, 1, 0], labels: ['객실동', '다이닝', '레저', 'MICE', '인프라'],
    summary: '미해결 7건, 객실동 최다(3건)', unit: '건',
  },
  {
    question: '어제 위험 VOC 건수',
    intent: 'danger_count', period: '07/23', place: '전체', n: '표본 1일',
    bars: [1, 0, 2, 1, 0], summary: '위험 4건 발생, 다이닝·객실동 집중', unit: '건',
  },
];

/* ------------------------------------------------------------------ */
/*  외부 리뷰 (SP-06)                                                  */
/* ------------------------------------------------------------------ */

export interface Review {
  id: string;
  sev: Severity;
  src: string;
  ago: string;
  time: string;
  text: string;
  full: string;
  sent: string;
  conf: number;
  cat: string;
  sim: [string, string, string][];
}

export const REV: Review[] = [
  {
    id: 'r1', sev: 'danger', src: '네이버', ago: '3시간 전', time: '07/22 14:00',
    text: '예약과 다른 객실 배정',
    full: '예약할 때 시티뷰로 했는데 체크인하니 다른 방으로 배정됐어요. 확인 요청했지만 대기가 길었습니다.',
    sent: '부정', conf: 0.94, cat: '예약·안내',
    sim: [['객실동 "배정 착오"', '07/18', '완료'], ['객실동 "룸타입 문의"', '07/15', '완료']],
  },
  {
    id: 'r2', sev: 'warn', src: '구글', ago: '어제', time: '07/23 10:20',
    text: '체크인 대기 김',
    full: '주말이라 그런지 체크인 줄이 길어서 20분 넘게 기다렸습니다.',
    sent: '부정', conf: 0.71, cat: '대기·혼잡',
    sim: [['로비 "체크인 혼잡"', '07/20', '진행중']],
  },
  {
    id: 'r3', sev: 'ok', src: '트립어드바이저', ago: '어제', time: '07/23 09:00',
    text: '조식 만족',
    full: '조식 뷔페 종류가 다양하고 맛있었어요. 재방문 의사 있습니다.',
    sent: '긍정', conf: 0.96, cat: '직원 서비스', sim: [],
  },
];

/* ------------------------------------------------------------------ */
/*  KPI (SP-03 모니터링 상단)                                          */
/* ------------------------------------------------------------------ */

export const KPI = {
  todayVoc: 24,
  unresolved: 7,
  avgProcess: 41,
  dangerUnhandled: 1,
} as const;

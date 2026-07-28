// synthetic dataset for the VOC agent console. no real guest data.
export const SYNTHETIC_META = {
  source: "synthetic",
  dataset: "walkerhill-voc-console",
  schemaVersion: "0.3.0",
  seed: 29003,
  generatedAt: "2026-07-27",
  note: "합성 데이터입니다. 실데이터 연동 전 UI 검증 목적으로만 사용합니다.",
};

export const PROPERTIES = ["그랜드 워커힐 서울", "비스타 워커힐 서울", "더글라스 하우스", "다락휴"];

/* ── 1. 일반 사용자용 챗 ───────────────────────────────────────── */
export const AGENT_SUGGESTIONS = [
  "지난주 부정 VOC가 가장 많이 늘어난 구역은?",
  "체크인 대기 불만의 원인 후보를 근거와 함께 알려줘",
  "비스타 조식 혼잡 이슈, 지금 무엇부터 처리해야 해?",
  "이번 달 하우스키핑 관련 VOC를 요약해줘",
];

export const AGENT_THREADS = [
  { id: "t1", title: "체크인 대기 이슈 원인 분석", updated: "12분 전", pinned: true },
  { id: "t2", title: "주말 조식 혼잡 대응안 비교", updated: "어제" },
  { id: "t3", title: "6월 객실 청결 VOC 요약", updated: "07.24" },
  { id: "t4", title: "OTA 평점 하락 구간 점검", updated: "07.21" },
];

// 데모용 고정 응답. 질문 키워드로 매칭하고 없으면 fallback.
export const AGENT_ANSWERS = [
  {
    match: ["체크인", "대기", "프론트"],
    steps: ["질문 의도 분류 · 원인 분석", "PMS 체크인 로그 조회 (28일)", "VOC 텍스트 클러스터링 134건", "근거 교차 검증"],
    answer:
      "체크인 대기 불만은 최근 28일 134건으로 전월 대비 +18건 증가했습니다. 가장 가능성이 높은 원인은 **성수기 예약 집중(91%)**과 **프론트 인력 부족(87%)**이며, PMS 응답 지연(64%)은 부차적 요인으로 보입니다.\n\n대기 시간은 15:00~17:00 구간에 집중되고, 20인 이상 단체 체크인이 겹친 6일에 평균 대기가 12분 → 31분으로 늘었습니다.",
    bullets: [
      "즉시: 15~17시 프론트 2명 탄력 배치, 키오스크 운영 2시간 연장",
      "단기: 단체 체크인 사전 등록 도입으로 동시 도착 분산",
      "점검: PMS 조회 API p95 응답시간 1.8초 → 목표 1초",
    ],
    evidence: [
      { id: "EV-2041", source: "OTA 리뷰", label: "\"체크인에 40분 기다렸습니다\"", conf: 94, date: "07.13" },
      { id: "EV-2038", source: "PMS 로그", label: "15:40 동시 체크인 27건 / 데스크 3석", conf: 99, date: "07.13" },
      { id: "EV-2031", source: "설문", label: "프론트 응대 만족도 4.1 → 3.6", conf: 88, date: "07.12" },
    ],
    confidence: 92,
  },
  {
    match: ["조식", "혼잡", "좌석"],
    steps: ["질문 의도 분류 · 우선순위 판단", "F&B POS 회전율 조회", "VOC 76건 감성 분석", "대응안 효과 시뮬레이션"],
    answer:
      "비스타 조식 혼잡은 좌석 부족이 부정 VOC의 41%를 차지합니다. 08:00~09:00 점유율이 92%를 넘는 날에만 발생하는 **용량 초과형 이슈**로, 인력 증원보다 좌석·입장 분산이 효과가 큽니다.",
    bullets: [
      "1순위: 피크 60분간 임시 좌석 24석 운영 (혼잡도 -21% 추정)",
      "2순위: 단체 입장 시간 15분 단위 분산 안내",
      "3순위: 탄력 인력 2명은 좌석 조치 후 효과 재측정",
    ],
    evidence: [
      { id: "EV-1980", source: "POS", label: "08:00~09:00 좌석 회전율 1.9회", conf: 97, date: "07.26" },
      { id: "EV-1974", source: "VOC", label: "\"자리가 없어 20분 서서 기다렸다\"", conf: 91, date: "07.25" },
    ],
    confidence: 87,
  },
];

export const AGENT_FALLBACK = {
  steps: ["질문 의도 분류", "카탈로그 소스 3개 조회", "근거 문서 랭킹"],
  answer:
    "합성 데이터 범위 안에서 답변 가능한 주제는 VOC 추이·원인 분석, 구역별 이슈, 고객 360 요약, 보고서 초안입니다. 아래 추천 질문을 사용하시면 근거까지 함께 확인할 수 있습니다.",
  bullets: [],
  evidence: [],
  confidence: 41,
};

/* ── 2. 보고서 ─────────────────────────────────────────────────── */
export const REPORT_TABS = [
  { key: "daily", label: "일일 보고", period: "2026.07.27 (월)", cadence: "매일 07:00 자동 생성" },
  { key: "weekly", label: "주간 보고", period: "2026.07.20 ~ 07.26", cadence: "매주 월 08:00 자동 생성" },
  { key: "monthly", label: "월간 보고", period: "2026년 06월", cadence: "매월 1일 09:00 자동 생성" },
];

export const REPORTS = {
  daily: {
    status: "초안",
    author: "VOC Agent",
    reviewer: "CX 운영팀 박준희",
    headline: "체크인 대기 VOC가 3일 연속 증가했습니다. 오늘 15시 피크 전 인력 배치 결정이 필요합니다.",
    kpis: [
      { label: "신규 VOC", value: "38", delta: "+6", dir: "up", bad: true, note: "전일 대비" },
      { label: "부정 비율", value: "21.1%", delta: "+2.4%p", dir: "up", bad: true, note: "목표 15% 이하" },
      { label: "평균 최초 응답", value: "24분", delta: "-3분", dir: "down", note: "목표 30분 이하" },
      { label: "조치 완료율", value: "82%", delta: "+4%p", dir: "up", note: "목표 90%" },
    ],
    series: [
      { t: "00시", voc: 1, neg: 0 }, { t: "04시", voc: 2, neg: 1 }, { t: "08시", voc: 9, neg: 3 },
      { t: "12시", voc: 6, neg: 1 }, { t: "16시", voc: 12, neg: 5 }, { t: "20시", voc: 8, neg: 3 },
    ],
    issues: [
      ["체크인 대기 시간 과다", "프론트", "12건", "긴급", "+5"],
      ["객실 온도 조절 불만", "시설", "6건", "보통", "+1"],
      ["룸서비스 지연", "F&B", "5건", "보통", "-2"],
    ],
    sections: [
      { title: "운영 요약", body: "체크인 16시 피크에 VOC가 집중되었고 부정 비율이 21.1%로 목표를 초과했습니다. 객실 청결·조식 관련 VOC는 전일 대비 감소해 개선 조치가 유효한 것으로 보입니다." },
      { title: "오늘의 결정 필요 사항", body: "15:00~17:00 프론트 탄력 인력 2명 배치 승인. 미승인 시 단체 체크인 3건이 겹치는 오늘 대기시간이 30분을 넘길 가능성이 높습니다." },
    ],
  },
  weekly: {
    status: "검토 중",
    author: "VOC Agent",
    reviewer: "CX 운영팀 박준희",
    headline: "부정 VOC 비율은 2.4%p 개선됐지만 프론트 데스크 단일 이슈가 전체 증가분의 68%를 차지합니다.",
    kpis: [
      { label: "총 VOC", value: "264", delta: "+19", dir: "up", bad: true, note: "전주 대비" },
      { label: "부정 비율", value: "18.2%", delta: "-2.4%p", dir: "down", note: "목표 15% 이하" },
      { label: "고객 만족도", value: "4.7", delta: "+0.2", dir: "up", note: "5점 기준" },
      { label: "평균 대기시간", value: "8분", delta: "-5분", dir: "down", note: "목표 10분 이하" },
    ],
    series: [
      { t: "월", voc: 34, neg: 8 }, { t: "화", voc: 36, neg: 7 }, { t: "수", voc: 41, neg: 9 },
      { t: "목", voc: 38, neg: 6 }, { t: "금", voc: 43, neg: 10 }, { t: "토", voc: 39, neg: 5 }, { t: "일", voc: 33, neg: 3 },
    ],
    issues: [
      ["체크인 대기 시간 과다", "프론트", "134건", "긴급", "+18"],
      ["객실 청결 상태 불량", "하우스키핑", "89건", "높음", "+11"],
      ["레스토랑 예약 불편", "F&B", "67건", "높음", "+2"],
      ["엘리베이터 대기 지연", "시설", "45건", "보통", "-5"],
      ["Wi-Fi 연결 불안정", "IT", "38건", "보통", "+8"],
    ],
    sections: [
      { title: "핵심 결론", body: "주간 전체 지표는 개선 추세이나 프론트 데스크 이슈가 구조적으로 남아 있습니다. 인력·시스템·예약 정책 세 축을 동시에 조정하지 않으면 8월 성수기에 재발할 가능성이 높습니다." },
      { title: "실행 과제 진척", body: "조식 인력 재배치 시범 운영 65%, 임시 좌석 동선 안전 검토 30%, 단체 예약 안내 문구 개정 0%(예정)." },
      { title: "다음 주 전망", body: "권고안 적용 시 부정 VOC 비율 15.8% 예상. 미적용 시 19.4%로 재상승 가능성이 있습니다." },
    ],
  },
  monthly: {
    status: "확정",
    author: "VOC Agent",
    reviewer: "운영본부 김성호",
    headline: "6월 만족도는 전년 동월 대비 +0.4 개선, 반복 이슈 3건이 전체 부정 VOC의 절반을 차지합니다.",
    kpis: [
      { label: "총 VOC", value: "1,142", delta: "+64", dir: "up", bad: true, note: "전월 대비" },
      { label: "부정 비율", value: "16.4%", delta: "-3.1%p", dir: "down", note: "목표 15% 이하" },
      { label: "고객 만족도", value: "4.6", delta: "+0.4", dir: "up", note: "전년 동월 대비" },
      { label: "재방문 의향", value: "78%", delta: "+5%p", dir: "up", note: "설문 응답 412건" },
    ],
    series: [
      { t: "1주", voc: 258, neg: 52 }, { t: "2주", voc: 287, neg: 49 },
      { t: "3주", voc: 301, neg: 44 }, { t: "4주", voc: 296, neg: 42 },
    ],
    issues: [
      ["체크인 대기 시간 과다", "프론트", "412건", "긴급", "+52"],
      ["객실 청결 상태 불량", "하우스키핑", "318건", "높음", "+21"],
      ["레스토랑 예약 불편", "F&B", "204건", "높음", "-14"],
      ["주차 안내 혼선", "시설", "121건", "보통", "+9"],
    ],
    sections: [
      { title: "월간 총평", body: "만족도와 부정 VOC 비율 모두 개선됐습니다. 다만 총 VOC 건수 증가는 리뷰 수집 채널 확대(OTA 2곳 추가)의 영향이 큽니다." },
      { title: "반복 이슈 구조 분석", body: "체크인·청결·예약 3개 이슈가 부정 VOC의 51%입니다. 세 이슈 모두 피크 수요 집중 구간에 발생해 수요 분산 정책이 공통 해법으로 도출됩니다." },
      { title: "분석 기준", body: "기간 2026.06.01~06.30 · 표본 1,142건 · synthetic schema 0.3.0 · seed 29003. 합성 데이터이므로 절대값이 아닌 상대 추세로 해석해야 합니다." },
    ],
  },
};

/* ── 3. 고객 360 ───────────────────────────────────────────────── */
export const CUSTOMERS = [
  {
    id: "G-100482", name: "김지훈", initials: "KJ", tier: "Diamond", property: "그랜드 워커힐 서울",
    segment: "장기 재방문 · 비즈니스", risk: "이탈 위험", riskLevel: "high", ltv: "42,800,000원",
    stays: 18, nights: 46, lastStay: "2026.07.18", avgSpend: "2,377,000원", nps: 6, sentiment: -0.28,
    tags: ["고층 선호", "레이트 체크아웃", "조용한 객실", "라운지 이용"],
    channels: [{ k: "OTA 리뷰", v: 4 }, { k: "설문", v: 7 }, { k: "프론트 접수", v: 5 }, { k: "콜센터", v: 2 }],
    trend: [
      { t: "2월", sat: 4.6, spend: 2.4 }, { t: "3월", sat: 4.5, spend: 2.6 }, { t: "4월", sat: 4.2, spend: 2.2 },
      { t: "5월", sat: 3.8, spend: 1.9 }, { t: "6월", sat: 3.4, spend: 1.6 }, { t: "7월", sat: 3.1, spend: 1.4 },
    ],
    timeline: [
      { d: "07.18", type: "VOC", tone: "neg", text: "체크인 대기 25분. 멤버십 전용 데스크가 운영되지 않았습니다.", src: "설문" },
      { d: "07.18", type: "숙박", tone: "neutral", text: "디럭스 리버뷰 2박 · 라운지 2회 이용 · 결제 3,120,000원", src: "PMS" },
      { d: "06.29", type: "VOC", tone: "neg", text: "요청한 고층 객실이 배정되지 않았습니다.", src: "프론트" },
      { d: "05.31", type: "보상", tone: "pos", text: "라운지 무료 이용권 2매 제공 · 담당 프론트 이서연", src: "CRM" },
      { d: "05.30", type: "숙박", tone: "neutral", text: "스위트 1박 · 스파 1회 · 결제 2,480,000원", src: "PMS" },
    ],
    nextBest: [
      { title: "멤버십 전용 체크인 안내 및 사과 연락", why: "동일 불만 2회 반복 · 티어 Diamond", owner: "CX 운영팀" },
      { title: "다음 예약 시 고층 리버뷰 사전 확정", why: "선호 미반영이 최근 불만의 직접 원인", owner: "예약실" },
    ],
    chat: [
      { match: ["이탈", "위험", "왜"], answer: "이 고객의 이탈 위험은 **높음**입니다. 근거는 3개입니다. ①만족도 6개월 연속 하락(4.6→3.1) ②객실 선호 미반영 불만 2회 반복 ③1박 평균 결제액 2.4→1.4백만원 감소. 티어 Diamond·LTV 4,280만원 기준 우선 리텐션 대상입니다." },
      { match: ["선호", "요청", "취향"], answer: "확인된 선호는 고층·조용한 객실·레이트 체크아웃·라운지 이용입니다. 최근 2회 예약에서 고층 배정이 이뤄지지 않아 동일 불만이 반복됐습니다." },
    ],
  },
  {
    id: "G-100751", name: "박서연", initials: "PS", tier: "Gold", property: "비스타 워커힐 서울",
    segment: "주말 레저 · 가족", risk: "안정", riskLevel: "low", ltv: "18,200,000원",
    stays: 9, nights: 21, lastStay: "2026.07.25", avgSpend: "1,412,000원", nps: 9, sentiment: 0.41,
    tags: ["패밀리룸", "조식 포함", "수영장", "주말 투숙"],
    channels: [{ k: "OTA 리뷰", v: 6 }, { k: "설문", v: 4 }, { k: "프론트 접수", v: 1 }, { k: "콜센터", v: 0 }],
    trend: [
      { t: "2월", sat: 4.3, spend: 1.2 }, { t: "3월", sat: 4.4, spend: 1.3 }, { t: "4월", sat: 4.5, spend: 1.4 },
      { t: "5월", sat: 4.6, spend: 1.5 }, { t: "6월", sat: 4.7, spend: 1.4 }, { t: "7월", sat: 4.8, spend: 1.6 },
    ],
    timeline: [
      { d: "07.25", type: "VOC", tone: "pos", text: "아이 동반 응대가 매우 친절했습니다. 수영장 시간 안내도 좋았어요.", src: "OTA" },
      { d: "07.25", type: "숙박", tone: "neutral", text: "패밀리 디럭스 2박 · 조식 4인 · 결제 1,860,000원", src: "PMS" },
      { d: "07.25", type: "VOC", tone: "neg", text: "조식 시간대에 좌석이 부족했습니다.", src: "설문" },
      { d: "06.14", type: "숙박", tone: "neutral", text: "패밀리 디럭스 1박 · 결제 980,000원", src: "PMS" },
    ],
    nextBest: [
      { title: "조식 예약 시간 지정 옵션 안내", why: "유일한 부정 요인이 조식 좌석 부족", owner: "F&B" },
      { title: "가족 패키지 사전 예약 프로모션 발송", why: "재방문 주기 5주 · 만족도 상승 추세", owner: "마케팅" },
    ],
    chat: [
      { match: ["불만", "부정", "이슈"], answer: "부정 VOC는 1건입니다. 07.25 조식 좌석 부족. 나머지 9건은 긍정·중립이며 아이 동반 응대에 대한 칭찬이 반복됩니다." },
      { match: ["추천", "다음", "제안"], answer: "재방문 주기가 약 5주로 일정합니다. 다음 예약 예상 시점은 08월 말이며, 조식 시간 지정 옵션과 가족 패키지 안내가 가장 효과적입니다." },
    ],
  },
  {
    id: "G-100903", name: "Michael Chen", initials: "MC", tier: "Platinum", property: "그랜드 워커힐 서울",
    segment: "해외 비즈니스 · 단기", risk: "관찰", riskLevel: "mid", ltv: "27,500,000원",
    stays: 12, nights: 19, lastStay: "2026.07.22", avgSpend: "1,905,000원", nps: 7, sentiment: 0.05,
    tags: ["공항 픽업", "얼리 체크인", "영문 안내", "미팅룸"],
    channels: [{ k: "OTA 리뷰", v: 5 }, { k: "설문", v: 3 }, { k: "프론트 접수", v: 3 }, { k: "콜센터", v: 4 }],
    trend: [
      { t: "2월", sat: 4.1, spend: 1.8 }, { t: "3월", sat: 4.0, spend: 2.0 }, { t: "4월", sat: 4.2, spend: 1.9 },
      { t: "5월", sat: 3.9, spend: 1.7 }, { t: "6월", sat: 4.1, spend: 2.1 }, { t: "7월", sat: 4.0, spend: 1.9 },
    ],
    timeline: [
      { d: "07.22", type: "VOC", tone: "neg", text: "영문 안내가 부족해 미팅룸 위치를 찾기 어려웠습니다.", src: "OTA" },
      { d: "07.22", type: "숙박", tone: "neutral", text: "이그제큐티브 1박 · 미팅룸 3시간 · 결제 2,240,000원", src: "PMS" },
      { d: "06.18", type: "VOC", tone: "pos", text: "얼리 체크인 요청이 즉시 처리돼 만족했습니다.", src: "설문" },
    ],
    nextBest: [
      { title: "영문 사이니지 및 미팅룸 안내 개선 요청", why: "해외 고객 동일 유형 VOC 7건 누적", owner: "시설" },
      { title: "얼리 체크인 사전 확정 플래그 설정", why: "요청 100% 반복 · 처리 시 만족도 상승", owner: "프론트" },
    ],
    chat: [
      { match: ["영문", "언어", "해외"], answer: "해외 고객 대상 영문 안내 부족 VOC는 이 고객 2건, 전체 7건 누적입니다. 미팅룸·부대시설 사이니지 구간에 집중됩니다." },
    ],
  },
];

export const CUSTOMER_CHAT_FALLBACK =
  "이 고객 데이터 범위에서는 이탈 위험 근거, 선호 정보, VOC 이력, 다음 조치 추천을 답변할 수 있습니다. 좌측 타임라인의 근거 항목을 클릭하면 원본 소스도 확인할 수 있습니다.";

/* ── 4. 데이터 카탈로그 · MCP ──────────────────────────────────── */
export const CATALOG = [
  {
    id: "pms", name: "PMS (Opera Cloud)", domain: "객실 · 예약", kind: "Oracle 19c",
    host: "pms-db.internal:1521/ORCL", owner: "객실운영팀", status: "connected", pii: "높음",
    freshness: "5분 전", rows: "12.4M", sync: "5분 주기 CDC",
    tables: ["reservation", "stay_folio", "room_status", "guest_profile"],
    joins: ["guest_profile.guest_id ↔ crm.member_id"],
  },
  {
    id: "pos", name: "POS (F&B)", domain: "식음 · 결제", kind: "MySQL 8",
    host: "pos-db.internal:3306/fnb", owner: "식음부", status: "connected", pii: "중간",
    freshness: "12분 전", rows: "8.1M", sync: "15분 주기 배치",
    tables: ["order_header", "order_item", "table_turn", "outlet_master"],
    joins: ["order_header.folio_no ↔ pms.stay_folio.folio_no"],
  },
  {
    id: "crm", name: "CRM · 멤버십", domain: "고객 · 등급", kind: "PostgreSQL 15",
    host: "crm-db.internal:5432/member", owner: "마케팅팀", status: "connected", pii: "높음",
    freshness: "1시간 전", rows: "1.9M", sync: "1시간 주기 배치",
    tables: ["member", "tier_history", "benefit_usage", "consent"],
    joins: ["member.member_id ↔ voc.author_key"],
  },
  {
    id: "voc", name: "OTA · 리뷰 수집", domain: "VOC 원문", kind: "MongoDB 7",
    host: "voc-mongo.internal:27017/reviews", owner: "CX 운영팀", status: "connected", pii: "중간",
    freshness: "38분 전", rows: "620K", sync: "1시간 주기 크롤",
    tables: ["review_raw", "review_normalized", "sentiment_label"],
    joins: ["review_normalized.property_code ↔ pms.property.code"],
  },
  {
    id: "csd", name: "고객 응대 티켓", domain: "CS · 처리 이력", kind: "MSSQL 2019",
    host: "csd-db.internal:1433/ticket", owner: "고객지원팀", status: "degraded", pii: "높음",
    freshness: "6시간 전", rows: "340K", sync: "야간 배치 (지연)",
    tables: ["ticket", "ticket_reply", "sla_log"],
    joins: ["ticket.folio_no ↔ pms.stay_folio.folio_no"],
  },
  {
    id: "iot", name: "시설 IoT 센서", domain: "시설 · 환경", kind: "InfluxDB 2.7",
    host: "iot-tsdb.internal:8086/facility", owner: "시설부", status: "pending", pii: "없음",
    freshness: "연동 대기", rows: "—", sync: "실시간 스트림 (예정)",
    tables: ["temp_reading", "elevator_event", "occupancy"],
    joins: ["occupancy.zone_code ↔ pms.room_status.zone_code"],
  },
];

export const MCP_TOOLS = [
  { name: "voc.search", server: "voc-mcp", desc: "VOC 원문 검색 및 감성 필터", args: "query, period, property, sentiment", status: "ready", p95: "420ms", calls24h: 1284, scope: "read" },
  { name: "voc.cluster", server: "voc-mcp", desc: "VOC 토픽 클러스터링 및 이슈 후보 추출", args: "period, min_size", status: "ready", p95: "2.1s", calls24h: 96, scope: "read" },
  { name: "pms.stay_lookup", server: "pms-mcp", desc: "예약·투숙·객실 상태 조회", args: "guest_id, date_range", status: "ready", p95: "310ms", calls24h: 2140, scope: "read" },
  { name: "pos.spend_summary", server: "pos-mcp", desc: "식음 결제 및 좌석 회전율 집계", args: "outlet, date_range", status: "ready", p95: "680ms", calls24h: 412, scope: "read" },
  { name: "crm.member_profile", server: "crm-mcp", desc: "멤버십 등급·혜택·동의 상태 조회", args: "member_id", status: "ready", p95: "240ms", calls24h: 903, scope: "read · PII 마스킹" },
  { name: "report.compose", server: "report-mcp", desc: "일간·주간·월간 보고서 초안 생성", args: "cadence, period, sections", status: "ready", p95: "8.4s", calls24h: 34, scope: "write (초안)" },
  { name: "ticket.create", server: "csd-mcp", desc: "이슈 기반 응대 티켓 생성", args: "issue_id, owner, due", status: "review", p95: "—", calls24h: 0, scope: "write · 승인 필요" },
  { name: "facility.sensor_read", server: "iot-mcp", desc: "온도·엘리베이터·혼잡 센서 조회", args: "zone_code, metric", status: "blocked", p95: "—", calls24h: 0, scope: "read (연동 대기)" },
];

export const CATALOG_HEALTH = [
  { label: "연결 소스", value: "4 / 6" },
  { label: "MCP Tool", value: "6 / 8 ready" },
  { label: "최대 지연", value: "6시간 (CSD)" },
  { label: "PII 마스킹", value: "3개 소스 적용" },
];

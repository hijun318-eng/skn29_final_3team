export const facilities = [
  { id: "breakfast", name: "조식당", status: "danger", statusLabel: "위험", x: 59, y: 57, labelX: 67, labelY: 49, metric: "대기 18분" },
  { id: "front", name: "프런트", status: "normal", statusLabel: "정상", x: 47, y: 67, labelX: 42, labelY: 76, metric: "대기 4분" },
  { id: "parking", name: "주차장", status: "warning", statusLabel: "주의", x: 27, y: 38, labelX: 25, labelY: 29, metric: "입차 지연 9분" },
  { id: "rooms", name: "객실층", status: "normal", statusLabel: "정상", x: 49, y: 55, labelX: 43, labelY: 47, metric: "운영 안정" },
  { id: "lobby", name: "로비", status: "normal", statusLabel: "정상", x: 53, y: 70, labelX: 61, labelY: 76, metric: "운영 안정" },
  { id: "convention", name: "컨벤션", status: "warning", statusLabel: "주의", x: 39, y: 68, labelX: 29, labelY: 60, metric: "행사 입장 집중" },
];

export const facilityDetails = {
  breakfast: {
    metricLabel: "현재 평균 대기", metricValue: "18", metricUnit: "분", observedAt: "08:15~08:30", owner: "식음부",
    facts: ["단체 고객 입장 집중", "동일 시간대 좌석 회전율 감소", "대기 관련 부정 VOC 13건"],
    cause: "단체 고객 동시 입장 · 좌석 회전 지연", counter: "전체 근무 인원은 기준 범위", recentVoc: "좌석을 기다리는 시간이 길고 안내가 부족했어요.",
    actions: ["피크 시간 인력 추가", "임시 좌석 개방", "단체 입장시간 분산"],
  },
  front: {
    metricLabel: "현재 평균 대기", metricValue: "4", metricUnit: "분", observedAt: "08:15~08:30", owner: "객실부",
    facts: ["체크인 카운터 3개 정상 운영", "대기 고객 6명", "직원 응대 긍정 VOC 8건"],
    cause: "체크인 예정 고객의 일시적 집중", counter: "목표 대기시간 5분 이내 유지", recentVoc: "체크인 안내가 빠르고 친절했습니다.",
    actions: ["대기열 안내 유지", "모바일 체크인 유도", "단체 도착시간 사전 공유"],
  },
  parking: {
    metricLabel: "평균 입차 지연", metricValue: "9", metricUnit: "분", observedAt: "08:10~08:30", owner: "주차 운영팀",
    facts: ["동시 입차 차량 17대", "주차타워 1층 혼잡", "발렛 요청 전주 대비 22% 증가"],
    cause: "행사 차량과 투숙객 입차 동선 중첩", counter: "전체 주차면 점유율은 78%로 여유", recentVoc: "입구에서 어느 주차장으로 가야 하는지 헷갈렸어요.",
    actions: ["입구 안내 인력 배치", "행사 차량 동선 분리", "전광판 잔여면 갱신"],
  },
  rooms: {
    metricLabel: "미처리 객실 요청", metricValue: "3", metricUnit: "건", observedAt: "최근 30분", owner: "객실부",
    facts: ["하우스키핑 요청 7건 접수", "평균 처리시간 11분", "청결 관련 VOC 2건"],
    cause: "체크아웃 집중 후 객실 정비 요청 증가", counter: "긴급 요청은 모두 SLA 이내 처리", recentVoc: "수건 요청은 빨랐지만 욕실 점검이 필요합니다.",
    actions: ["정비 요청 우선순위 확인", "하우스키핑 1명 재배치", "욕실 점검 체크리스트 확인"],
  },
  lobby: {
    metricLabel: "현재 체류 인원", metricValue: "84", metricUnit: "명", observedAt: "08:25 기준", owner: "객실부",
    facts: ["라운지 좌석 점유율 71%", "문의 응답 평균 2분", "혼잡 관련 VOC 없음"],
    cause: "조식 종료 고객과 체크아웃 고객 동선 교차", counter: "보행 동선과 안내 데스크 운영은 정상", recentVoc: "로비가 붐볐지만 직원 안내는 원활했습니다.",
    actions: ["주요 동선 지속 관찰", "체크아웃 안내 표지 유지", "짐 보관 대기열 분리"],
  },
  convention: {
    metricLabel: "행사 입장 진행률", metricValue: "74", metricUnit: "%", observedAt: "08:20 기준", owner: "연회부",
    facts: ["행사 참석자 320명", "15분 내 180명 집중 입장", "엘리베이터 대기 6분"],
    cause: "등록 데스크와 행사장 입장 시간 중첩", counter: "행사 시작 전 잔여 수용시간 25분", recentVoc: "행사장 안내 표지가 조금 더 잘 보였으면 좋겠습니다.",
    actions: ["등록 데스크 1개 추가", "엘리베이터 안내 배치", "행사장 표지 위치 조정"],
  },
};

export const responseOptions = [
  { id: "staff", label: "운영 인력 +2명", description: "피크 시간 서비스 인력 보강", cost: 64000 },
  { id: "seats", label: "임시 좌석 +20석", description: "가용 공간에 임시 좌석 배치", cost: 32000 },
  { id: "group", label: "단체 고객 입장 15분 분산", description: "단체별 입장 시간을 순차 안내", cost: 0 },
  { id: "guide", label: "안내 직원 1명 배치", description: "대기열 분기와 좌석 안내 지원", cost: 28000 },
];

export const timeline = [
  { label: "현재", wait: 18, status: "위험", voc: 13, queue: 6, heat: 1 },
  { label: "+10분", wait: 15, status: "위험", voc: 11, queue: 5, heat: 0.86 },
  { label: "+20분", wait: 13, status: "주의", voc: 9, queue: 4, heat: 0.72 },
  { label: "+30분", wait: 11, status: "주의", voc: 8, queue: 3, heat: 0.58 },
];

export const HOTEL_COMPARISON_DATA = [
  { hotel: "SENSE PLACE 서울", shortName: "서울", vocCount: 842, negativeRate: 22.4, waitMinutes: 14, satisfaction: 4.5, resolutionRate: 84, issue: "주말 조식 혼잡", action: "조식 피크 탄력 인력 확대" },
  { hotel: "비스타 SENSE PLACE", shortName: "비스타", vocCount: 614, negativeRate: 14.8, waitMinutes: 8, satisfaction: 4.8, resolutionRate: 91, issue: "웰니스 예약 문의", action: "예약 안내 메시지 선제 발송" },
  { hotel: "그랜드 SENSE PLACE", shortName: "그랜드", vocCount: 936, negativeRate: 28.7, waitMinutes: 18, satisfaction: 4.2, resolutionRate: 76, issue: "체크인 대기 증가", action: "프런트 피크 데스크 추가 운영" },
  { hotel: "더글라스 하우스", shortName: "더글라스", vocCount: 455, negativeRate: 12.6, waitMinutes: 6, satisfaction: 4.7, resolutionRate: 94, issue: "객실 안내 편차", action: "객실 안내 체크리스트 표준화" },
];

export const HOTEL_COMPARISON_INSIGHTS = [
  { tone: "risk", title: "우선 개선 대상", hotel: "그랜드 SENSE PLACE", summary: "부정 VOC 비율 28.7%와 평균 대기 18분이 비교 호텔 중 가장 높습니다.", action: "체크인 피크 시간대 프런트 데스크 증설 효과를 우선 검증하세요." },
  { tone: "positive", title: "벤치마크 후보", hotel: "비스타 SENSE PLACE", summary: "만족도 4.8점과 조치 완료율 91%로 고객 경험과 대응 속도가 함께 안정적입니다.", action: "비스타의 사전 안내·현장 대응 방식을 다른 호텔에 적용할 수 있는지 검토하세요." },
  { tone: "watch", title: "표본 해석 주의", hotel: "더글라스 하우스", summary: "운영 지표는 양호하지만 VOC 455건으로 비교 호텔 중 표본이 가장 적습니다.", action: "낮은 부정 비율을 단정하기보다 채널별 응답률과 누락 여부를 함께 확인하세요." },
];

export const HOTEL_COMPARISON_META = {
  label: "Synthetic data",
  schemaVersion: "hotel-comparison.v1.0",
  seed: 290723,
  period: "2026.07.14 — 2026.07.20",
};

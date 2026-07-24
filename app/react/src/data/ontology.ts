/**
 * 호텔 구역/시설 온톨로지
 * @see docs/markdown/ai_docs/SensePlace_목업_v1.2.html
 */

export const ZONES: Record<string, string[]> = {
  "객실동": ["그랜드 워커힐", "비스타 워커힐", "더글라스 하우스", "애스톤 하우스"],
  "다이닝": ["피자힐", "명월관"],
  "레저·웰니스": [
    "리버파크", "테네즈 파크", "포레스트 파크",
    "힐링 포레스트", "더글라스 가든", "워커힐 골프클럽",
  ],
  "MICE·엔터": ["컨벤션 센터", "빛의 시어터", "Casino"],
  "인프라": ["주차타워", "South Gate", "East Gate"],
};

export const CATS = [
  "청결·위생", "안전", "대기·혼잡", "직원 서비스",
  "시설 고장", "소음", "온도·환경", "가격·결제", "예약·안내",
] as const;

export type ZoneName = keyof typeof ZONES;
export type CatName = (typeof CATS)[number];

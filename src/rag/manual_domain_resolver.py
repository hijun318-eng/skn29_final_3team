from __future__ import annotations

from collections.abc import Iterable


class ManualDomainResolver:
    """업무 도메인을 현재 승인된 내부지침 문서명으로 연결한다."""

    DOMAIN_TITLES = {
        "COMMON": "01 공통",
        "PRIVACY": "02 개인정보",
        "REPORT": "03 보고서",
        "NOTIFICATION_COOPERATION": "04 알림 협조",
        "INTERACTIVE_ANALYSIS": "05 대화형 분석",
        "CUSTOMER_SERVICE": "06 고객응대",
        "EXTERNAL_REVIEW": "07 외부 후기",
        "FOOD_BEVERAGE": "08 식음",
        "RESERVATION_CHECKIN_PAYMENT": "09 입실 퇴실 예약 결제",
        "LEISURE": "10 레저",
        "FACILITY": "11 시설",
        "PARKING_EVENT_LOBBY": "12 주차 행사 로비",
        "ROOM": "13 객실",
        "SAFETY": "14 안전",
        "CUSTOMER_FEEDBACK": "15 고객의견",
        "CANCELLATION_REFUND_COMPENSATION": "16 취소",
    }

    DOMAIN_TERMS = {
        "COMMON": ("공통 업무", "공통 지침"),
        "PRIVACY": ("개인정보", "정보 유출", "잘못 전달"),
        "REPORT": ("보고서",),
        "NOTIFICATION_COOPERATION": ("알림 협조", "알림·협조", "공지", "협조 요청"),
        "INTERACTIVE_ANALYSIS": ("대화형 분석",),
        "CUSTOMER_SERVICE": ("고객응대", "고객 응대", "직원 응대", "서비스 불만", "고객 불만"),
        "EXTERNAL_REVIEW": ("외부 후기", "온라인 후기", "리뷰"),
        "FOOD_BEVERAGE": ("식음", "주방", "음식", "위생"),
        "RESERVATION_CHECKIN_PAYMENT": ("예약", "체크인", "체크아웃", "입실", "퇴실", "결제"),
        "LEISURE": ("레저", "수영장", "골프", "스파"),
        "FACILITY": ("시설", "설비", "고장", "장애", "누수"),
        "PARKING_EVENT_LOBBY": ("주차", "행사", "로비"),
        "ROOM": ("객실", "청결", "욕실", "냄새", "곰팡이", "해충", "벌레"),
        "SAFETY": ("안전", "쓰러", "실신", "부상", "화재", "감전", "응급", "호흡", "출혈", "사고"),
        "CUSTOMER_FEEDBACK": ("고객의견", "고객 의견", "voc"),
        "CANCELLATION_REFUND_COMPENSATION": ("취소", "환불", "보상", "노쇼", "위약금"),
    }

    _ROOM_ISSUE_TERMS = ("청결", "욕실", "냄새", "곰팡이", "해충", "벌레", "객실 문제")
    _RESERVATION_DETAIL_TERMS = (
        "예약 변경",
        "예약 불일치",
        "객실 유형",
        "체크인",
        "체크아웃",
        "입실",
        "퇴실",
        "결제",
    )

    def resolve(
        self,
        question: str,
        explicit_domains: Iterable[str] = (),
    ) -> tuple[str, ...]:
        explicit = self._valid_domains(explicit_domains)
        if explicit:
            return explicit

        text = " ".join(question.lower().split())
        ranked: list[tuple[int, int, str]] = []
        for order, (domain, terms) in enumerate(self.DOMAIN_TERMS.items()):
            positions = [text.find(term) for term in terms if text.find(term) >= 0]
            if positions:
                ranked.append((min(positions), order, domain))
        resolved = [domain for _, _, domain in sorted(ranked)]

        if "SAFETY" in resolved and "ROOM" in resolved:
            if not any(term in text for term in self._ROOM_ISSUE_TERMS):
                resolved.remove("ROOM")
        cancellation = "CANCELLATION_REFUND_COMPENSATION"
        reservation = "RESERVATION_CHECKIN_PAYMENT"
        if cancellation in resolved and reservation in resolved:
            if not any(term in text for term in self._RESERVATION_DETAIL_TERMS):
                resolved.remove(reservation)
        return tuple(resolved[:3])

    def titles_for(self, domains: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            self.DOMAIN_TITLES[domain]
            for domain in self._valid_domains(domains)
        )

    def _valid_domains(self, domains: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                domain.strip().upper()
                for domain in domains
                if domain and domain.strip().upper() in self.DOMAIN_TITLES
            )
        )

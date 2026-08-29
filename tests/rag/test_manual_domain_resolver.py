import unittest

from src.rag.manual_domain_resolver import ManualDomainResolver


class ManualDomainResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = ManualDomainResolver()

    def test_safety_incident_wins_over_room_location(self) -> None:
        actual = self.resolver.resolve("고객이 객실에서 쓰러졌어. 지금 뭘 해야 해?")
        self.assertEqual(("SAFETY",), actual)

    def test_explicit_comparison_domains_are_preserved(self) -> None:
        actual = self.resolver.resolve(
            "각각의 즉시 보고 기준을 알려줘",
            ("FACILITY", "SAFETY"),
        )
        self.assertEqual(("FACILITY", "SAFETY"), actual)

    def test_unknown_explicit_domain_is_rejected(self) -> None:
        self.assertEqual((), self.resolver.resolve("일반 질문", ("UNKNOWN",)))

    def test_refund_question_routes_to_cancellation_manual(self) -> None:
        actual = self.resolver.resolve("예약 취소하면 환불 가능한가?")
        self.assertEqual(("CANCELLATION_REFUND_COMPENSATION",), actual)

    def test_comparison_order_follows_question(self) -> None:
        actual = self.resolver.resolve("시설 장애와 안전사고 대응은 어떻게 달라?")
        self.assertEqual(("FACILITY", "SAFETY"), actual)


if __name__ == "__main__":
    unittest.main()

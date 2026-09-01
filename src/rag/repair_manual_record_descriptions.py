"""매뉴얼 PDF의 반복 기록 문구를 필드별 기록 목적 설명으로 안전하게 교체한다."""

from __future__ import annotations

import argparse
import io
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf._text_extraction import mult
from pypdf.generic import ContentStream
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


REPEATED_TEXT = "업무 수행, 검증, 감사 및 인계를 위해 구조화하여 기록한다."
FONT_NAME = "MalgunGothic"
FONT_PATH = Path(r"C:\Windows\Fonts\malgun.ttf")

FIELD_PURPOSES = {
    "access_policy_id": "적용한 접근 권한 정책 식별자",
    "acknowledged_at": "담당자가 알림 또는 요청을 확인한 시각",
    "action_log": "수행 조치와 변경 이력을 시간순으로 기록",
    "active_staff_count": "해당 시점 실제 투입 가능 인원 수",
    "alert_id": "운영 알림의 고유 식별자",
    "alert_status": "알림의 현재 확인·해제 상태",
    "alert_type": "알림 발생 원인과 분류 유형",
    "approval_status": "검토·승인의 현재 처리 상태",
    "approved_release_by": "운영 재개를 승인한 책임자 식별자",
    "asset_type": "보호·관리 대상 자산의 유형",
    "assigned_team": "조치 수행을 맡은 부서 또는 팀",
    "assignment_status": "담당자 배정과 인수 확인 상태",
    "booking_channel": "예약이 접수된 판매·중개 채널",
    "calibration_status": "측정 장비의 교정 완료 여부와 상태",
    "capacity": "시설·좌석·객실의 운영 가능 수량",
    "case_id": "문의·검토 건의 고유 식별자",
    "closed_at": "사건 또는 요청을 최종 종결한 시각",
    "collected_at": "외부 자료 또는 데이터를 수집한 시각",
    "control_status": "위험 구역 통제와 해제 상태",
    "conversation_id": "업무 대화의 고유 식별자",
    "customer_condition": "확인 시점 고객의 건강·안전 상태",
    "customer_consent": "고객 동의 여부와 확인 범위",
    "customer_notice_at": "고객에게 결과나 진행상태를 안내한 시각",
    "customer_statement": "고객이 설명한 사실과 요구사항 원문",
    "data_source_ids": "조회에 사용한 원천 데이터 식별자 목록",
    "decision_code": "승인·보류·반려 등 최종 판단 코드",
    "department_id": "담당 또는 협조 부서의 식별자",
    "detected_at": "이상 징후나 사건을 최초 발견한 시각",
    "device_id": "점검·측정에 사용한 장비 식별자",
    "employee_statement": "관련 직원이 확인한 사실과 진술",
    "escalated_at": "상위 관리자 또는 전문 담당에게 보고한 시각",
    "estimated_wait": "현재 기준 예상 대기 시간",
    "facility_id": "사건이 발생한 시설·영업장 식별자",
    "fault_symptom": "현장에서 관찰한 설비 이상 증상",
    "food_safety_flag": "식품안전 절차 전환 필요 여부",
    "handover_at": "다음 담당자에게 업무를 인계한 시각",
    "impact_scope": "고객·시설·운영에 미친 영향 범위",
    "improvement_action": "재발 방지를 위해 확정한 개선 조치",
    "incident_status": "운영사건의 현재 처리 단계",
    "incident_type": "운영사건의 원인·영향 분류",
    "inspection_result": "현장 점검 결과와 확인 근거",
    "intent": "질문 또는 요청에서 판별한 업무 목적",
    "internal_match_ids": "교차 확인한 내부 사건·기록 식별자",
    "is_partial": "조회 결과가 일부만 제공되었는지 여부",
    "manager_decision": "관리자가 확정한 조치와 판단 사유",
    "manual_id": "판단에 적용한 업무 매뉴얼 식별자",
    "masked_payment_method": "마스킹 처리한 결제수단 식별 정보",
    "masking_rule_version": "개인정보 마스킹에 적용한 규칙 버전",
    "measured_at": "시설·환경 값을 실제 측정한 시각",
    "measured_by": "측정을 수행하거나 확인한 담당자",
    "measured_value": "장비로 확인한 측정값과 단위",
    "menu_id": "주문·위생 확인 대상 메뉴 식별자",
    "message_id": "접수 메시지 또는 알림의 고유 식별자",
    "metric_ids": "보고서·분석에 사용한 지표 식별자 목록",
    "metric_type": "측정·집계한 운영지표 유형",
    "normalization_at": "외부 평점이나 지표를 표준화한 시각",
    "normalized_rating": "공통 척도로 변환한 평점 값",
    "observed_at": "현장 상태를 직접 확인한 시각",
    "observed_condition": "확인자가 직접 관찰한 현장 상태",
    "occurred_at": "사건 또는 고객 불편이 발생한 시각",
    "official_sop_id": "우선 적용한 공식 절차 식별자",
    "operation_status": "시설·서비스의 현재 운영 상태",
    "order_id": "확인 대상 주문의 고유 식별자",
    "period_end": "조회·분석 대상 기간의 종료 시점",
    "period_start": "조회·분석 대상 기간의 시작 시점",
    "pii_types": "포함되거나 노출된 개인정보 유형 목록",
    "preserved_item_id": "증거 보전을 위해 분리한 물품 식별자",
    "privacy_flag_id": "개인정보 포함 여부 표시 식별자",
    "privacy_level": "정보의 민감도와 접근 제한 등급",
    "query_template_id": "실행한 승인 SQL 템플릿 식별자",
    "queue_count": "확인 시점 대기 고객·차량 건수",
    "rate_plan_id": "예약에 적용된 요금제 식별자",
    "rating_scale": "원천 리뷰에 사용된 평점 척도",
    "received_at": "요청·문의·리뷰가 시스템에 접수된 시각",
    "received_confirmation": "고객 또는 인계 대상자의 수신 확인 여부",
    "recipient_scope": "알림·보고서의 허용 수신 대상 범위",
    "reference_rule_id": "판단에 참고한 정책·규칙 식별자",
    "relation_type": "사건·문서 사이의 연결 관계 유형",
    "report_id": "생성·검토한 보고서의 고유 식별자",
    "report_status": "보고서의 초안·검토·확정 상태",
    "report_version": "보고서 변경 이력을 구분하는 버전",
    "request_type": "고객 또는 내부 요청의 분류 유형",
    "reservation_id": "확인 대상 예약의 고유 식별자",
    "restart_approved_by": "시설 운영 재개를 승인한 책임자",
    "restoration_type": "복구·재정비·교체 등 정상화 유형",
    "retention_rule_id": "기록 보존·삭제에 적용한 규칙 식별자",
    "retry_count": "실패 후 재시도한 누적 횟수",
    "review_id": "외부 또는 내부 리뷰의 고유 식별자",
    "reviewed_by": "내용과 근거를 최종 검토한 담당자",
    "room_status": "조치 후 객실의 사용 가능 상태",
    "room_token": "객실 정보를 비식별 처리한 참조 토큰",
    "route_version": "질문·사건 분류에 적용한 라우팅 버전",
    "row_count": "조회 결과에 포함된 데이터 행 수",
    "safety_control": "즉시 시행한 안전 통제 조치",
    "safety_risk": "확인된 안전 위험 유형과 심각도",
    "sample_size": "평점·감성 집계에 사용한 리뷰 수",
    "sentiment_label": "리뷰 문장에서 판별한 감성 분류",
    "served_at": "음식·서비스가 고객에게 제공된 시각",
    "service_status": "서비스 요청의 현재 처리 상태",
    "severity": "확인된 사건의 최종 심각도 등급",
    "severity_final": "관리자가 확정한 최종 심각도",
    "severity_suggested": "자동 분류가 제안한 심각도 후보",
    "shared_scope": "문서·결과가 실제 공유된 대상 범위",
    "source": "리뷰·요청·자료가 들어온 원천",
    "source_channel": "고객 의견이나 요청이 접수된 채널",
    "source_systems": "근거 조회에 사용한 원천 시스템 목록",
    "submission_type": "문의·불만·요청 등 접수 유형",
    "suppression_reason": "중복 알림을 억제한 사유",
    "threshold_policy_id": "알림 임계값에 적용한 정책 식별자",
    "topic_code": "질문·VOC·리뷰의 업무 주제 코드",
    "transaction_id": "결제 거래의 고유 식별자",
    "transaction_status": "결제 승인·취소·매입 처리 상태",
    "unit": "측정값과 지표에 적용한 단위",
    "witness_statement": "목격자가 확인한 사실과 진술",
    "work_order_id": "시설 점검·복구 작업지시 식별자",
    "written_at": "리뷰 또는 기록이 최초 작성된 시각",
    "zone_id": "시설 내 발생 구역의 식별자",
}


@dataclass(frozen=True)
class Replacement:
    """교체할 필드 설명과 PDF 텍스트 기준점 좌표를 나타내는 불변 항목이다."""

    field: str
    description: str
    x: float
    baseline_y: float


class ManualRecordDescriptionRepairer:
    """PDF content stream의 반복 문구만 제거하고 한글 필드 설명 overlay를 합성한다.

    Malgun Gothic 글꼴이 없거나 필드·페이지·교체 수가 원문과 맞지 않으면 결과물을
    확정하지 않고 예외로 종료한다.
    """

    def __init__(self) -> None:
        if not FONT_PATH.is_file():
            raise FileNotFoundError(f"Korean font not found: {FONT_PATH}")
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))

    def repair(self, source: Path, target: Path) -> int:
        """원본 PDF의 반복 문구를 교체해 대상 파일에 쓰고 검증된 교체 건수를 반환한다.

        대상이 원본과 같으면 임시 파일을 검증한 뒤 원자적으로 교체하며, 남은 반복
        문구나 누락된 설명이 발견되면 ``ValueError``를 발생시킨다.
        """

        replacements = self._find_replacements(source)
        if not any(replacements):
            return 0
        writer = PdfWriter(clone_from=source)
        if len(writer.pages) != len(replacements):
            raise ValueError(f"page count mismatch: {source.name}")
        replaced = 0
        for page, page_replacements in zip(writer.pages, replacements):
            if page_replacements:
                replaced += self._remove_original_text(page, writer, page_replacements)
                page.merge_page(self._overlay(page, page_replacements))
        if replaced != sum(map(len, replacements)):
            raise ValueError(f"replacement count mismatch: {source.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        write_target = (
            target.with_suffix(".repairing.pdf")
            if source.resolve() == target.resolve()
            else target
        )
        with write_target.open("wb") as stream:
            writer.write(stream)
        self._verify(write_target, replaced)
        if write_target != target:
            write_target.replace(target)
        return replaced

    def _find_replacements(self, path: Path) -> list[list[Replacement]]:
        pages: list[list[Replacement]] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                words = page.extract_words()
                items = []
                for match in page.search(REPEATED_TEXT):
                    center = (match["top"] + match["bottom"]) / 2
                    left = [
                        word for word in words
                        if word["x1"] < match["x0"] - 5
                        and abs((word["top"] + word["bottom"]) / 2 - center) < 2
                    ]
                    if not left:
                        raise ValueError(f"field not found: {path.name} page {page.page_number}")
                    field = max(left, key=lambda word: word["x1"])["text"]
                    if field not in FIELD_PURPOSES:
                        raise ValueError(f"description missing for field: {field}")
                    baseline = float(page.height) - match["bottom"] + 0.3 * (
                        match["bottom"] - match["top"]
                    )
                    items.append(Replacement(field, FIELD_PURPOSES[field], match["x0"], baseline))
                pages.append(items)
        return pages

    @staticmethod
    def _remove_original_text(page, pdf: PdfWriter, items: list[Replacement]) -> int:
        content = ContentStream(page.get_contents(), pdf)
        ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        stack: list[list[float]] = []
        matched_block = False
        removed_blocks = 0
        operations = []
        for operands, operator in content.operations:
            if operator == b"q":
                stack.append(ctm.copy())
            elif operator == b"Q":
                ctm = stack.pop()
            elif operator == b"cm":
                ctm = mult([float(value) for value in operands[:6]], ctm)
            elif operator == b"BT":
                matched_block = False
            elif operator == b"Tm":
                matrix = mult([float(value) for value in operands[:6]], ctm)
                matched_block = any(
                    abs(matrix[4] - item.x) < 0.8
                    and abs(matrix[5] - item.baseline_y) < 0.8
                    for item in items
                )
                removed_blocks += int(matched_block)
            elif operator == b"ET":
                matched_block = False
            if matched_block and operator in {b"Tj", b"TJ"}:
                continue
            operations.append((operands, operator))
        content.operations = operations
        page.replace_contents(content)
        return removed_blocks

    @staticmethod
    def _overlay(page, items: list[Replacement]):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        buffer = io.BytesIO()
        layer = canvas.Canvas(buffer, pagesize=(width, height))
        layer.setFillColorRGB(0.12549, 0.145098, 0.156863)
        for item in items:
            font_size = 7.8
            while pdfmetrics.stringWidth(item.description, FONT_NAME, font_size) > 305:
                font_size -= 0.2
            layer.setFont(FONT_NAME, font_size)
            layer.drawString(item.x, item.baseline_y, item.description)
        layer.save()
        buffer.seek(0)
        return PdfReader(buffer).pages[0]

    @staticmethod
    def _verify(path: Path, expected: int) -> None:
        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        if REPEATED_TEXT in text:
            raise ValueError(f"repeated text remains: {path.name}")
        found = sum(text.count(description) for description in FIELD_PURPOSES.values())
        if found < expected:
            raise ValueError(f"replacement text missing: {path.name}")


def main() -> None:
    """입력 디렉터리의 선택된 PDF를 일괄 보정하고 파일·교체 건수를 출력한다."""

    parser = argparse.ArgumentParser(description="매뉴얼 기록 목적 반복 문구를 필드별 설명으로 교체")
    parser.add_argument("manuals_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--pattern", default="*.pdf")
    args = parser.parse_args()
    repairer = ManualRecordDescriptionRepairer()
    total = 0
    files = 0
    for source in sorted(args.manuals_dir.glob(args.pattern)):
        count = repairer.repair(source, args.output_dir / source.name)
        if count:
            files += 1
            total += count
            print(f"{source.name}: {count}")
    print(f"repaired_files={files} replacements={total}")


if __name__ == "__main__":
    main()

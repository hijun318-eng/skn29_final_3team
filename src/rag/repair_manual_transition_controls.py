"""매뉴얼 PDF의 공통 상태전환 문구를 문서별 승인·보류·종결 통제로 교체한다."""

from __future__ import annotations

import argparse
import io
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf._text_extraction import mult
from pypdf.generic import ContentStream
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
REPEATED_TEXT = "허용된 역할만 전환한다. 이전 상태, 변경자, 변경 시각, 사유와 필수 근거를 이력으로 남긴다. 자동 전환은 승인된 규칙에 한정한다."
SEARCH_TEXT = "허용된 역할만 전환한다."
FONT_NAME = "MalgunGothic"
FONT_PATH = Path(r"C:\Windows\Fonts\malgun.ttf")
TRANSITION_CONTROLS = {
    "POL-COM-001": (
        "주관 담당자가 접수·배정·조치·해결 근거를 확인해 단계별 변경한다.",
        "주관 담당자가 대기사유·대상·재확인 시각을 입력한 경우에만 적용한다.",
        "개인정보·안전 책임자의 확인 결과가 등록돼야 종결 심사로 넘긴다.",
    ),
    "POLICY-PRV-001": (
        "개인정보 책임자가 목적·권한·최소수집 위반 가능성을 확인해 제한한다.",
        "오전송·무단조회·외부노출 정황을 보안 책임자가 확인하면 사고 절차로 넘긴다.",
        "보존 책임자가 만료·법적보전 여부를 확인해 삭제 또는 보존을 결정한다.",
    ),
    "REPORT-RULE-001": (
        "작성·검토·승인 담당자가 수치·출처·권한을 순서대로 확인한다.",
        "검토자가 데이터 오류나 근거 부족을 기록한 경우 보류 또는 반려한다.",
        "승인본은 직접 수정하지 않고 승인 책임자가 새 버전 생성을 허가한다.",
    ),
    "REPORT-RULE-002": (
        "작성자가 제출하고 검토자가 근거를 확인한 뒤 승인 책임자가 확정한다.",
        "검토자가 보완사항·반려사유·재검토 조건을 기록해야 전환한다.",
        "승인 책임자가 변경 필요성을 확인하면 기존본을 보존하고 새 초안을 만든다.",
    ),
    "REPORT-RULE-003": (
        "작성 담당자가 권한·데이터 범위를 검증한 뒤 초안을 만들고 사람 검토로 넘긴다.",
        "접근정책 불일치가 확인되면 보안 담당자가 해제하기 전까지 차단한다.",
        "역할 변경 시 권한 책임자가 기존 보고서의 조회·공유 범위를 다시 승인한다.",
    ),
    "SOP-ALT-001": (
        "수신 담당자가 확인하고 조치 담당자가 해결 근거를 등록한 뒤 종결한다.",
        "알림 담당자가 중복 대상·비교 근거·억제 사유를 확인한 경우만 억제한다.",
        "미확인·전달 실패·심각도 상승 근거가 있으면 운영 관리자가 상위 보고한다.",
    ),
    "SOP-ALT-002": (
        "요청 부서와 협조 부서가 접수·착수·완료 결과를 단계별로 확인한다.",
        "협조 부서 책임자가 거절 사유와 대체 조치를 기록해야 반려한다.",
        "요청 책임자가 취소 사유와 진행 영향 확인 후 취소하며 완료 건은 취소하지 않는다.",
    ),
    "SOP-CHAT-001": (
        "질문 분류자가 범위와 권한을 확인한 뒤 승인된 조회만 실행 단계로 넘긴다.",
        "기간·대상·지표가 부족하면 담당자가 누락 조건을 제시하고 답변을 보류한다.",
        "권한·정의·데이터 부재를 확인한 담당자가 차단 사유와 해제 조건을 남긴다.",
    ),
    "SOP-CHAT-002": (
        "분석 담당자가 결과·단위·출처를 검증한 뒤에만 사용자에게 제시한다.",
        "조회 누락 범위와 영향이 표시된 경우에만 부분 결과로 제공한다.",
        "수치·권한·근거 검증 실패 시 검토자가 공개를 차단하고 재검증을 요청한다.",
    ),
    "SOP-CHAT-003": (
        "대화 소유자가 업무 종료와 보존 필요성을 확인한 뒤 보관 상태로 바꾼다.",
        "감사·분쟁·보전 필요성을 책임자가 확인하면 잠금 또는 보존을 적용한다.",
        "개인정보·법적보전 검토와 승인 기록이 모두 있어야 삭제한다.",
    ),
    "SOP-CS-001": (
        "응대 관리자가 사실확인·답변·개선조치와 고객 안내 결과를 확인해 종결한다.",
    ),
    "SOP-EXT-001": (
        "데이터 담당자가 수집 출처·표본·척도를 검증한 뒤 집계와 검토로 넘긴다.",
        "출처·표본·중복에 이상이 있으면 검증 담당자가 격리 사유를 기록한다.",
        "기준 충족 근거를 관리자가 확인한 경우에만 운영 알림을 발행한다.",
    ),
    "SOP-EXT-002": (
        "분석 담당자가 후보 매뉴얼을 제시하고 관리자가 확인한 뒤 내부 점검을 요청한다.",
        "현장 담당자가 실제 사건의 시간·장소·영향을 확인하면 사건으로 등록한다.",
        "근거 부족과 재확인 조건을 관리자가 기록한 경우 모니터링을 종료한다.",
    ),
    "SOP-FNB-001": (
        "현장 관리자가 대기량·동선·투입인원을 확인해 혼잡 대응 단계를 변경한다.",
        "피난·보행 동선 침해를 안전 담당자가 확인하면 즉시 안전 절차로 격상한다.",
    ),
    "SOP-FNB-002": (
        "매장 관리자가 사실·보상권한·고객 확인을 순서대로 검토한 뒤 종결한다.",
    ),
    "SOP-FNB-003": (
        "현장 책임자가 고객 안전·증거보전 후 식품안전 책임자에게 공식 인계한다.",
        "공식 조사 결과와 후속조치 확인을 책임자가 등록한 경우에만 종결한다.",
    ),
    "SOP-FRT-001": (
        "프런트 관리자가 대기량·인력·동선의 정상화 근거를 확인해 단계를 변경한다.",
        "예약 원장 비교와 관리자 결정을 거쳐 고객 확인 결과가 있어야 종결한다.",
    ),
    "SOP-FRT-002": (
        "재무 담당자가 거래 원장과 승인내역을 검증하고 고객 안내 후 종결한다.",
    ),
    "SOP-LSR-001": (
        "시설 책임자가 안전·측정·조치·재측정 근거를 확인해 운영 재개를 결정한다.",
    ),
    "SOP-MNT-001": (
        "시설 책임자가 통제·점검·복구·모니터링 결과를 확인한 뒤 종결한다.",
    ),
    "SOP-OPS-001": (
        "주차 관리자가 대기량·동선·통제 효과를 확인해 정상화 단계를 변경한다.",
        "사고나 보행 위험을 안전 담당자가 확인하면 일반 혼잡 절차에서 분리한다.",
    ),
    "SOP-OPS-002": (
        "행사 책임자가 계획·입장량·통제·잔여대기 확인을 거쳐 종료한다.",
    ),
    "SOP-OPS-003": (
        "로비 관리자가 밀집도·동선·대기시간을 확인해 혼잡 상태를 변경한다.",
        "수하물 담당자가 보관표와 인수자를 대조하고 인수 확인 후 완료한다.",
        "표식·수량·인수자 불일치가 있으면 관리자가 인계를 중지하고 조사한다.",
    ),
    "SOP-PRV-001": (
        "개인정보 담당자가 접근제한·마스킹을 확인한 자료만 업무에 사용하도록 승인한다.",
        "오전송·노출 정황을 확인하면 즉시 사용을 중지하고 사고 대응으로 넘긴다.",
    ),
    "SOP-PRV-002": (
        "개인정보 책임자가 확산차단·영향평가·통지검토·재발방지를 확인해 종결한다.",
    ),
    "SOP-ROOM-001": (
        "객실 관리자가 고객 동의·점검·재점검·고객 확인 근거를 확인해 종결한다.",
    ),
    "SOP-ROOM-002": (
        "객실 담당자가 접수·준비·전달을 기록하고 고객 수령 확인 후 완료한다.",
        "재고·전달 실패·취소 사유를 담당자가 확인하고 필요 시 관리자에게 격상한다.",
    ),
    "SOP-ROOM-003": (
        "객실 관리자가 안전확인·시설점검·수리·재점검 결과를 확인해 종결한다.",
    ),
    "SOP-SAF-001": (
        "안전 책임자가 공식 절차 가동·긴급 인계·현장보전·사후검토 후 종결한다.",
    ),
    "SOP-SAF-002": (
        "안전 책임자와 긴급기관이 대피·통제·인계를 확인하고 재개 승인 후 종결한다.",
    ),
    "SOP-SAF-003": (
        "안전 담당자가 구역통제·조치·안전 재확인을 완료한 뒤 해제와 종결을 승인한다.",
    ),
    "SOP-VOC-001": (
        "VOC 담당자가 원문 검증·마스킹·분류를 확인한 건만 담당 부서로 전달한다.",
        "필수 정보 오류나 접수 대상 아님을 확인한 담당자가 반려 사유를 기록한다.",
        "분류·권한 판단이 불확실하면 관리자가 검토 사유와 필요한 근거를 지정한다.",
    ),
    "SOP-VOC-002": (
        "VOC 담당자가 유사 근거를 제시하고 관리자가 관계를 확인한 뒤 연결한다.",
        "동일 사건 근거가 부족하면 별도 사건을 유지하고 참고 연결만 남긴다.",
        "재발 시 관리자가 기존 사건 재오픈과 신규 사건 생성을 근거로 선택한다.",
    ),
    "SOP-VOC-003": (
        "운영 관리자가 업무영역과 권한을 확인해 배정하고 담당자가 인수한다.",
        "담당 부서가 반려·재배정 사유를 기록하면 관리자가 새 담당자를 지정한다.",
        "기한 내 인수 확인이 없으면 운영 관리자가 상위 책임자에게 격상한다.",
    ),
    "SOP-VOC-004": (
        "주관 담당자가 접수·배정·조치·해결 근거를 확인해 단계별 변경한다.",
        "대기사유 해소와 재확인 결과를 담당자가 기록해야 처리를 재개한다.",
        "관리자가 재오픈 사유와 미해결 근거를 승인한 경우에만 진행 상태로 돌린다.",
        "접수 오류는 취소하고 동일 사건 근거가 확인된 건만 중복 연결한다.",
    ),
}
@dataclass(frozen=True)
class Replacement:
    """PDF에 덧그릴 문서별 상태전환 설명과 원문 기준점 좌표를 보존한다."""

    description: str
    x: float
    baseline_y: float
class ManualTransitionControlRepairer:
    """매뉴얼 ID에 승인된 전환 통제를 매핑해 PDF content stream과 overlay를 갱신한다.

    지원되지 않는 매뉴얼 ID, 예상과 다른 전환 문구 수, 글꼴 부재 또는 출력 검증
    실패는 예외로 종료해 일부 교체본을 정상 산출물로 사용하지 않게 한다.
    """

    def __init__(self) -> None:
        if not FONT_PATH.is_file():
            raise FileNotFoundError(f"Korean font not found: {FONT_PATH}")
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
    def repair(self, source: Path, target: Path) -> int:
        """원본의 공통 전환 문구를 매뉴얼별 통제로 교체하고 검증된 건수를 반환한다.

        원본을 덮어쓰는 경우 별도 임시 PDF를 먼저 검증하며, content stream에서 제거한
        수와 삽입할 통제 수가 다르면 결과 파일을 확정하지 않는다.
        """

        replacements = self._find_replacements(source)
        if not any(replacements):
            return 0
        writer = PdfWriter(clone_from=source)
        replaced = 0
        for page, items in zip(writer.pages, replacements):
            if items:
                replaced += self._remove_original_text(page, writer, items)
                page.merge_page(self._overlay(page, items))
        expected = sum(map(len, replacements))
        if replaced != expected:
            raise ValueError(f"replacement count mismatch: {source.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        write_target = target.with_suffix(".repairing.pdf") if source.resolve() == target.resolve() else target
        with write_target.open("wb") as stream:
            writer.write(stream)
        self._verify(write_target, expected)
        if write_target != target:
            write_target.replace(target)
        return expected
    def _find_replacements(self, path: Path) -> list[list[Replacement]]:
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                matches = page.search(SEARCH_TEXT)
                if not matches:
                    pages.append([])
                    continue
                first_line = (page.extract_text() or "").splitlines()[0]
                manual_id = re.match(r"[A-Z]+(?:-[A-Z]+)*-\d{3}", first_line)
                if not manual_id or manual_id.group() not in TRANSITION_CONTROLS:
                    raise ValueError(f"manual id not found: {path.name} page {page.page_number}")
                descriptions = TRANSITION_CONTROLS[manual_id.group()]
                if len(matches) != len(descriptions):
                    raise ValueError(f"transition count mismatch: {manual_id.group()}")
                items = []
                for match, description in zip(matches, descriptions):
                    baseline = float(page.height) - match["bottom"] + 0.3 * (match["bottom"] - match["top"])
                    items.append(Replacement(description, match["x0"], baseline))
                pages.append(items)
        return pages
    @staticmethod
    def _remove_original_text(page, pdf: PdfWriter, items: list[Replacement]) -> int:
        content = ContentStream(page.get_contents(), pdf)
        ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        stack, operations = [], []
        matched_block = False
        removed = 0
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
                matched_block = any(abs(matrix[4] - item.x) < 0.8 and abs(matrix[5] - item.baseline_y) < 0.8 for item in items)
                removed += int(matched_block)
            elif operator == b"ET":
                matched_block = False
            if not (matched_block and operator in {b"Tj", b"TJ"}):
                operations.append((operands, operator))
        content.operations = operations
        page.replace_contents(content)
        return removed
    @staticmethod
    def _overlay(page, items: list[Replacement]):
        buffer = io.BytesIO()
        layer = canvas.Canvas(buffer, pagesize=(float(page.mediabox.width), float(page.mediabox.height)))
        layer.setFillColorRGB(0.12549, 0.145098, 0.156863)
        for item in items:
            words = item.description.split()
            lines = [""]
            for word in words:
                candidate = f"{lines[-1]} {word}".strip()
                if pdfmetrics.stringWidth(candidate, FONT_NAME, 7.5) <= 305:
                    lines[-1] = candidate
                else:
                    lines.append(word)
            if len(lines) > 2:
                raise ValueError(f"description exceeds two lines: {item.description}")
            layer.setFont(FONT_NAME, 7.5)
            for index, line in enumerate(lines):
                layer.drawString(item.x, item.baseline_y - index * 9, line)
        layer.save()
        buffer.seek(0)
        return PdfReader(buffer).pages[0]
    @staticmethod
    def _verify(path: Path, expected: int) -> None:
        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        compact = re.sub(r"\s+", "", text)
        if re.sub(r"\s+", "", REPEATED_TEXT) in compact or SEARCH_TEXT in text:
            raise ValueError(f"repeated transition text remains: {path.name}")
        found = sum(text.count(description) for descriptions in TRANSITION_CONTROLS.values() for description in descriptions)
        if found < expected:
            raise ValueError(f"replacement text missing: {path.name}")
def main() -> None:
    """입력 디렉터리의 PDF를 문서별 전환 통제로 일괄 보정하고 처리 건수를 출력한다."""

    parser = argparse.ArgumentParser(description="매뉴얼 상태 전환 통제를 업무별 조건으로 교체")
    parser.add_argument("manuals_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--pattern", default="*.pdf")
    args = parser.parse_args()
    repairer = ManualTransitionControlRepairer()
    files = total = 0
    for source in sorted(args.manuals_dir.glob(args.pattern)):
        count = repairer.repair(source, args.output_dir / source.name)
        if count:
            files += 1
            total += count
            print(f"{source.name}: {count}")
    print(f"repaired_files={files} replacements={total}")
if __name__ == "__main__":
    main()

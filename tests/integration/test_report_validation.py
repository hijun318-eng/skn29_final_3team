import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_reports",
    ROOT / ".agents/skills/update-project-reports/scripts/validate_reports.py",
)
validate_reports = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_reports)


class ReportValidationTest(unittest.TestCase):
    def test_presentation_daily_summary_requires_every_member(self) -> None:
        headings = "\n\n".join(
            f"### {name} (`{branch}`)\n\n- 보고 없음"
            for name, branch in validate_reports.MEMBERS.items()
        )
        text = (
            "# 20260730 데일리 스크럼\n\n"
            "## 오늘 팀 진행 상황\n\n- 진행 내용\n\n"
            "## 팀원별 발표 메모\n\n"
            f"{headings}\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "20260730.md"
            path.write_text(text, encoding="utf-8")
            self.assertEqual([], validate_reports.validate(path))

            path.write_text(
                text.replace("### 윤대성 (`daesung`)", ""), encoding="utf-8"
            )
            self.assertTrue(
                any("윤대성" in error for error in validate_reports.validate(path))
            )

    def test_weekly_report_checks_date_and_weekday(self) -> None:
        text = """# 3주차 주간보고

## 20260727 ~ 20260730 (3주차)

작성자: 3팀

## 이번 주 진행 상황

- 진행 내용

## 이번 주에 진행한 것

### 화요일 (20260727)

- 주요 작업

## 앞으로 진행할 내용

- 다음 작업
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "3주차" / "주간보고.md"
            path.parent.mkdir()
            path.write_text(text, encoding="utf-8")
            self.assertTrue(
                any(
                    "날짜와 요일이 다릅니다" in error
                    for error in validate_reports.validate(path)
                )
            )


if __name__ == "__main__":
    unittest.main()

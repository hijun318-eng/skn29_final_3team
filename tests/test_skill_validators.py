from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


reports = load(
    "validate_reports",
    ".agents/skills/update-project-reports/scripts/validate_reports.py",
)
documents = load(
    "check_document_policy",
    ".agents/skills/manage-project-documents/scripts/check_document_policy.py",
)
wbs = load(
    "validate_wbs",
    ".agents/skills/update-project-wbs/scripts/validate_wbs.py",
)


class SkillValidatorTests(unittest.TestCase):
    def test_daily_report_ignores_separator_blank_and_selects_requested_date(self):
        text = """# 일일보고

> 안내

## 20260727

- 하나
- 둘
- 셋

## 20260726

- 하나
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "일일보고.md"
            path.write_text(text, encoding="utf-8")
            self.assertEqual(reports.validate(path), [])
            self.assertEqual(reports.validate(path, "20260726"), [])

    def test_document_links_ignore_fenced_examples(self):
        text = """```md
[예시](missing.png)
```
[실제](present.png)
"""
        self.assertEqual(documents.local_link_targets(text), ["present.png"])

    def test_document_validator_finds_staged_deleted_link_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text("[자산](asset.png)\n", encoding="utf-8")
            (docs / "asset.png").write_bytes(b"asset")
            for command in (
                ["git", "init", "-q"],
                ["git", "config", "user.email", "test@example.com"],
                ["git", "config", "user.name", "Test"],
                ["git", "add", "docs"],
                ["git", "commit", "-qm", "fixture"],
            ):
                subprocess.run(command, cwd=root, check=True)
            (docs / "asset.png").unlink()
            subprocess.run(["git", "add", "-u"], cwd=root, check=True)
            deleted = {
                path
                for path in documents.staged_paths(root)
                if not documents.index_exists(root, path)
            }
            self.assertIn("docs/asset.png", deleted)
            self.assertTrue(documents.deleted_link_errors(root, deleted))

    def test_wbs_summary_matches_execution_tasks(self):
        text = """# WBS

> 실행 일정 1개 태스크

## 🗓️ 8주 핵심 개발 일정

## 📈 Mermaid 일정 가시화

dateFormat  YYYY-MM-DD

## 실행 WBS

## 📊 단계별 요약

| 단계 | 태스크 | 기간 |
|---|---:|---|
| 기획 | 1 | 07/10~07/10 |

## 🗂️ 전체 태스크 (1개)

### 기획

| ID | 작업 항목 | 산출물 | 담당 | 현황 | 시작 | 마감 | 제출일 |
|---|---|---|---|---|---|---|---|
| 1.1 | 시작 | 범위 | 전원 | 완료 | 07/10 | 07/10 |  |

## 📦 산출물 제출 일정

| 단계 | 산출물 | 제출일 | 내부검토 | WBS | 담당 | 현황 |
|---|---|---|---|---|---|---|
| 기획 | 범위 | 07/10 | 07/10 | 1.1 | 전원 | 완료 |

## WBS 작업 로그

## 변경 내역
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "02_WBS.md"
            path.write_text(text, encoding="utf-8")
            self.assertEqual(wbs.validate(path), [])


if __name__ == "__main__":
    unittest.main()

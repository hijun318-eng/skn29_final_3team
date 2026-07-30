import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "gate_scope", ROOT / ".github/scripts/gate_scope.py"
)
gate_scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate_scope)


class GateScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = gate_scope.LEDGER.read_text(encoding="utf-8")

    def test_latest_r4_merged_bundle_is_selected(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "jaehong")
        self.assertEqual("R4-W1-F2", bundle["EXECUTION_BUNDLE_ID"])
        self.assertEqual("MERGED_DEV", bundle["STATUS"])

    def test_ready_bundle_uses_exact_allowed_paths(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "seung")
        self.assertEqual("R2-W1-F2", bundle["EXECUTION_BUNDLE_ID"])
        self.assertEqual("READY", bundle["STATUS"])
        patterns = gate_scope.allowed_paths(bundle, "seung")
        self.assertTrue(
            gate_scope.path_allowed(
                "infrastructure/database/datahub/compose.fragment.yml", patterns
            )
        )
        self.assertFalse(
            gate_scope.path_allowed("compose.yml", patterns)
        )

    def test_merged_bundle_is_report_only(self) -> None:
        bundle = gate_scope.current_bundle(self.ledger, "jaehong")
        patterns = gate_scope.allowed_paths(bundle, "jaehong")
        self.assertTrue(
            gate_scope.path_allowed(
                "docs/markdown/daily_reports/jaehong/일일보고.md", patterns
            )
        )
        self.assertFalse(
            gate_scope.path_allowed(
                "app/backend/scripts/verify-container.ps1", patterns
            )
        )


if __name__ == "__main__":
    unittest.main()

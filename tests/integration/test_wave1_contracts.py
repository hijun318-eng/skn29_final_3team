import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def assigned_value(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        )
    )


class Wave1ContractTest(unittest.TestCase):
    def test_arrived_contract_versions_match_i1_ledger(self) -> None:
        data = json.loads(
            (ROOT / "src/data/r2_w1_contract.v1.json").read_text(encoding="utf-8")
        )
        model = json.loads(
            (ROOT / "src/ai/contracts/node_io.v0.1.json").read_text(encoding="utf-8")
        )
        backend_version = assigned_value(
            ROOT / "app/backend/app/contracts.py", "CONTRACT_VERSION"
        )
        ledger = (
            ROOT / "docs/markdown/collaboration/I0_결정_및_I1_공통_계약_원장.md"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            ("DRAFT-I1-v0.1", "1.0.0", "20260729", "1.0.0"),
            (
                data["contract_version"],
                data["schema_version"],
                data["seed_version"],
                data["scenario_version"],
            ),
        )
        self.assertEqual("DRAFT-MODEL-v0.1", model["version"])
        self.assertIn(
            backend_version,
            {"DRAFT-OPENAPI-v0.1", "OPENAPI-v1.0.0"},
        )
        for version in (
            data["contract_version"],
            model["version"],
            backend_version,
        ):
            self.assertIn(version, ledger)


if __name__ == "__main__":
    unittest.main()

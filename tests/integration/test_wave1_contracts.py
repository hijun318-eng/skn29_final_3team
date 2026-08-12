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
    def test_arrived_contract_versions_match(self) -> None:
        data = json.loads(
            (ROOT / "src/data/r2_w1_contract.v1.json").read_text(encoding="utf-8")
        )
        model = json.loads(
            (ROOT / "src/ai/contracts/node_io.v0.1.json").read_text(encoding="utf-8")
        )
        backend_version = assigned_value(
            ROOT / "app/backend/app/contracts.py", "CONTRACT_VERSION"
        )
        self.assertEqual("I1-v1.0.0", data["contract_version"])
        self.assertEqual(
            ("1.0.0", "20260729", "1.0.0"),
            (data["schema_version"], data["seed_version"], data["scenario_version"]),
        )
        self.assertEqual("I1-v1.0.0", data["candidate_contract_version"])
        self.assertEqual("MODEL-v1.0.0", model["version"])
        self.assertEqual("OPENAPI-v1.0.0", backend_version)

    def test_access_policy_is_versioned_and_least_privilege(self) -> None:
        policy = json.loads(
            (ROOT / "config/access-policy.yaml").read_text(encoding="utf-8")
        )

        self.assertEqual("ACCESS-POLICY-v1.0.0", policy["policy_version"])
        self.assertEqual(
            ["hotel_analyst"],
            policy["analysis_templates"]["weekly-room-operations"]["allowed_roles"],
        )
        self.assertEqual(
            {"hotel_analyst", "report_admin", "data_admin"},
            set(policy["role_mappings"]["groups"].values()),
        )
        self.assertEqual(3, len(policy["role_mappings"]["test_users"]))
        self.assertNotIn("token", json.dumps(policy).lower())

    def test_root_docker_context_excludes_local_state(self) -> None:
        ignored = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())

        self.assertTrue(
            {".git", ".wt", ".env", "**/.env", ".env.*", "**/.env.*"}
            <= ignored
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from src.ai.model_contracts import (
    canonical_json,
    canonical_json_sha256,
    canonical_messages,
    model_node_contract,
    model_release_checksum,
    model_release_manifest,
)
from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, schema_sha256, schema_version


class LiveModelContractTests(unittest.TestCase):
    def test_release_manifest_has_one_active_v1_contract_for_every_live_node(self):
        manifest = model_release_manifest()

        self.assertEqual("MODEL-RELEASE-v1.55.0", manifest["manifest_version"])
        self.assertEqual("ACTIVE", manifest["state"])
        self.assertEqual("v1", manifest["schema_contract"])
        self.assertEqual(schema_version(), manifest["schema_version"])
        self.assertEqual(schema_sha256(), manifest["schema_sha256"])
        self.assertEqual(
            {
                "analysis_plan_version",
                "typed_sql_compiler_version",
                "canonical_semantic_release_version",
                "runtime_governance_version",
            },
            set(manifest["compatible_runtime"]),
        )
        self.assertEqual(
            {
                "node1",
                "node2",
                "node2_repair",
                "node3",
                "report_assistant",
                "report_assistant_turn",
                "report_assistant_review",
            },
            set(manifest["nodes"]),
        )
        for forbidden in ("candidate", "cutover_gates", "rollback"):
            self.assertNotIn(forbidden, manifest)
        self.assertEqual("node2.sql_only", manifest["nodes"]["node2"]["prompt_id"])

    def test_release_entries_are_bound_to_live_prompt_and_schema_hashes(self):
        manifest = model_release_manifest()

        for node in manifest["nodes"]:
            entry = model_node_contract(node)
            prompt_id = entry["prompt_id"]
            prompt = get_prompt(prompt_id)
            with self.subTest(node=node):
                self.assertEqual(prompt_id, entry["prompt_id"])
                self.assertEqual(prompt.version, entry["prompt_version"])
                self.assertEqual(prompt.metadata()["hash"], entry["prompt_sha256"])
                self.assertEqual(f"{node}_request", entry["request_definition"])
                self.assertEqual(f"{node}_response", entry["response_definition"])

    def test_manifest_is_cached_and_node_contracts_are_immutable(self):
        self.assertIs(model_release_manifest(), model_release_manifest())
        self.assertEqual(64, len(model_release_checksum()))
        contract = model_node_contract("node2")
        with self.assertRaises(TypeError):
            contract["prompt_id"] = "replacement"
        with self.assertRaisesRegex(ContractError, "unsupported active model node"):
            model_node_contract("candidate_node")

    def test_unreleased_v2_schema_is_not_selectable(self):
        with self.assertRaisesRegex(ContractError, "unknown schema contract"):
            schema_version("v2")

    def test_canonical_messages_are_stable_and_do_not_mutate_payload(self):
        payload = {"label": "측정값", "a": 1}
        first = canonical_messages("node1.normalize", payload)
        second = canonical_messages("node1.normalize", {"a": 1, "label": "측정값"})

        self.assertEqual(first, second)
        self.assertEqual('{"a":1,"label":"측정값"}', first[1]["content"])
        self.assertEqual(payload, {"label": "측정값", "a": 1})
        self.assertEqual(64, len(canonical_json_sha256(payload)))
        with self.assertRaises(ValueError):
            canonical_json({"value": float("nan")})


if __name__ == "__main__":
    unittest.main()

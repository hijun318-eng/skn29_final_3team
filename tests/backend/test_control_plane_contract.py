import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
CONTRACT_VERSION = "DRAFT-OPENAPI-v0.1"


class ControlPlaneContractTest(unittest.TestCase):
    def test_backend_import_graph_has_no_cycle(self) -> None:
        modules = {
            ".".join(path.relative_to(BACKEND).with_suffix("").parts): path
            for path in (BACKEND / "app").rglob("*.py")
        }
        graph = {module: set() for module in modules}
        for module, path in modules.items():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module in modules:
                    graph[module].add(node.module)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(module: str) -> None:
            if module in visiting:
                self.fail(f"순환 의존 발견: {module}")
            if module in visited:
                return
            visiting.add(module)
            for dependency in graph[module]:
                visit(dependency)
            visiting.remove(module)
            visited.add(module)

        for module in graph:
            visit(module)

    def test_service_depends_on_port_not_fake_adapter(self) -> None:
        source = (BACKEND / "app" / "services" / "analysis_service.py").read_text(
            encoding="utf-8"
        )
        imports = {
            node.module
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom)
        }

        self.assertIn("app.ports.data_platform", imports)
        self.assertNotIn("app.adapters.fake_data_platform", imports)

    def test_contract_version_and_error_codes_are_complete(self) -> None:
        contracts = (BACKEND / "app" / "contracts.py").read_text(encoding="utf-8")
        registry = json.loads(
            (BACKEND / "contracts" / "source_registry.v1.json").read_text(
                encoding="utf-8"
            )
        )
        required_codes = {
            "CONTEXT_INCOMPLETE",
            "ACCESS_DENIED",
            "SQL_POLICY_BLOCKED",
            "QUERY_SOURCE_FAILED",
            "RESULT_EVIDENCE_MISSING",
            "PARTIAL_FAILURE",
            "INSUFFICIENT_EVIDENCE",
            "RATE_LIMITED",
            "CONTRACT_VERSION_MISMATCH",
            "SCHEMA_VERSION_MISMATCH",
            "INTERNAL_ERROR",
        }

        tree = ast.parse(contracts)
        assigned_version = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "CONTRACT_VERSION"
                for target in node.targets
            )
        )
        error_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ErrorCode"
        )
        declared_codes = {
            node.targets[0].id
            for node in error_class.body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        }

        self.assertEqual(CONTRACT_VERSION, assigned_version)
        self.assertEqual(CONTRACT_VERSION, registry["contract_version"])
        self.assertEqual(required_codes, declared_codes)


if __name__ == "__main__":
    unittest.main()

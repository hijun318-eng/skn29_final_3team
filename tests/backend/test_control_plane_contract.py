import ast
import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
CONTRACT_VERSION = "OPENAPI-v1.0.0"


class ControlPlaneContractTest(unittest.TestCase):
    def test_backend_image_preserves_repository_layout_for_migrations(self) -> None:
        dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("PYTHONPATH=/workspace", dockerfile)
        self.assertIn("WORKDIR /workspace/app/backend", dockerfile)
        self.assertIn(
            "app/backend/ app/backend/",
            dockerfile,
        )
        self.assertIn(
            "infrastructure/database/sql/ddl/00_answervice_app_postgresql.sql "
            "infrastructure/database/sql/ddl/00_answervice_app_postgresql.sql",
            dockerfile,
        )

    def test_backend_release_uses_exact_dependency_constraints(self) -> None:
        dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
        lock_lines = [
            line.strip()
            for line in (BACKEND / "requirements.lock.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

        self.assertTrue(lock_lines)
        for line in lock_lines:
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[^\s=]+$")
        self.assertIn(
            "--constraint app/backend/requirements.lock.txt",
            dockerfile,
        )

    def test_docker_healthcheck_is_liveness_not_product_readiness(self) -> None:
        dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
        healthcheck = dockerfile[dockerfile.index("HEALTHCHECK") :]

        self.assertIn("/health", healthcheck)
        self.assertNotIn("/readiness", healthcheck)
        self.assertIn("from urllib.request import urlopen", healthcheck)
        self.assertNotIn("import httpx", healthcheck)
        self.assertIn("--timeout=5s", healthcheck)

    def test_published_migration_is_immutable_and_followup_is_least_privilege(self) -> None:
        versions = BACKEND / "migrations" / "versions"
        published = (versions / "20260730_02_application_schema.py").read_bytes()
        followup = (versions / "20260731_03_runtime_grants.py").read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            "a468edca9b560c78afffc46876acb4d6b2ef1d6b42641d00fcc2db1c63c285ee",
            hashlib.sha256(published).hexdigest(),
        )
        self.assertLess(
            followup.index("DELETE FROM context.analysis_templates"),
            followup.index("ALTER COLUMN sql_text SET NOT NULL"),
        )
        self.assertIn(
            "GRANT SELECT, INSERT ON chat.analysis_state_transitions",
            followup,
        )
        self.assertNotIn("GRANT SELECT, INSERT, UPDATE", followup)
        self.assertNotIn("GRANT SELECT, INSERT, DELETE", followup)

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
        source = (BACKEND / "app" / "services" / "analysis" / "service.py").read_text(
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
        contracts = (BACKEND / "app" / "contract_core.py").read_text(
            encoding="utf-8"
        )
        required_codes = {
            "CONTEXT_INCOMPLETE",
            "CONTEXT_SOURCE_FAILED",
            "DATA_ASSET_NOT_FOUND",
            "OUT_OF_DATA_RANGE",
            "SOURCE_NOT_READY",
            "GRAIN_VIOLATION",
            "FILTER_VALUE_NOT_FOUND",
            "METRIC_NOT_AVAILABLE",
            "AUTHENTICATION_REQUIRED",
            "ACCESS_DENIED",
            "SEMANTIC_CONTRACT_INVALID",
            "MODEL_CONTRACT_INVALID",
            "MODEL_TIMEOUT",
            "MODEL_ENDPOINT_UNAVAILABLE",
            "MODEL_OUTPUT_UNGROUNDED",
            "CIRCUIT_OPEN",
            "INSUFFICIENT_CONTEXT",
            "UNREPAIRABLE",
            "SQL_POLICY_BLOCKED",
            "SQL_REPAIR_FAILED",
            "TRINO_CONNECTION_FAILED",
            "QUERY_TIMEOUT",
            "QUERY_SOURCE_FAILED",
            "EMPTY_RESULT",
            "PRESENTATION_NOT_SUPPORTED",
            "RESULT_VALIDATION_FAILED",
            "RESULT_EVIDENCE_MISSING",
            "ARTIFACT_PERSIST_FAILED",
            "PARTIAL_FAILURE",
            "INSUFFICIENT_EVIDENCE",
            "RATE_LIMITED",
            "REQUEST_CANCELLED",
            "CONTRACT_VERSION_MISMATCH",
            "SCHEMA_VERSION_MISMATCH",
            "CONVERSATION_ARCHIVED",
            "CONVERSATION_BUSY",
            "CONVERSATION_CONFLICT",
            "IDEMPOTENCY_CONFLICT",
            "REPORT_DRAFT_CONFLICT",
            "RESOURCE_NOT_FOUND",
            "RESOURCE_CONFLICT",
            "LAST_ADMIN_REQUIRED",
            "DEPENDENCY_UNAVAILABLE",
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
        self.assertEqual(required_codes, declared_codes)


if __name__ == "__main__":
    unittest.main()

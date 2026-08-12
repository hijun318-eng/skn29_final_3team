import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_trino_serving_views_are_provisioned_before_backend():
    result = subprocess.run(
        [
            "docker", "compose", "--env-file", ".env.example",
            "--profile", "full", "config", "--format", "json",
        ],
        cwd=ROOT,
        env=os.environ | {"COMPOSE_PROJECT_NAME": "answervice"},
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(result.stdout)["services"]
    provision = services["trino-provision"]

    assert provision["restart"] == "no"
    assert provision["depends_on"]["trino"]["condition"] == "service_healthy"
    assert "/sql/ddl/06_trino_analytics_views.sql" in provision["entrypoint"]
    assert services["backend"]["depends_on"]["trino-provision"] == {
        "condition": "service_completed_successfully",
        "required": False,
    }

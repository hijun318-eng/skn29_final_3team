from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infrastructure" / "neo4j" / "compose.fragment.yml"
ENV_EXAMPLE = ROOT / "infrastructure" / "neo4j" / ".env.example"


def _config() -> dict:
    environment = os.environ | {
        "NEO4J_PASSWORD": "test-only-password",
        "NEO4J_PROJECTION_DATABASE_URL": (
            "postgresql+psycopg://app_user:test-only-password@"
            "host.docker.internal:25432/app_db"
        ),
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "--profile",
            "neo4j",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_neo4j_profile_runs_one_shot_projector_after_health() -> None:
    services = _config()["services"]
    projector = services["neo4j-projector"]

    assert projector["depends_on"]["neo4j"]["condition"] == "service_healthy"
    assert projector["environment"]["NEO4J_GRAPH_ENABLED"] == "true"
    assert projector["environment"]["NEO4J_URI"] == "bolt://neo4j:7687"
    assert projector["restart"] == "on-failure:3"
    assert services["neo4j"]["ports"] == [
        {
            "mode": "ingress",
            "target": 7474,
            "published": "17474",
            "protocol": "tcp",
            "host_ip": "127.0.0.1",
        },
        {
            "mode": "ingress",
            "target": 7687,
            "published": "17687",
            "protocol": "tcp",
            "host_ip": "127.0.0.1",
        },
    ]


def test_neo4j_env_example_documents_automatic_projection_inputs() -> None:
    keys = {
        line.split("=", 1)[0]
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }

    assert {
        "NEO4J_PASSWORD",
        "NEO4J_PROJECTION_DATABASE_URL",
        "NEO4J_HTTP_PORT",
        "NEO4J_BOLT_PORT",
    } <= keys

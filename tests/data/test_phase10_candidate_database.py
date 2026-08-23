from argparse import Namespace

import pytest

from infrastructure.acceptance.phase10_candidate_database import (
    DATABASE,
    PORT,
    Phase10DatabaseError,
    validate_boundary,
)


def test_phase10_candidate_database_accepts_only_exact_isolated_target() -> None:
    validate_boundary(Namespace(host="127.0.0.1", port=PORT, database=DATABASE))


@pytest.mark.parametrize(
    ("host", "port", "database"),
    [
        ("127.0.0.1", 5432, DATABASE),
        ("remote.example", PORT, DATABASE),
        ("127.0.0.1", PORT, "app_db"),
    ],
)
def test_phase10_candidate_database_rejects_boundary_drift(
    host: str, port: int, database: str
) -> None:
    with pytest.raises(Phase10DatabaseError):
        validate_boundary(Namespace(host=host, port=port, database=database))

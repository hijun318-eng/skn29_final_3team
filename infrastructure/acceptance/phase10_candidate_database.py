#!/usr/bin/env python3
"""Prepare the exact isolated Phase 10 App DB without touching the Phase 4 DB."""

from __future__ import annotations

import argparse
import sys

import psycopg
from psycopg import sql


HOST = "127.0.0.1"
PORT = 55440
DATABASE = "phase10_p0_same_release_acceptance"
MIGRATION_ROLE = "phase10_migrator"
RUNTIME_ROLE = "phase10_runtime"
DATABASE_COMMENT = "Answervice isolated Phase 10 same-release acceptance"


class Phase10DatabaseError(RuntimeError):
    """The candidate database boundary or existing identity is unsafe."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--database", required=True)
    return parser.parse_args(argv)


def validate_boundary(args: argparse.Namespace) -> None:
    if args.host not in {HOST, "localhost", "::1"} or args.port != PORT:
        raise Phase10DatabaseError("Phase 10 database host is outside the isolated boundary")
    if args.database != DATABASE:
        raise Phase10DatabaseError("Phase 10 database name is outside the isolated boundary")


def _role(connection: psycopg.Connection[tuple[object, ...]], name: str) -> None:
    row = connection.execute(
        "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s", (name,)
    ).fetchone()
    if row is None:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(name))
        )
    elif row[0] is not True:
        raise Phase10DatabaseError("Phase 10 role exists without LOGIN")


def prepare(args: argparse.Namespace) -> None:
    validate_boundary(args)
    with psycopg.connect(
        host=HOST,
        port=PORT,
        user="postgres",
        dbname="postgres",
        autocommit=True,
    ) as connection:
        _role(connection, MIGRATION_ROLE)
        _role(connection, RUNTIME_ROLE)
        row = connection.execute(
            "SELECT pg_get_userbyid(datdba), obj_description(oid, 'pg_database') "
            "FROM pg_database WHERE datname = %s",
            (DATABASE,),
        ).fetchone()
        if row is None:
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(DATABASE), sql.Identifier(MIGRATION_ROLE)
                )
            )
            connection.execute(
                sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                    sql.Identifier(DATABASE), sql.Literal(DATABASE_COMMENT)
                )
            )
        elif row != (MIGRATION_ROLE, DATABASE_COMMENT):
            raise Phase10DatabaseError("existing Phase 10 database identity differs")
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(DATABASE), sql.Identifier(RUNTIME_ROLE)
            )
        )


def main(argv: list[str] | None = None) -> int:
    try:
        prepare(parse_args(argv))
    except (Phase10DatabaseError, psycopg.Error) as error:
        print(f"PHASE10_CANDIDATE_DATABASE_ERROR: {error}")
        return 1
    print("PHASE10_CANDIDATE_DATABASE_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

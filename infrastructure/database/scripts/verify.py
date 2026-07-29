#!/usr/bin/env python3
"""Verify the isolated synthetic hotel database Compose environment."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "compose.yml"
DATABASE_SERVICES = (
    "app-postgres",
    "pms-postgres",
    "banquet-postgres",
    "pos-mysql",
    "crm-mssql",
    "facility-clickhouse",
)


class VerificationError(RuntimeError):
    pass


def run(
    command: Sequence[str],
    *,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command),
        cwd=ROOT,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode != 0:
        output = "\n".join(
            part.strip()
            for part in (result.stdout or "", result.stderr or "")
            if part.strip()
        )
        raise VerificationError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{output}"
        )
    return result


def compose_base(env_file: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(COMPOSE_FILE),
    ]


def compose(env_file: Path, *arguments: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return run([*compose_base(env_file), *arguments], capture=capture)


def container_id(env_file: Path, service: str) -> str:
    result = compose(env_file, "ps", "-q", service)
    value = result.stdout.strip()
    if not value:
        raise VerificationError(f"{service}: container is not running")
    return value


def wait_for_health(env_file: Path, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    pending = set(DATABASE_SERVICES)
    last_status: dict[str, str] = {}
    while pending and time.monotonic() < deadline:
        for service in tuple(pending):
            cid = container_id(env_file, service)
            result = run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                    cid,
                ]
            )
            status = result.stdout.strip()
            last_status[service] = status
            if status == "healthy":
                print(f"PASS health: {service}")
                pending.remove(service)
            elif status in {"exited", "dead", "unhealthy"}:
                logs = compose(env_file, "logs", "--no-color", "--tail", "120", service).stdout
                raise VerificationError(f"{service}: status={status}\n{logs}")
        if pending:
            time.sleep(3)
    if pending:
        details = ", ".join(f"{name}={last_status.get(name, 'unknown')}" for name in sorted(pending))
        raise VerificationError(f"health timeout after {timeout_seconds}s: {details}")


def exec_in(
    env_file: Path,
    service: str,
    shell_script: str,
    *,
    expect_success: bool,
    label: str,
) -> str:
    result = compose(
        env_file,
        "exec",
        "-T",
        service,
        "bash",
        "-lc",
        shell_script,
    )
    succeeded = result.returncode == 0
    if succeeded != expect_success:
        output = "\n".join(
            part.strip()
            for part in (result.stdout or "", result.stderr or "")
            if part.strip()
        )
        expectation = "success" if expect_success else "failure"
        raise VerificationError(f"{label}: expected {expectation}\n{output}")
    print(f"PASS {label}")
    return result.stdout.strip()


def exec_allow_failure(
    env_file: Path,
    service: str,
    shell_script: str,
    *,
    expect_success: bool,
    label: str,
) -> str:
    command = [
        *compose_base(env_file),
        "exec",
        "-T",
        service,
        "bash",
        "-lc",
        shell_script,
    ]
    result = run(command, check=False)
    succeeded = result.returncode == 0
    if succeeded != expect_success:
        output = "\n".join(
            part.strip()
            for part in (result.stdout or "", result.stderr or "")
            if part.strip()
        )
        expectation = "success" if expect_success else "failure"
        raise VerificationError(f"{label}: expected {expectation}\n{output}")
    print(f"PASS {label}")
    return result.stdout.strip()


def verify_runtime_shape(env_file: Path) -> None:
    volume_names: set[str] = set()
    network_ids: set[str] = set()
    for service in DATABASE_SERVICES:
        cid = container_id(env_file, service)
        raw = run(["docker", "inspect", cid]).stdout
        details = json.loads(raw)[0]
        data_mounts = [
            mount
            for mount in details["Mounts"]
            if mount["Type"] == "volume"
        ]
        if len(data_mounts) != 1:
            raise VerificationError(f"{service}: expected one named data volume, got {len(data_mounts)}")
        volume_name = data_mounts[0]["Name"]
        if volume_name in volume_names:
            raise VerificationError(f"{service}: data volume is shared: {volume_name}")
        volume_names.add(volume_name)

        networks = details["NetworkSettings"]["Networks"]
        if len(networks) != 1:
            raise VerificationError(f"{service}: expected one Compose network")
        network_ids.add(next(iter(networks.values()))["NetworkID"])

        for bindings in (details["HostConfig"].get("PortBindings") or {}).values():
            for binding in bindings or []:
                if binding.get("HostIp") != "127.0.0.1":
                    raise VerificationError(
                        f"{service}: host port is not loopback-only: {binding}"
                    )
    if len(network_ids) != 1:
        raise VerificationError("database services are not attached to one common network")
    print("PASS topology: six unique named volumes, one common network, loopback host ports")


def postgres_checks(
    env_file: Path,
    service: str,
    database: str,
    prefix: str,
    table: str,
    cross_table: str,
) -> None:
    for consumer in ("datahub", "trino"):
        user = f"{prefix}_{consumer}"
        password_variable = f"{prefix.upper()}_{consumer.upper()}_PASSWORD"
        base = (
            f'PGPASSWORD="${password_variable}" psql --no-psqlrc '
            f'-v ON_ERROR_STOP=1 -h 127.0.0.1 -U {user} -d {database}'
        )
        exec_allow_failure(
            env_file,
            service,
            f'{base} -Atqc "SELECT count(*) FROM public.{table}"',
            expect_success=True,
            label=f"{service}/{user}: SELECT allowed",
        )
        exec_allow_failure(
            env_file,
            service,
            f'{base} -Atqc "DELETE FROM public.{table} WHERE false"',
            expect_success=False,
            label=f"{service}/{user}: write denied",
        )
        exec_allow_failure(
            env_file,
            service,
            f'{base} -Atqc "SELECT count(*) FROM public.{cross_table}"',
            expect_success=False,
            label=f"{service}/{user}: other silo absent",
        )


def verify_permissions(env_file: Path) -> None:
    postgres_checks(
        env_file,
        "pms-postgres",
        "hotel_pms",
        "pms",
        "pms_guests",
        "banquet_bookings",
    )
    postgres_checks(
        env_file,
        "banquet-postgres",
        "hotel_banquet",
        "banquet",
        "banquet_bookings",
        "pms_guests",
    )

    for consumer in ("datahub", "trino"):
        user = f"pos_{consumer}"
        password_variable = f"POS_{consumer.upper()}_PASSWORD"
        base = (
            f'mysql --protocol=TCP -h 127.0.0.1 -u{user} '
            f'-p"${password_variable}" --silent --skip-column-names hotel_pos'
        )
        exec_allow_failure(
            env_file,
            "pos-mysql",
            f'{base} -e "SELECT COUNT(*) FROM pos_orders"',
            expect_success=True,
            label=f"pos-mysql/{user}: SELECT allowed",
        )
        exec_allow_failure(
            env_file,
            "pos-mysql",
            f'{base} -e "DELETE FROM pos_orders WHERE 1=0"',
            expect_success=False,
            label=f"pos-mysql/{user}: write denied",
        )

    for consumer in ("datahub", "trino"):
        user = f"crm_{consumer}"
        password_variable = f"CRM_{consumer.upper()}_PASSWORD"
        sqlcmd = (
            'SQLCMD=/opt/mssql-tools18/bin/sqlcmd; '
            '[ -x "$SQLCMD" ] || SQLCMD=/opt/mssql-tools/bin/sqlcmd; '
        )
        base = (
            f'{sqlcmd}"$SQLCMD" -S localhost -C -b -U {user} '
            f'-P "${password_variable}" -d "$CRM_DATABASE"'
        )
        exec_allow_failure(
            env_file,
            "crm-mssql",
            f'{base} -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM dbo.crm_members"',
            expect_success=True,
            label=f"crm-mssql/{user}: SELECT allowed",
        )
        exec_allow_failure(
            env_file,
            "crm-mssql",
            f'{base} -Q "DELETE FROM dbo.crm_members WHERE 1=0"',
            expect_success=False,
            label=f"crm-mssql/{user}: write denied",
        )

    for consumer in ("datahub", "trino"):
        user = f"facility_{consumer}"
        password_variable = f"FACILITY_{consumer.upper()}_PASSWORD"
        base = (
            f'clickhouse-client -h 127.0.0.1 -u {user} '
            f'--password "${password_variable}" -d "$CLICKHOUSE_DB"'
        )
        exec_allow_failure(
            env_file,
            "facility-clickhouse",
            f'{base} -q "SELECT count() FROM facility_master"',
            expect_success=True,
            label=f"facility-clickhouse/{user}: SELECT allowed",
        )
        exec_allow_failure(
            env_file,
            "facility-clickhouse",
            f'{base} -q "INSERT INTO facility_master SELECT * FROM facility_master WHERE 0"',
            expect_success=False,
            label=f"facility-clickhouse/{user}: write denied",
        )

    exec_allow_failure(
        env_file,
        "app-postgres",
        (
            'PGPASSWORD="$APP_RUNTIME_PASSWORD" psql --no-psqlrc -v ON_ERROR_STOP=1 '
            '-h 127.0.0.1 -U app_runtime -d "$POSTGRES_DB" '
            '-Atqc "BEGIN; UPDATE connection.data_sources '
            "SET source_name = source_name WHERE source_code = 'pms'; ROLLBACK;\""
        ),
        expect_success=True,
        label="app-postgres/app_runtime: transactional DML allowed",
    )


def fingerprints(env_file: Path) -> dict[str, str]:
    queries = {
        "app-postgres": (
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF "|" -c '
            '"SELECT schema_version, synthetic_data_seed, '
            "(SELECT count(*) FROM connection.data_sources), "
            "(SELECT count(*) FROM governance.audit_events), "
            '(SELECT count(*) FROM reference.calendar_daily) '
            'FROM public.environment_manifest"'
        ),
        "pms-postgres": (
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF "|" -c '
            '"SELECT schema_version, synthetic_data_seed, '
            "(SELECT count(*) FROM pms_guests), "
            "(SELECT count(*) FROM pms_room_inventory_daily), "
            "(SELECT count(*) FROM pms_reservations), "
            '(SELECT count(*) FROM pms_stays) FROM environment_manifest"'
        ),
        "banquet-postgres": (
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF "|" -c '
            '"SELECT schema_version, synthetic_data_seed, '
            "(SELECT count(*) FROM banquet_bookings), "
            '(SELECT count(*) FROM banquet_revenue) FROM environment_manifest"'
        ),
        "pos-mysql": (
            'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --silent --skip-column-names '
            '"$MYSQL_DATABASE" -e "SELECT schema_version, synthetic_data_seed, '
            "(SELECT COUNT(*) FROM pos_stores), "
            "(SELECT COUNT(*) FROM pos_service_periods), "
            "(SELECT COUNT(*) FROM pos_orders), "
            '(SELECT COUNT(*) FROM pos_order_items) FROM environment_manifest"'
        ),
        "crm-mssql": (
            'SQLCMD=/opt/mssql-tools18/bin/sqlcmd; '
            '[ -x "$SQLCMD" ] || SQLCMD=/opt/mssql-tools/bin/sqlcmd; '
            '"$SQLCMD" -S localhost -C -b -h -1 -W -s "|" -U sa '
            '-P "$MSSQL_SA_PASSWORD" -d "$CRM_DATABASE" -Q '
            '"SET NOCOUNT ON; SELECT schema_version, synthetic_seed, '
            "(SELECT COUNT(*) FROM dbo.crm_members), "
            "(SELECT COUNT(*) FROM dbo.crm_member_grade_history), "
            "(SELECT COUNT(*) FROM dbo.crm_point_transactions), "
            '(SELECT COUNT(*) FROM dbo.crm_customer_map) FROM dbo.environment_manifest"'
        ),
        "facility-clickhouse": (
            'clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" '
            '-d "$CLICKHOUSE_DB" --format TSVRaw -q "SELECT schema_version, '
            "synthetic_data_seed, (SELECT count() FROM facility_master), "
            "(SELECT count() FROM facility_events), "
            "(SELECT count() FROM hotel_staffing_daily), "
            '(SELECT count() FROM facility_resource_daily) FROM environment_manifest"'
        ),
    }
    values: dict[str, str] = {}
    for service, query in queries.items():
        value = exec_allow_failure(
            env_file,
            service,
            query,
            expect_success=True,
            label=f"{service}: fingerprint query",
        )
        normalized = " ".join(value.split())
        if not normalized:
            raise VerificationError(f"{service}: empty fingerprint")
        values[service] = normalized
    return values


def compare_fingerprints(before: dict[str, str], after: dict[str, str], label: str) -> None:
    if before != after:
        lines = [
            f"{service}: before={before.get(service)!r}, after={after.get(service)!r}"
            for service in DATABASE_SERVICES
            if before.get(service) != after.get(service)
        ]
        raise VerificationError(f"{label}: fingerprint mismatch\n" + "\n".join(lines))
    print(f"PASS {label}: deterministic fingerprints match")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT / ".env",
        help="Compose environment file (default: infrastructure/database/.env)",
    )
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()

    env_file = args.env_file.resolve()
    if not env_file.is_file():
        raise VerificationError(f"environment file does not exist: {env_file}")

    compose(env_file, "config", "--quiet")
    print("PASS docker compose config")
    compose(env_file, "up", "-d", capture=False)
    wait_for_health(env_file, args.timeout)
    verify_runtime_shape(env_file)
    verify_permissions(env_file)
    baseline = fingerprints(env_file)

    if args.restart:
        compose(env_file, "restart", *DATABASE_SERVICES, capture=False)
        wait_for_health(env_file, args.timeout)
        compare_fingerprints(baseline, fingerprints(env_file), "restart persistence")

    if args.recreate:
        compose(env_file, "down", "--volumes", "--remove-orphans", capture=False)
        compose(env_file, "up", "-d", capture=False)
        wait_for_health(env_file, args.timeout)
        verify_runtime_shape(env_file)
        verify_permissions(env_file)
        compare_fingerprints(baseline, fingerprints(env_file), "volume recreation")

    print("PASS all requested database checks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as error:
        print(f"FAIL {error}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""Load a validated v4 candidate into isolated runtime namespaces."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema_contract.v2.json"
SOURCE_CONFIG = {
    "pms": ("postgres", "pms-postgres", "pms_readonly"),
    "pos": ("mysql", "pos-mysql", "pos_readonly"),
    "crm": ("mssql", "crm-mssql", "crm_query"),
    "banquet": ("postgres", "banquet-postgres", "banquet_readonly"),
    "facility": ("clickhouse", "facility-clickhouse", "facility_readonly"),
}
NAMESPACE = "walkerhill_v4"
STORAGE_PREFIX = "_v4_storage__"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(command: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        command,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command[:4])}\n{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def docker_sql(container: str, shell_command: str, sql: str) -> str:
    return run(["docker", "exec", "-i", container, "sh", "-lc", shell_command], input_text=sql)


def table_name(dataset: dict) -> str:
    return dataset["fqn"].rsplit(".", 1)[1]


def datasets_for(schema: dict, domain: str) -> list[dict]:
    return [dataset for dataset in schema["datasets"] if dataset["id"].split(".", 1)[0] == domain]


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def identifier(engine: str, name: str) -> str:
    if engine == "mysql":
        return f"`{name}`"
    if engine == "mssql":
        return f"[{name}]"
    return f'"{name}"'


def type_name(engine: str, field: list) -> str:
    field_type, nullable = field[0], field[1]
    mappings = {
        "postgres": {
            "string": "text",
            "integer": "bigint",
            "money": "numeric(20,2)",
            "decimal": "numeric(24,6)",
            "boolean": "boolean",
            "date": "date",
            "timestamp": "timestamptz",
            "time": "time",
        },
        "mysql": {
            "string": "varchar(512)",
            "integer": "bigint",
            "money": "decimal(20,2)",
            "decimal": "decimal(24,6)",
            "boolean": "boolean",
            "date": "date",
            "timestamp": "datetime(3)",
            "time": "time",
        },
        "mssql": {
            "string": "nvarchar(255)",
            "integer": "bigint",
            "money": "decimal(20,2)",
            "decimal": "decimal(24,6)",
            "boolean": "bit",
            "date": "date",
            "timestamp": "datetimeoffset(3)",
            "time": "time(0)",
        },
        "clickhouse": {
            "string": "String",
            "integer": "Int64",
            "money": "Decimal(20,2)",
            "decimal": "Decimal(24,6)",
            "boolean": "UInt8",
            "date": "Date",
            "timestamp": "DateTime64(3, 'Asia/Seoul')",
            "time": "String",
        },
        "trino": {
            "string": "varchar",
            "integer": "bigint",
            "money": "decimal(20,2)",
            "decimal": "decimal(24,6)",
            "boolean": "boolean",
            "date": "date",
            "timestamp": "timestamp(3) with time zone",
            "time": "time",
        },
    }
    rendered = mappings[engine][field_type]
    if engine == "clickhouse" and nullable:
        return f"Nullable({rendered})"
    return rendered


def render_source_ddl(schema: dict, domain: str) -> str:
    engine, _container, readonly_role = SOURCE_CONFIG[domain]
    datasets = datasets_for(schema, domain)
    statements: list[str] = []
    if engine == "postgres":
        statements.extend(
            [
                "\\set ON_ERROR_STOP on",
                f"DROP SCHEMA IF EXISTS {NAMESPACE} CASCADE;",
                f"CREATE SCHEMA {NAMESPACE};",
            ]
        )
    elif engine == "mysql":
        statements.extend(
            [
                f"DROP DATABASE IF EXISTS {NAMESPACE};",
                f"CREATE DATABASE {NAMESPACE} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;",
                f"USE {NAMESPACE};",
            ]
        )
    elif engine == "mssql":
        statements.extend(
            [
                "SET XACT_ABORT ON; SET NOCOUNT ON;",
                f"IF SCHEMA_ID(N'{NAMESPACE}') IS NOT NULL BEGIN",
                "DECLARE @drop nvarchar(max) = N'';",
                f"SELECT @drop += N'DROP TABLE [{NAMESPACE}].' + QUOTENAME(name) + N';' FROM sys.tables WHERE schema_id = SCHEMA_ID(N'{NAMESPACE}');",
                "EXEC sp_executesql @drop;",
                f"EXEC(N'DROP SCHEMA [{NAMESPACE}]'); END;",
                f"EXEC(N'CREATE SCHEMA [{NAMESPACE}]');",
                "GO",
            ]
        )
    else:
        statements.extend(
            [
                f"DROP DATABASE IF EXISTS {NAMESPACE};",
                f"CREATE DATABASE {NAMESPACE};",
            ]
        )

    for dataset in datasets:
        columns = []
        primary_key = dataset.get("primary_key", [])
        for field_name, contract in dataset["fields"].items():
            null_clause = "" if engine == "clickhouse" else (" NULL" if contract[1] else " NOT NULL")
            columns.append(f"{identifier(engine, field_name)} {type_name(engine, contract)}{null_clause}")
        if primary_key and engine != "clickhouse":
            columns.append(
                "PRIMARY KEY (" + ", ".join(identifier(engine, field) for field in primary_key) + ")"
            )
        qualified = f"{NAMESPACE}.{identifier(engine, table_name(dataset))}"
        if engine == "mssql":
            qualified = f'[{NAMESPACE}].[{table_name(dataset)}]'
        create = f"CREATE TABLE {qualified} (\n  " + ",\n  ".join(columns) + "\n)"
        if engine == "clickhouse":
            order = dataset.get("primary_key", [])
            order_expr = ", ".join(identifier(engine, field) for field in order) if order else "tuple()"
            create += f" ENGINE = MergeTree ORDER BY ({order_expr})"
        create += ";"
        statements.append(create)
        if engine == "mssql":
            statements.append("GO")

    if engine == "postgres":
        statements.extend(
            [
                f"GRANT USAGE ON SCHEMA {NAMESPACE} TO {readonly_role};",
                f"GRANT SELECT ON ALL TABLES IN SCHEMA {NAMESPACE} TO {readonly_role};",
            ]
        )
    elif engine == "mysql":
        statements.append(f"GRANT SELECT ON {NAMESPACE}.* TO '{readonly_role}';")
    elif engine == "mssql":
        statements.extend([f"GRANT SELECT ON SCHEMA::[{NAMESPACE}] TO [{readonly_role}];", "GO"])
    else:
        statements.append(f"GRANT SELECT ON {NAMESPACE}.* TO {readonly_role};")
    return "\n".join(statements) + "\n"


def csv_path(candidate: Path, dataset: dict) -> Path:
    domain, name = dataset["id"].split(".", 1)
    return candidate / "data" / domain / f"{name}.csv"


def load_postgres(schema: dict, candidate: Path, domain: str, output: Path) -> None:
    _engine, container, _role = SOURCE_CONFIG[domain]
    ddl = render_source_ddl(schema, domain)
    (output / f"{domain}.sql").write_text(ddl, encoding="utf-8", newline="\n")
    docker_sql(container, 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"', ddl)
    for dataset in datasets_for(schema, domain):
        source = csv_path(candidate, dataset)
        target = f"/tmp/walkerhill_v4_{table_name(dataset)}.csv"
        run(["docker", "cp", str(source), f"{container}:{target}"])
        fields = ", ".join(f'"{field}"' for field in dataset["fields"])
        copy_sql = f"\\copy {NAMESPACE}.\"{table_name(dataset)}\" ({fields}) FROM '{target}' WITH (FORMAT csv, HEADER true, NULL '');\n"
        docker_sql(container, 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"', copy_sql)


def load_mysql(schema: dict, candidate: Path, output: Path) -> None:
    domain = "pos"
    _engine, container, _role = SOURCE_CONFIG[domain]
    ddl = render_source_ddl(schema, domain)
    (output / "pos.sql").write_text(ddl, encoding="utf-8", newline="\n")
    mysql = 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 --local-infile=1'
    docker_sql(container, mysql, ddl)
    original_local_infile = docker_sql(container, mysql, "SELECT @@GLOBAL.local_infile;\n").splitlines()[-1]
    docker_sql(container, mysql, "SET GLOBAL local_infile = ON;\n")
    try:
        for dataset in datasets_for(schema, domain):
            source = csv_path(candidate, dataset)
            target = f"/tmp/walkerhill_v4_{table_name(dataset)}.csv"
            run(["docker", "cp", str(source), f"{container}:{target}"])
            variables = [f"@v{index}" for index, _name in enumerate(dataset["fields"], 1)]
            assignments = []
            for variable, (name, contract) in zip(variables, dataset["fields"].items()):
                if contract[0] == "boolean":
                    expression = f"IF({variable}='',NULL,IF(LOWER({variable})='true',1,0))"
                elif contract[0] == "timestamp":
                    expression = f"NULLIF(REPLACE(SUBSTRING_INDEX({variable},'+',1),'T',' '),'')"
                elif contract[1]:
                    expression = f"NULLIF({variable},'')"
                else:
                    expression = variable
                assignments.append(f"`{name}`={expression}")
            load_sql = (
                f"LOAD DATA LOCAL INFILE '{target}' INTO TABLE {NAMESPACE}.`{table_name(dataset)}` "
                "CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' "
                "LINES TERMINATED BY '\\n' IGNORE 1 LINES ("
                + ",".join(variables)
                + ") SET "
                + ",".join(assignments)
                + ";\n"
            )
            docker_sql(container, mysql, load_sql)
    finally:
        docker_sql(container, mysql, f"SET GLOBAL local_infile = {int(original_local_infile)};\n")


def typed_literal(value: str, contract: list, engine: str) -> str:
    if value == "":
        return "NULL"
    field_type = contract[0]
    if field_type == "boolean":
        if engine == "trino":
            return value.upper()
        return "1" if value.lower() == "true" else "0"
    if engine == "trino" and field_type == "integer":
        return f"BIGINT {sql_string(value)}"
    if engine == "trino" and field_type in {"money", "decimal"}:
        return f"DECIMAL {sql_string(value)}"
    if field_type in {"integer", "money", "decimal"}:
        return value
    if engine == "trino":
        if field_type == "date":
            return f"DATE {sql_string(value)}"
        if field_type == "timestamp":
            return f"from_iso8601_timestamp({sql_string(value)})"
        if field_type == "time":
            return f"TIME {sql_string(value)}"
        return sql_string(value)
    return "N" + sql_string(value)


SERVING_VIEW_SQL = {
    "serving.hotel_daily_metrics": """
WITH stay_days AS (
  SELECT s.hotel_code, s.room_type_code, day AS business_date,
         CAST(s.room_revenue AS decimal(20,6)) / s.occupied_room_nights AS allocated_revenue
  FROM pms.walkerhill_v4.pms_stays s
  CROSS JOIN UNNEST(sequence(CAST(s.actual_checkin_at AS date), date_add('day', -1, CAST(s.actual_checkout_at AS date)))) AS d(day)
  WHERE s.occupied_room_nights > 0
), sold AS (
  SELECT hotel_code, business_date, room_type_code, count(*) AS rooms_sold,
         sum(allocated_revenue) AS stay_day_room_revenue
  FROM stay_days GROUP BY 1,2,3
), recognized AS (
  SELECT hotel_code, CAST(actual_checkout_at AS date) AS business_date, room_type_code,
         sum(room_revenue) AS recognized_room_revenue
  FROM pms.walkerhill_v4.pms_stays GROUP BY 1,2,3
), base AS (
  SELECT hotel_code, business_date, room_type_code, i.available_room_nights,
         coalesce(s.rooms_sold, BIGINT '0') AS rooms_sold,
         CAST(coalesce(s.stay_day_room_revenue, DECIMAL '0') AS decimal(20,2)) AS stay_day_room_revenue,
         CAST(coalesce(r.recognized_room_revenue, DECIMAL '0') AS decimal(20,2)) AS recognized_room_revenue
  FROM pms.walkerhill_v4.pms_room_inventory_daily i
  LEFT JOIN sold s USING (hotel_code, business_date, room_type_code)
  LEFT JOIN recognized r USING (hotel_code, business_date, room_type_code)
)
SELECT hotel_code, business_date, room_type_code, available_room_nights, rooms_sold,
       stay_day_room_revenue, recognized_room_revenue,
       CAST(CAST(rooms_sold AS decimal(24,6)) / nullif(available_room_nights, 0) AS decimal(24,6)) AS occupancy_rate,
       CAST(round(CAST(stay_day_room_revenue AS double) / nullif(rooms_sold, 0), 6) AS decimal(24,6)) AS adr,
       CAST(round(CAST(stay_day_room_revenue AS double) / nullif(available_room_nights, 0), 6) AS decimal(24,6)) AS revpar
FROM base
""",
    "serving.fnb_daily_metrics": """
WITH base AS (
  SELECT o.outlet_id, o.business_date, o.service_period, count(*) AS order_count,
         sum(o.guest_count) AS fnb_covers, CAST(sum(o.net_amount) AS decimal(20,2)) AS fnb_net_revenue,
         CAST(m.synthetic_seat_capacity * CASE o.service_period WHEN 'LUNCH' THEN 2 ELSE 3 END AS decimal(24,6)) AS available_seat_hours
  FROM pos.walkerhill_v4.pos_orders o
  JOIN pos.walkerhill_v4.pos_outlets m ON o.outlet_id = m.outlet_id
  GROUP BY 1,2,3,m.synthetic_seat_capacity
)
SELECT outlet_id, business_date, service_period, order_count, fnb_covers, fnb_net_revenue,
       available_seat_hours,
       CAST(round(CAST(fnb_net_revenue AS double) / nullif(fnb_covers, 0), 6) AS decimal(24,6)) AS average_check,
       CAST(round(CAST(fnb_net_revenue AS double) / nullif(CAST(available_seat_hours AS double), 0), 6) AS decimal(24,6)) AS revpash
FROM base
""",
    "serving.banquet_daily_metrics": """
WITH revenue AS (
  SELECT banquet_event_id, sum(recognized_amount) AS recognized_revenue
  FROM banquet.walkerhill_v4.banquet_revenue_lines GROUP BY 1
), blocks AS (
  SELECT banquet_event_id, sum(reserved_room_nights) AS reserved_room_nights,
         sum(pickup_room_nights) AS pickup_room_nights
  FROM banquet.walkerhill_v4.banquet_room_blocks GROUP BY 1
), base AS (
  SELECT b.venue_id, b.event_date AS business_date, count(*) AS booking_count,
         count_if(b.booking_status = 'COMPLETED') AS completed_count,
         count_if(b.booking_status = 'CANCELLED') AS cancelled_count,
         sum(coalesce(b.actual_attendees, 0)) AS actual_attendees,
         CAST(sum(coalesce(r.recognized_revenue, DECIMAL '0')) AS decimal(20,2)) AS recognized_revenue,
         sum(coalesce(k.reserved_room_nights, 0)) AS reserved_room_nights,
         sum(coalesce(k.pickup_room_nights, 0)) AS pickup_room_nights
  FROM banquet.walkerhill_v4.banquet_bookings b
  LEFT JOIN revenue r ON b.banquet_event_id = r.banquet_event_id
  LEFT JOIN blocks k ON b.banquet_event_id = k.banquet_event_id
  GROUP BY 1,2
)
SELECT venue_id, business_date, booking_count, completed_count, cancelled_count,
       actual_attendees, recognized_revenue, reserved_room_nights, pickup_room_nights,
       CAST(CAST(pickup_room_nights AS decimal(24,6)) / nullif(reserved_room_nights, 0) AS decimal(24,6)) AS room_block_pickup_rate
FROM base
""",
    "serving.facility_daily_metrics": """
WITH days AS (
  SELECT DISTINCT business_date FROM facility.walkerhill_v4.facility_resource_daily
), usage AS (
  SELECT facility_id, business_date, count(*) AS usage_count, sum(guest_count) AS facility_guests,
         sum(net_amount) AS facility_net_revenue
  FROM facility.walkerhill_v4.facility_usage_events GROUP BY 1,2
), incidents AS (
  SELECT facility_id, CAST(CAST(started_at AS timestamp(3)) AS date) AS business_date, count(*) AS incident_count,
         sum(downtime_minutes) AS downtime_minutes
  FROM facility.walkerhill_v4.facility_incidents GROUP BY 1,2
)
SELECT f.facility_id, d.business_date, coalesce(u.usage_count, BIGINT '0') AS usage_count,
       coalesce(u.facility_guests, BIGINT '0') AS facility_guests,
       CAST(coalesce(u.facility_net_revenue, DECIMAL '0') AS decimal(20,2)) AS facility_net_revenue,
       coalesce(i.incident_count, BIGINT '0') AS incident_count,
       coalesce(i.downtime_minutes, BIGINT '0') AS downtime_minutes
FROM facility.walkerhill_v4.facility_master f CROSS JOIN days d
LEFT JOIN usage u ON f.facility_id = u.facility_id AND d.business_date = u.business_date
LEFT JOIN incidents i ON f.facility_id = i.facility_id AND d.business_date = i.business_date
""",
    "serving.resource_daily_metrics": """
WITH base AS (
  SELECT *, CAST(energy_kwh AS decimal(30,12)) * 1000000 / occupied_room_nights AS scaled_energy,
         CAST(water_m3 AS decimal(30,12)) * 1000000 / occupied_room_nights AS scaled_water
  FROM facility.walkerhill_v4.facility_resource_daily
), rounded AS (
  SELECT *,
         CASE WHEN scaled_energy - floor(scaled_energy) = DECIMAL '0.5' AND mod(CAST(floor(scaled_energy) AS bigint), 2) = 0
              THEN floor(scaled_energy) ELSE floor(scaled_energy + DECIMAL '0.5') END AS energy_units,
         CASE WHEN scaled_water - floor(scaled_water) = DECIMAL '0.5' AND mod(CAST(floor(scaled_water) AS bigint), 2) = 0
              THEN floor(scaled_water) ELSE floor(scaled_water + DECIMAL '0.5') END AS water_units
  FROM base
)
SELECT hotel_code, business_date, occupied_room_nights, energy_kwh, water_m3, waste_kg, resource_cost,
       CAST(CAST(energy_units AS decimal(30,6)) / DECIMAL '1000000.000000' AS decimal(24,6)) AS energy_per_occupied_room,
       CAST(CAST(water_units AS decimal(30,6)) / DECIMAL '1000000.000000' AS decimal(24,6)) AS water_per_occupied_room
FROM rounded
""",
    "serving.member_daily_revenue_metrics": """
WITH stay_days AS (
  SELECT s.guest_id, s.hotel_code, day AS business_date,
         CAST(s.room_revenue AS decimal(20,6)) / s.occupied_room_nights AS revenue_amount
  FROM pms.walkerhill_v4.pms_stays s
  CROSS JOIN UNNEST(sequence(CAST(s.actual_checkin_at AS date), date_add('day', -1, CAST(s.actual_checkout_at AS date)))) AS d(day)
  WHERE s.occupied_room_nights > 0
), all_revenue AS (
  SELECT m.member_no, s.business_date, s.hotel_code, 'ROOMS' AS source_domain,
         count(*) AS transaction_count, sum(s.revenue_amount) AS revenue_amount
  FROM stay_days s JOIN crm.walkerhill_v4.crm_customer_map m
    ON s.guest_id = m.pms_guest_id AND CAST(m.valid_from AS date) <= s.business_date
   AND (m.valid_to IS NULL OR s.business_date < CAST(m.valid_to AS date))
  GROUP BY 1,2,3,4
  UNION ALL
  SELECT m.member_no, o.business_date, x.hotel_code, 'FNB', count(*), sum(o.net_amount)
  FROM pos.walkerhill_v4.pos_orders o JOIN pos.walkerhill_v4.pos_outlets x ON o.outlet_id = x.outlet_id
  JOIN crm.walkerhill_v4.crm_customer_map m
    ON o.pos_customer_ref = m.pos_customer_ref AND m.valid_from <= o.ordered_at
   AND (m.valid_to IS NULL OR o.ordered_at < m.valid_to)
  WHERE o.net_amount > 0 GROUP BY 1,2,3,4
  UNION ALL
  SELECT m.member_no, u.business_date, f.hotel_code, 'FACILITY', count(*), sum(u.net_amount)
  FROM facility.walkerhill_v4.facility_usage_events u
  JOIN facility.walkerhill_v4.facility_master f ON u.facility_id = f.facility_id
  JOIN crm.walkerhill_v4.crm_customer_map m
    ON u.facility_user_ref = m.facility_user_ref
   AND m.valid_from <= with_timezone(CAST(u.event_at AS timestamp(3)), 'Asia/Seoul')
   AND (m.valid_to IS NULL OR with_timezone(CAST(u.event_at AS timestamp(3)), 'Asia/Seoul') < m.valid_to)
  WHERE u.net_amount > 0 GROUP BY 1,2,3,4
  UNION ALL
  SELECT m.member_no, b.event_date, v.hotel_code, 'BANQUET', count(DISTINCT b.banquet_event_id), sum(r.recognized_amount)
  FROM banquet.walkerhill_v4.banquet_bookings b
  JOIN banquet.walkerhill_v4.banquet_venues v ON b.venue_id = v.venue_id
  JOIN banquet.walkerhill_v4.banquet_revenue_lines r ON b.banquet_event_id = r.banquet_event_id
  JOIN crm.walkerhill_v4.crm_customer_map m
    ON b.banquet_customer_id = m.banquet_customer_id AND CAST(m.valid_from AS date) <= b.event_date
   AND (m.valid_to IS NULL OR b.event_date < CAST(m.valid_to AS date))
  WHERE r.recognized_amount > 0 GROUP BY 1,2,3,4
)
SELECT member_no, business_date, hotel_code, source_domain, sum(transaction_count) AS transaction_count,
       CAST(sum(revenue_amount) AS decimal(20,2)) AS revenue_amount
FROM all_revenue GROUP BY 1,2,3,4
""",
    "serving.total_operating_daily_metrics": """
WITH stay_days AS (
  SELECT s.hotel_code, day AS business_date,
         CAST(s.room_revenue AS decimal(20,6)) / s.occupied_room_nights AS revenue_amount
  FROM pms.walkerhill_v4.pms_stays s
  CROSS JOIN UNNEST(sequence(CAST(s.actual_checkin_at AS date), date_add('day', -1, CAST(s.actual_checkout_at AS date)))) AS d(day)
  WHERE s.occupied_room_nights > 0
), rooms AS (SELECT hotel_code, business_date, sum(revenue_amount) revenue FROM stay_days GROUP BY 1,2),
fnb AS (
  SELECT x.hotel_code, o.business_date, sum(o.net_amount) revenue FROM pos.walkerhill_v4.pos_orders o
  JOIN pos.walkerhill_v4.pos_outlets x ON o.outlet_id = x.outlet_id GROUP BY 1,2
), banquet_revenue AS (
  SELECT v.hotel_code, r.recognized_date AS business_date, sum(r.recognized_amount) revenue
  FROM banquet.walkerhill_v4.banquet_revenue_lines r
  JOIN banquet.walkerhill_v4.banquet_bookings b ON r.banquet_event_id = b.banquet_event_id
  JOIN banquet.walkerhill_v4.banquet_venues v ON b.venue_id = v.venue_id GROUP BY 1,2
), facility_revenue AS (
  SELECT f.hotel_code, u.business_date, sum(u.net_amount) revenue
  FROM facility.walkerhill_v4.facility_usage_events u
  JOIN facility.walkerhill_v4.facility_master f ON u.facility_id = f.facility_id GROUP BY 1,2
), base AS (
  SELECT hotel_code, business_date,
         CAST(coalesce(r.revenue, DECIMAL '0') AS decimal(20,2)) AS room_revenue,
         CAST(coalesce(f.revenue, DECIMAL '0') AS decimal(20,2)) AS fnb_net_revenue,
         CAST(coalesce(b.revenue, DECIMAL '0') AS decimal(20,2)) AS banquet_recognized_revenue,
         CAST(coalesce(x.revenue, DECIMAL '0') AS decimal(20,2)) AS facility_net_revenue
  FROM facility.walkerhill_v4.facility_resource_daily d
  LEFT JOIN rooms r USING (hotel_code, business_date)
  LEFT JOIN fnb f USING (hotel_code, business_date)
  LEFT JOIN banquet_revenue b USING (hotel_code, business_date)
  LEFT JOIN facility_revenue x USING (hotel_code, business_date)
)
SELECT hotel_code, business_date, room_revenue, fnb_net_revenue, banquet_recognized_revenue,
       facility_net_revenue,
       CAST(room_revenue + fnb_net_revenue + banquet_recognized_revenue + facility_net_revenue AS decimal(20,2)) AS total_operating_revenue
FROM base
""",
}


def load_mssql(schema: dict, candidate: Path, output: Path) -> None:
    domain = "crm"
    _engine, container, _role = SOURCE_CONFIG[domain]
    ddl = render_source_ddl(schema, domain)
    script = [ddl]
    for dataset in datasets_for(schema, domain):
        rows = list(csv.DictReader(csv_path(candidate, dataset).open("r", encoding="utf-8", newline="")))
        fields = list(dataset["fields"])
        for start in range(0, len(rows), 500):
            values = []
            for row in rows[start : start + 500]:
                values.append(
                    "(" + ",".join(typed_literal(row[field], dataset["fields"][field], "mssql") for field in fields) + ")"
                )
            columns = ",".join(f"[{field}]" for field in fields)
            script.append(f"INSERT INTO [{NAMESPACE}].[{table_name(dataset)}] ({columns}) VALUES\n" + ",\n".join(values) + ";\nGO")
    rendered = "\n".join(script) + "\n"
    (output / "crm.sql").write_text(rendered, encoding="utf-8", newline="\n")
    sqlcmd = '/opt/mssql-tools18/bin/sqlcmd -C -b -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -d crm_db'
    docker_sql(container, sqlcmd, rendered)


def transform_clickhouse_csv(source: Path, target: Path, dataset: dict) -> None:
    with source.open("r", encoding="utf-8", newline="") as input_stream, target.open(
        "w", encoding="utf-8", newline=""
    ) as output_stream:
        reader = csv.DictReader(input_stream)
        writer = csv.DictWriter(output_stream, fieldnames=reader.fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            for name, contract in dataset["fields"].items():
                if contract[0] == "boolean" and row[name]:
                    row[name] = "1" if row[name].lower() == "true" else "0"
                elif contract[0] == "timestamp" and row[name]:
                    row[name] = row[name].replace("T", " ").split("+", 1)[0]
            writer.writerow(row)


def load_clickhouse(schema: dict, candidate: Path, output: Path) -> None:
    domain = "facility"
    _engine, container, _role = SOURCE_CONFIG[domain]
    ddl = render_source_ddl(schema, domain)
    (output / "facility.sql").write_text(ddl, encoding="utf-8", newline="\n")
    client = 'clickhouse-client --multiquery --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD"'
    docker_sql(container, client, ddl)
    for dataset in datasets_for(schema, domain):
        transformed = output / f"{table_name(dataset)}.csv"
        transform_clickhouse_csv(csv_path(candidate, dataset), transformed, dataset)
        with transformed.open("r", encoding="utf-8") as stream:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "sh",
                    "-lc",
                    f'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "INSERT INTO {NAMESPACE}.\\"{table_name(dataset)}\\" FORMAT CSVWithNames"',
                ],
                stdin=stream,
                text=True,
                check=True,
            )


def render_trino(schema: dict, candidate: Path) -> str:
    datasets = datasets_for(schema, "reference") + datasets_for(schema, "serving")
    statements = []
    for dataset in datasets:
        if dataset["id"].startswith("serving."):
            view_table = dataset["fqn"].rsplit(".", 1)[1]
            old_storage = f"{STORAGE_PREFIX}analytics__{view_table}"
            statements.extend(
                [
                    f'DROP VIEW IF EXISTS {dataset["fqn"]};',
                    f'DROP TABLE IF EXISTS serving.analytics."{old_storage}";',
                    f'CREATE VIEW {dataset["fqn"]} AS\n{SERVING_VIEW_SQL[dataset["id"]].strip()};',
                ]
            )
            continue
        fields = list(dataset["fields"])
        columns = ", ".join(f'"{name}" {type_name("trino", contract)}' for name, contract in dataset["fields"].items())
        _catalog, view_schema, view_table = dataset["fqn"].split(".")
        storage_table = f"{STORAGE_PREFIX}{view_schema}__{view_table}"
        statements.extend(
            [
                f'DROP VIEW IF EXISTS {dataset["fqn"]};',
                f'DROP TABLE IF EXISTS serving.analytics."{storage_table}";',
                f'CREATE TABLE serving.analytics."{storage_table}" ({columns});',
            ]
        )
        rows = list(csv.DictReader(csv_path(candidate, dataset).open("r", encoding="utf-8", newline="")))
        for start in range(0, len(rows), 250):
            values = []
            for row in rows[start : start + 250]:
                values.append(
                    "(" + ",".join(typed_literal(row[field], dataset["fields"][field], "trino") for field in fields) + ")"
                )
            statements.append(
                f'INSERT INTO serving.analytics."{storage_table}" ({",".join(f"\"{field}\"" for field in fields)}) VALUES\n'
                + ",\n".join(values)
                + ";"
            )
        statements.append(
            f'CREATE VIEW {dataset["fqn"]} AS SELECT * FROM serving.analytics."{storage_table}";'
        )
    return "\n".join(statements) + "\n"


def load_trino(schema: dict, candidate: Path, output: Path) -> None:
    sql = render_trino(schema, candidate)
    path = output / "serving.sql"
    path.write_text(sql, encoding="utf-8", newline="\n")
    container_path = "/tmp/walkerhill_v4_serving.sql"
    run(["docker", "cp", str(path), f"hotel-synthetic-db-trino-1:{container_path}"])
    run(
        [
            "docker",
            "exec",
            "hotel-synthetic-db-trino-1",
            "trino",
            "--server",
            "http://localhost:8080",
            "--user",
            "hotel_synthetic_setup",
            "--file",
            container_path,
        ]
    )


def trino_counts(schema: dict) -> dict[str, int]:
    selects = [
        f"SELECT {sql_string(dataset['id'])} dataset_id, count(*) row_count FROM {dataset['fqn']}"
        for dataset in schema["datasets"]
    ]
    query = " UNION ALL ".join(selects)
    output = run(
        [
            "docker",
            "exec",
            "hotel-synthetic-db-trino-1",
            "trino",
            "--server",
            "http://localhost:8080",
            "--user",
            "hotel_synthetic_setup",
            "--output-format",
            "CSV_HEADER_UNQUOTED",
            "--execute",
            query,
        ]
    )
    return {row["dataset_id"]: int(row["row_count"]) for row in csv.DictReader(output.splitlines())}


def verify_counts(schema: dict, candidate: Path, output: Path) -> dict:
    manifest = load_json(candidate / "manifest.json")
    expected = {item["dataset_id"]: item["row_count"] for item in manifest["files"]}
    actual = trino_counts(schema)
    mismatches = {
        dataset_id: {"expected": expected.get(dataset_id), "actual": actual.get(dataset_id)}
        for dataset_id in sorted(set(expected) | set(actual))
        if expected.get(dataset_id) != actual.get(dataset_id)
    }
    report = {
        "namespace": NAMESPACE,
        "dataset_count": len(actual),
        "expected_rows": sum(expected.values()),
        "actual_rows": sum(actual.values()),
        "mismatches": mismatches,
        "status": "PASSED" if not mismatches else "FAILED",
    }
    (output / "runtime_load_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    if mismatches:
        raise RuntimeError(f"runtime row counts differ: {mismatches}")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate = args.candidate.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    schema = load_json(SCHEMA_PATH)
    for domain in SOURCE_CONFIG:
        (output / f"{domain}.ddl.sql").write_text(
            render_source_ddl(schema, domain), encoding="utf-8", newline="\n"
        )
    (output / "serving.rendered.sql").write_text(
        render_trino(schema, candidate), encoding="utf-8", newline="\n"
    )
    if args.render_only:
        print(json.dumps({"status": "RENDERED", "output": str(output)}, ensure_ascii=False))
        return 0

    load_postgres(schema, candidate, "pms", output)
    load_mysql(schema, candidate, output)
    load_mssql(schema, candidate, output)
    load_postgres(schema, candidate, "banquet", output)
    load_clickhouse(schema, candidate, output)
    load_trino(schema, candidate, output)
    report = verify_counts(schema, candidate, output)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""APP_DATABASE_URL에 연결된 단일 governance Alembic revision chain을 실행한다."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool


config = context.config
database_url = os.getenv("APP_DATABASE_URL")
if database_url:
    # Alembic stores this option in ConfigParser, where percent is interpolation
    # syntax. URL-encoded credentials must remain literal connection data.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    """DB 연결 없이 literal SQL을 만들되 version table 위치는 governance로 고정한다."""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        include_schemas=True,
        version_table_schema="governance",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """전용 non-pooled connection에서 governance schema와 migration을 원자 실행한다."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # Lock-then-recheck migrations require a fresh snapshot after lock waits.
        isolation_level="READ COMMITTED",
    )
    with connectable.connect() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS governance")
        connection.commit()
        context.configure(
            connection=connection,
            include_schemas=True,
            version_table_schema="governance",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

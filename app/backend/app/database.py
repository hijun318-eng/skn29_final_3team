"""프로세스당 하나의 PostgreSQL async engine과 transaction-scoped session 수명을 관리한다."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DatabaseConfigurationError(RuntimeError):
    """DB URL 누락·비 PostgreSQL backend·이미 고정된 process URL과의 충돌을 알린다."""


_state_lock = Lock()
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_database_url: str | None = None


def normalize_async_database_url(database_url: str) -> str:
    """비동기 database URL 값을 비교와 해시에 사용할 수 있는 표준 형태로 정규화한다.

    Return a SQLAlchemy URL that uses psycopg's asynchronous PostgreSQL dialect.
    """
    value = database_url.strip()
    if not value:
        raise DatabaseConfigurationError("APP_RUNTIME_DATABASE_URL is required")
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise DatabaseConfigurationError("Only PostgreSQL runtime databases are supported")
    return url.set(drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )


def get_sessionmaker(
    database_url: str | None = None,
) -> async_sessionmaker[AsyncSession]:
    """명시 URL 또는 ``APP_RUNTIME_DATABASE_URL``로 프로세스 공용 async session factory를 반환한다.

    첫 호출이 PostgreSQL engine과 factory를 생성하고, 동시 초기화는 process lock으로
    직렬화하며 이후 같은 URL은 그 인스턴스를 재사용한다. 이미 다른 URL로 초기화된 프로세스에는
    :class:`DatabaseConfigurationError`를 발생시켜 서로 다른 DB의 transaction이 한 pool에
    섞이지 않게 한다.
    """
    global _database_url, _engine, _sessionmaker

    normalized = normalize_async_database_url(
        database_url or os.getenv("APP_RUNTIME_DATABASE_URL", "")
    )
    with _state_lock:
        if _sessionmaker is None:
            _engine = create_async_engine(normalized, pool_pre_ping=True)
            _sessionmaker = async_sessionmaker(
                _engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            _database_url = normalized
        elif normalized != _database_url:
            raise DatabaseConfigurationError(
                "The process database is already configured with a different URL"
            )
        return _sessionmaker


@asynccontextmanager
async def session_scope(
    database_url: str | None = None,
) -> AsyncIterator[AsyncSession]:
    """비동기 DB 세션을 열고 성공 시 commit, 예외 시 rollback한 뒤 항상 닫는다.

    Yield a session and commit or roll back its unit of work atomically.
    """
    factory = get_sessionmaker(database_url)
    async with factory() as session:
        try:
            yield session
            # 호출자가 여러 write를 수행해도 여기서 한 번만 commit해야 중간 상태가 노출되지 않는다.
            # commit 실패도 아래 rollback 경로로 보내 동일 unit-of-work 전체를 원복한다.
            await session.commit()
        except BaseException:
            # cancellation도 BaseException 계열이므로 반드시 rollback한 뒤 다시 전파해야 한다.
            # 그렇지 않으면 pool로 돌아간 세션의 미완료 transaction이 다음 요청에 섞일 수 있다.
            await session.rollback()
            raise


async def get_database_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 요청에 transaction 범위의 ``AsyncSession`` 하나를 주입한다.

    의존 함수 소비가 정상 종료되면 commit하고 예외나 cancellation이면 rollback한 뒤
    세션을 닫는다. DB URL 계약 위반은 :class:`DatabaseConfigurationError`로 그대로
    전달된다.
    """
    async with session_scope() as session:
        yield session


async def dispose_database() -> None:
    """애플리케이션 종료 시 공용 engine 참조를 먼저 분리한 뒤 connection pool을 폐기한다.

    잠금 안에서 factory와 URL까지 초기화하므로 이후 시작 주기는 새 DB 설정으로 안전하게
    초기화할 수 있다. engine이 없을 때의 반복 호출도 성공하며 반환값은 ``None``이다.
    """
    global _database_url, _engine, _sessionmaker

    with _state_lock:
        engine = _engine
        _engine = None
        _sessionmaker = None
        _database_url = None
    if engine is not None:
        await engine.dispose()

"""SQLAlchemy 2 DB 설정 — FastAPI 공개 API용.

기획서 기준 SQLAlchemy 2 + Alembic. 현재는 SQLite data.db를 사용하며
향후 PostgreSQL로 전환 예정.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# app/fastapi/app/database.py → parent x2 = app/fastapi/
_FASTAPI_DIR = Path(__file__).resolve().parent.parent
_DB_PATH = _FASTAPI_DIR / "data.db"
DATABASE_URL = f"sqlite:///{_DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, future=True)


class Base(DeclarativeBase):
    """SQLAlchemy 2 declarative base."""
    pass


def get_db():
    """FastAPI 의존성: DB 세션을 생성하고 자동으로 닫는다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

"""``python -m src.rag.e2e`` 실행을 E2E CLI의 검증 결과 종료 코드로 연결한다."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())

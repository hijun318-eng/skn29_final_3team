"""PDF·DOCX 원본을 동일한 크기·변경 감지 계약으로 읽는다."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import BinaryIO


DEFAULT_MAX_SOURCE_BYTES = 64 * 1024 * 1024
SOURCE_MAX_BYTES_BY_SUFFIX: dict[str, int] = {
    ".pdf": DEFAULT_MAX_SOURCE_BYTES,
    ".docx": DEFAULT_MAX_SOURCE_BYTES,
}
_READ_BLOCK_BYTES = 1024 * 1024


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    """경로 stat과 descriptor stat 모두 안정적으로 제공하는 identity를 반환한다."""

    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
    )


def _descriptor_state(value: os.stat_result) -> tuple[int, int, int, int, int]:
    """동일 descriptor의 읽기 전후 변경 감지용 상태를 반환한다."""

    return (*_stat_identity(value), value.st_ctime_ns)


def _read_at_most(source: BinaryIO, maximum_bytes: int) -> bytes:
    """부분 read가 발생해도 상한을 넘지 않는 범위에서 EOF까지 읽는다."""

    chunks: list[bytes] = []
    remaining = maximum_bytes + 1
    while remaining > 0:
        chunk = source.read(min(_READ_BLOCK_BYTES, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_bounded_source_bytes(
    path: Path,
    *,
    expected_suffix: str | None = None,
    maximum_bytes: int | None = None,
) -> bytes:
    """지원 원본을 bounded read하고 읽기 중 identity·크기 변경을 거부한다."""

    source_path = Path(path)
    suffix = source_path.suffix.lower()
    expected = suffix if expected_suffix is None else expected_suffix.lower()
    if (
        expected not in SOURCE_MAX_BYTES_BY_SUFFIX
        or suffix != expected
        or (maximum_bytes is not None and type(maximum_bytes) is not int)
    ):
        raise ValueError("RAG source format or size limit is invalid")
    limit = (
        SOURCE_MAX_BYTES_BY_SUFFIX[expected]
        if maximum_bytes is None
        else maximum_bytes
    )
    if type(limit) is not int or limit <= 0:
        raise ValueError("RAG source format or size limit is invalid")

    try:
        path_before = source_path.stat()
        if (
            not stat.S_ISREG(path_before.st_mode)
            or path_before.st_size <= 0
            or path_before.st_size > limit
        ):
            raise ValueError("RAG source size is invalid")
        with source_path.open("rb") as source:
            descriptor_before = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(descriptor_before.st_mode)
                or _stat_identity(path_before) != _stat_identity(descriptor_before)
            ):
                raise ValueError("RAG source changed before bounded read")
            content = _read_at_most(source, limit)
            descriptor_after = os.fstat(source.fileno())
            path_after = source_path.stat()
    except OSError as error:
        raise ValueError("RAG source is unreadable") from error

    identity = _stat_identity(descriptor_before)
    if (
        _descriptor_state(descriptor_before) != _descriptor_state(descriptor_after)
        or identity != _stat_identity(path_after)
        or len(content) != descriptor_before.st_size
    ):
        raise ValueError("RAG source changed during bounded read")
    if not content or len(content) > limit:
        raise ValueError("RAG source size is invalid")
    return content

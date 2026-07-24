"""로그인 실패 잠금 관리 모듈.

클라이언트 IP 기반으로 로그인 실패 횟수를 추적하고,
5회 실패 시 자동으로 잠금을 건다. 잠금 시간은 15분이다.

Django cache 프레임워크를 사용하여 LocMemCache에 저장한다.
"""

from __future__ import annotations

from django.core.cache import cache

_LOCKOUT_THRESHOLD = 5
_LOCKOUT_TIMEOUT_SECONDS = 15 * 60  # 15분


def _cache_key(ip: str) -> str:
    """IP별 실패 횟수 캐시 키."""
    return f"senseplace:login_fail:{ip}"


def _lock_key(ip: str) -> str:
    """IP별 잠금 상태 캐시 키."""
    return f"senseplace:login_lock:{ip}"


def check_locked(ip: str) -> bool:
    """IP가 잠금 상태인지 확인한다."""
    return cache.get(_lock_key(ip), False)


def record_failure(ip: str) -> int:
    """로그인 실패를 기록하고 현재 실패 횟수를 반환한다.

    잠금 임계값(5회)에 도달하면 자동으로 잠금을 건다.
    """
    key = _cache_key(ip)
    count = cache.get(key, 0) + 1
    cache.set(key, count, _LOCKOUT_TIMEOUT_SECONDS)

    if count >= _LOCKOUT_THRESHOLD:
        cache.set(_lock_key(ip), True, _LOCKOUT_TIMEOUT_SECONDS)

    return count


def clear_failures(ip: str) -> None:
    """로그인 성공 시 실패 기록과 잠금을 초기화한다."""
    cache.delete(_cache_key(ip))
    cache.delete(_lock_key(ip))


def get_failure_count(ip: str) -> int:
    """현재 실패 횟수를 반환한다 (테스트용)."""
    return cache.get(_cache_key(ip), 0)

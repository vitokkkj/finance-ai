from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Iterable


class SlidingWindowRateLimiter:
    """Aplica limite de frequência com janela móvel e memória limitada."""

    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: int,
        max_keys: int = 4096,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _recent_attempts(self, key: str, now: float) -> deque[float]:
        attempts = self._failures.get(key)
        if attempts is None:
            return deque()
        cutoff = now - self._window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            self._failures.pop(key, None)
            return deque()
        self._failures.move_to_end(key)
        return attempts

    def _discard_expired(self, now: float) -> None:
        cutoff = now - self._window_seconds
        expired = [
            key
            for key, attempts in self._failures.items()
            if not attempts or attempts[-1] <= cutoff
        ]
        for key in expired:
            self._failures.pop(key, None)

    def allow_attempt(self, keys: Iterable[str], now: float) -> bool:
        with self._lock:
            unique_keys = tuple(dict.fromkeys(keys))
            attempts_by_key = {
                key: self._recent_attempts(key, now) for key in unique_keys
            }
            if any(len(attempts) >= self._max_attempts for attempts in attempts_by_key.values()):
                return False

            new_keys = tuple(key for key in unique_keys if key not in self._failures)
            if new_keys:
                self._discard_expired(now)
                if len(self._failures) + len(new_keys) > self._max_keys:
                    # Fail closed at capacity. Evicting an active bucket would let
                    # a high-cardinality attack erase an existing lockout.
                    return False

            for key, attempts in attempts_by_key.items():
                if not attempts and key not in self._failures:
                    attempts = deque()
                    self._failures[key] = attempts
                attempts.append(now)
                self._failures.move_to_end(key)
            return True

    def clear(self, keys: Iterable[str]) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


LoginRateLimiter = SlidingWindowRateLimiter


def verify_totp(secret: str, code: str | None, *, now: float | None = None) -> bool:
    """Valida código TOTP de 6 dígitos com uma janela de ±30 segundos."""
    if code is None or len(code) != 6 or not code.isascii() or not code.isdigit():
        return False

    normalized = secret.strip().upper().rstrip("=")
    padded = normalized + "=" * ((8 - len(normalized) % 8) % 8)
    try:
        key = base64.b32decode(padded, casefold=False)
    except (binascii.Error, ValueError):
        return False
    if len(key) < 20:
        return False

    current_counter = int((time.time() if now is None else now) // 30)
    for counter in (current_counter - 1, current_counter, current_counter + 1):
        digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
        expected = f"{binary % 1_000_000:06d}"
        if hmac.compare_digest(expected, code):
            return True
    return False

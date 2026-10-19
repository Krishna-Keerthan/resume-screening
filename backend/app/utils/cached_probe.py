"""
app/utils/cached_probe.py

A yes/no check whose answer is reused for a while, so a frequent caller (a health probe)
does not repeat an outbound call each time.
"""

import time
from typing import Callable


class CachedProbe:
    """
    Calls `check` at most once per `ttl_seconds` and returns its last answer in between.

    The clock is time.monotonic by default, so a change of the system time cannot extend
    or cut the interval; tests pass their own. A ttl of 0 never reuses an answer. If `check`
    raises, nothing is cached and the exception reaches the caller.
    """

    def __init__(self, check: Callable[[], bool], ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._check = check
        self._ttl = ttl_seconds
        self._clock = clock
        self._answer: bool | None = None
        self._checked_at = 0.0

    def __call__(self) -> bool:
        now = self._clock()
        if self._answer is None or now - self._checked_at >= self._ttl:
            self._answer = bool(self._check())
            self._checked_at = now
        return self._answer

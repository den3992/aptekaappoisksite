"""Small process-local TTL cache with one refresh shared by concurrent readers."""
from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import Awaitable, Callable, Generic, Optional, TypeVar


T = TypeVar("T")
_MISSING = object()
logger = logging.getLogger(__name__)


class AsyncTTLValue(Generic[T]):
    def __init__(
        self,
        load: Callable[[], Awaitable[T]],
        *,
        ttl: float,
        stale_if_error: float = 0,
        stale_while_revalidate: bool = False,
        retry_delay: float = 0,
        load_timeout: Optional[float] = None,
        name: str,
        clock: Optional[Callable[[], float]] = None,
    ):
        self._load = load
        self._ttl = ttl
        self._stale_if_error = stale_if_error
        self._stale_while_revalidate = stale_while_revalidate
        self._retry_delay = retry_delay
        self._load_timeout = load_timeout
        self._name = name
        self._clock = clock or monotonic
        self._value = _MISSING
        self._updated_at = 0.0
        self._inflight: Optional[asyncio.Task] = None
        self._retry_after = 0.0
        self._last_error: Optional[Exception] = None

    async def get(self) -> T:
        now = self._clock()
        age = now - self._updated_at
        has_value = self._value is not _MISSING
        if has_value and age < self._ttl:
            return self._value
        can_revalidate = (
            self._stale_while_revalidate and has_value
            and age < self._ttl + self._stale_if_error
        )
        if self._inflight is None:
            if now < self._retry_after and self._last_error is not None:
                if can_revalidate:
                    return self._value
                # Never serve a snapshot past the hard age limit during backoff.
                raise self._last_error.with_traceback(None)
            self._inflight = asyncio.create_task(self._refresh())
            # A disconnected client must not cancel the refresh for other readers.
            # Retrieve errors even if every waiting client has disconnected.
            self._inflight.add_done_callback(self._observe_result)
        if can_revalidate:
            return self._value
        return await asyncio.shield(self._inflight)

    @staticmethod
    def _observe_result(task: asyncio.Task) -> None:
        if not task.cancelled():
            task.exception()

    async def _refresh(self) -> T:
        try:
            value = await asyncio.wait_for(self._load(), timeout=self._load_timeout)
            self._value = value
            self._updated_at = self._clock()
            self._retry_after = 0.0
            self._last_error = None
            return value
        except Exception as error:
            self._last_error = error
            self._retry_after = self._clock() + self._retry_delay
            age = self._clock() - self._updated_at
            if (
                self._stale_if_error > 0
                and self._value is not _MISSING
                and age < self._ttl + self._stale_if_error
            ):
                logger.warning(
                    "%s refresh failed; serving cached snapshot aged %.1fs",
                    self._name, age, exc_info=True,
                )
                return self._value
            if self._stale_while_revalidate:
                logger.warning("%s refresh failed; no usable snapshot", self._name, exc_info=True)
            raise
        finally:
            self._inflight = None

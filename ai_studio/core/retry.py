"""Async retry utility with exponential backoff and jitter."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ai_studio.exceptions import ServiceUnavailableError

T = TypeVar("T")


async def with_retry(
    coro_factory: Callable[..., Awaitable[T]],
    *args: object,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable: tuple[type[Exception], ...] = (ServiceUnavailableError,),
    **kwargs: object,
) -> T:
    """Call *coro_factory* with retry on transient failures.

    Args:
        coro_factory: An async callable that will be invoked on each attempt.
        *args: Positional arguments forwarded to *coro_factory*.
        max_attempts: Total number of attempts before giving up.
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Upper bound on the computed delay.
        retryable: Exception types that trigger a retry.
        **kwargs: Keyword arguments forwarded to *coro_factory*.

    Returns:
        The value returned by *coro_factory* on a successful attempt.

    Raises:
        The last exception raised by *coro_factory* after all attempts
        are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await coro_factory(*args, **kwargs)
        except retryable as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                delay = min(base_delay * (2**attempt) + random.uniform(0, 1), max_delay)
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]

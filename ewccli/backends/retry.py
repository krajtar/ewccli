#!/usr/bin/env python
#
# Package Name: ewccli
# License: GPL-3.0-or-later
# Copyright (c) 2025 EUMETSAT, ECMWF for European Weather Cloud
# See the LICENSE file for more details


"""Retry and timeout utilities for backend clients.

Provides a decorator that wraps a callable with exponential-backoff
retries and an optional overall timeout.  Retryable exceptions are
configurable via the ``retry_on`` parameter; by default only
:class:`~ewccli.backends.exceptions.BackendTimeoutError` and transient
:class:`~ewccli.backends.exceptions.BackendConnectionError` are retried.
"""

import functools
import time
import logging
from typing import Type, Tuple, Callable, Any

from ewccli.backends.exceptions import (
    BackendTimeoutError,
    BackendConnectionError,
    BackendOperationError,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_RETRY_ON: Tuple[Type[Exception], ...] = (
    BackendTimeoutError,
    BackendConnectionError,
)

# Exceptions that should *never* be retried even if they are BackendError
# sub-classes.
_NO_RETRY_ON: Tuple[Type[Exception], ...] = (
    BackendOperationError,
)


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    retry_on: Tuple[Type[Exception], ...] = _DEFAULT_RETRY_ON,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that retries a callable with exponential backoff.

    :param max_retries: Maximum number of retry attempts (excluding the
        initial call).  ``0`` disables retries.
    :param initial_delay: Delay in seconds before the first retry.
    :param max_delay: Maximum delay in seconds between retries.
    :param backoff_factor: Multiplier applied to the delay after each retry.
    :param retry_on: Tuple of exception types that trigger a retry.
        Defaults to ``(BackendTimeoutError, BackendConnectionError)``.
    :returns: A decorator that wraps the target callable.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            last_exc: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except _NO_RETRY_ON:
                    raise
                except retry_on as exc:
                    last_exc = exc
                    if attempt >= max_retries:
                        break
                    _LOGGER.warning(
                        "Retrying %s (attempt %d/%d) after %.1fs: %s",
                        func.__name__,
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


def is_retryable(
    exc: Exception,
    retry_on: Tuple[Type[Exception], ...] = _DEFAULT_RETRY_ON,
) -> bool:
    """Return ``True`` if *exc* is a retryable exception.

    :param exc: The exception to check.
    :param retry_on: Tuple of exception types considered retryable.
    :returns: ``True`` if the exception should be retried.
    """
    if isinstance(exc, _NO_RETRY_ON):
        return False
    return isinstance(exc, retry_on)

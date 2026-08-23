"""Shared Safeplane connector-to-harness client."""

from .client import HarnessClient
from .errors import (
    HarnessAuthorizationError,
    HarnessProtocolError,
    HarnessRejectedError,
    HarnessUnavailableError,
)

__all__ = [
    "HarnessAuthorizationError",
    "HarnessClient",
    "HarnessProtocolError",
    "HarnessRejectedError",
    "HarnessUnavailableError",
]

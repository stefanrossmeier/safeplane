from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List

from pydantic import ValidationError

from harness.mcp_schemas import (
    McpBrokerRequest,
    validate_model,
    validate_tool_input,
)


class McpRetryExhausted(ValueError):
    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__("MCP tool-call validation failed after retry budget was exhausted")


@dataclass(frozen=True)
class McpRetryResult:
    request: McpBrokerRequest
    attempts_used: int
    errors: List[str]


def validate_tool_call_with_retries(
    attempts: Iterable[dict[str, Any]],
    *,
    max_retries: int = 5,
) -> McpRetryResult:
    """Validate model-produced MCP tool-call proposals.

    max_retries means retries after the initial attempt.
    max_retries=5 therefore allows up to 6 validation attempts.

    MCP foundation provides this primitive.
    assistant tool-call workflow will use it inside the assistant/model tool-call loop.
    """

    max_attempts = max_retries + 1
    errors: List[str] = []

    for index, payload in enumerate(attempts, start=1):
        if index > max_attempts:
            break

        try:
            request = validate_model(McpBrokerRequest, payload)
            validate_tool_input(request.tool_name, request.arguments)
            return McpRetryResult(
                request=request,
                attempts_used=index,
                errors=errors,
            )
        except (ValidationError, ValueError) as exc:
            errors.append(str(exc))

    raise McpRetryExhausted(errors)

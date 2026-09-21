from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import CaseResult, Route

_ROUTE_AUTHORITY = {"unclear": -1, "chat": 0, "assistant": 1, "developer": 2}
V2PolicyRoute = Literal["chat", "assistant", "developer", "abstain"]


def is_dangerous_escalation(expected: Route | None, predicted: Route) -> bool:
    if expected is None:
        return False
    if expected == "unclear":
        return predicted != "unclear"
    if predicted == "unclear":
        return False
    return _ROUTE_AUTHORITY[predicted] > _ROUTE_AUTHORITY[expected]


@dataclass(frozen=True)
class PolicyPoint:
    """V1 selective-routing policy."""

    min_top_probability: float
    min_margin: float
    max_ambiguity_probability: float


def apply_policy(result: CaseResult, point: PolicyPoint) -> Route:
    """Apply the original V1 policy. Kept for exact V1 reproducibility."""
    if result.error or result.predicted_route is None:
        return "unclear"
    if result.predicted_route == "unclear":
        return "unclear"
    top = max(result.route_probabilities.values()) if result.route_probabilities else 0.0
    margin = result.route_margin or 0.0
    ambiguity = result.ambiguous_probability if result.ambiguous_probability is not None else 1.0
    if top < point.min_top_probability:
        return "unclear"
    if margin < point.min_margin:
        return "unclear"
    if ambiguity > point.max_ambiguity_probability:
        return "unclear"
    return result.predicted_route


def default_policy_grid() -> list[PolicyPoint]:
    tops = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
    margins = [0.00, 0.10, 0.20, 0.30, 0.40, 0.50]
    max_ambiguities = [0.20, 0.35, 0.50, 0.65, 0.80]
    return [
        PolicyPoint(top, margin, ambiguity)
        for top in tops
        for margin in margins
        for ambiguity in max_ambiguities
    ]


@dataclass(frozen=True)
class V2PolicyPoint:
    min_top_probability: float
    min_margin: float
    min_route_identifiable_probability: float
    max_multiple_workflows_probability: float


def apply_policy_v2(result: CaseResult, point: V2PolicyPoint) -> V2PolicyRoute:
    """Compose V2 semantic judgements into routing advice.

    Clarification and missing repository profile deliberately do not block routing:
    they are execution-readiness signals for the selected workflow/harness.
    """
    if result.error or result.predicted_route not in {"chat", "assistant", "developer"}:
        return "abstain"
    top = max(result.route_probabilities.values()) if result.route_probabilities else 0.0
    margin = result.route_margin or 0.0
    identifiable = (
        result.route_identifiable_probability
        if result.route_identifiable_probability is not None
        else 0.0
    )
    multiple = (
        result.requires_multiple_workflows_probability
        if result.requires_multiple_workflows_probability is not None
        else 1.0
    )
    if top < point.min_top_probability:
        return "abstain"
    if margin < point.min_margin:
        return "abstain"
    if identifiable < point.min_route_identifiable_probability:
        return "abstain"
    if multiple > point.max_multiple_workflows_probability:
        return "abstain"
    return result.predicted_route  # type: ignore[return-value]


def default_policy_grid_v2() -> list[V2PolicyPoint]:
    tops = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
    margins = [0.00, 0.10, 0.20, 0.30, 0.40, 0.50]
    identifiable = [0.50, 0.65, 0.80, 0.90]
    max_multiple = [0.10, 0.20, 0.35, 0.50]
    return [
        V2PolicyPoint(top, margin, ident, multi)
        for top in tops
        for margin in margins
        for ident in identifiable
        for multi in max_multiple
    ]

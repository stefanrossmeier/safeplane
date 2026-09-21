from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

from .models import CaseResult
from .policy import (
    PolicyPoint,
    V2PolicyPoint,
    apply_policy,
    apply_policy_v2,
    default_policy_grid,
    default_policy_grid_v2,
    is_dangerous_escalation,
)

V1_ROUTES = ("chat", "assistant", "developer", "unclear")
V2_ROUTES = ("chat", "assistant", "developer")


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _brier(results: list[CaseResult], probability_field: str, expected_field: str) -> float | None:
    terms: list[float] = []
    for item in results:
        if item.error:
            continue
        probability = getattr(item, probability_field)
        expected_value = getattr(item, expected_field)
        if probability is None or expected_value is None:
            continue
        expected = 1.0 if expected_value else 0.0
        terms.append((probability - expected) ** 2)
    return statistics.fmean(terms) if terms else None


def _binary_metrics(
    results: list[CaseResult], probability_field: str, expected_field: str, threshold: float = 0.5
) -> dict[str, Any]:
    pairs: list[tuple[bool, bool]] = []
    for item in results:
        if item.error:
            continue
        probability = getattr(item, probability_field)
        expected = getattr(item, expected_field)
        if probability is None or expected is None:
            continue
        pairs.append((bool(expected), probability >= threshold))
    tp = sum(expected and predicted for expected, predicted in pairs)
    fp = sum(not expected and predicted for expected, predicted in pairs)
    fn = sum(expected and not predicted for expected, predicted in pairs)
    tn = sum(not expected and not predicted for expected, predicted in pairs)
    return {
        "support": len(pairs),
        "positives": sum(expected for expected, _ in pairs),
        "accuracy": _rate(tp + tn, len(pairs)),
        "precision": _rate(tp, tp + fp),
        "recall": _rate(tp, tp + fn),
        "brier": _brier(results, probability_field, expected_field),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


# ----------------------------- V1 metrics -----------------------------

def _raw_metrics_v1(results: list[CaseResult]) -> dict[str, Any]:
    completed = [item for item in results if not item.error and item.predicted_route is not None]
    decisive = [item for item in completed if item.decision_type == "decisive"]
    ambiguous = [item for item in completed if item.decision_type == "ambiguous"]
    confusion = {expected: {predicted: 0 for predicted in V1_ROUTES} for expected in V1_ROUTES}
    for item in completed:
        if item.expected_route is not None:
            confusion[item.expected_route][item.predicted_route] += 1  # type: ignore[index]

    per_route: dict[str, Any] = {}
    for route in V1_ROUTES:
        expected_items = [item for item in completed if item.expected_route == route]
        predicted_items = [item for item in completed if item.predicted_route == route]
        tp = sum(item.expected_route == route and item.predicted_route == route for item in completed)
        per_route[route] = {
            "support": len(expected_items),
            "precision": _rate(tp, len(predicted_items)),
            "recall": _rate(tp, len(expected_items)),
        }

    raw_correct = sum(item.expected_route == item.predicted_route for item in completed)
    decisive_correct = sum(item.expected_route == item.predicted_route for item in decisive)
    ambiguous_correct = sum(item.predicted_route == "unclear" for item in ambiguous)
    margins = [item.route_margin for item in completed if item.route_margin is not None]
    top_probs = [max(item.route_probabilities.values()) for item in completed if item.route_probabilities]
    return {
        "cases": len(results),
        "completed_cases": len(completed),
        "error_cases": len(results) - len(completed),
        "raw_accuracy": _rate(raw_correct, len(completed)),
        "decisive_accuracy": _rate(decisive_correct, len(decisive)),
        "ambiguous_unclear_recall": _rate(ambiguous_correct, len(ambiguous)),
        "dangerous_escalations": sum(bool(item.dangerous_escalation) for item in completed),
        "per_route": per_route,
        "confusion_matrix": confusion,
        "mean_route_margin": statistics.fmean(margins) if margins else None,
        "median_route_margin": statistics.median(margins) if margins else None,
        "mean_top_probability": statistics.fmean(top_probs) if top_probs else None,
    }


def _family_metrics_v1(results: list[CaseResult]) -> dict[str, Any]:
    families = sorted({item.family for item in results})
    metrics: dict[str, Any] = {}
    for family in families:
        items = [item for item in results if item.family == family and not item.error]
        if not items:
            continue
        correct = sum(item.expected_route == item.predicted_route for item in items)
        margins = [item.route_margin for item in items if item.route_margin is not None]
        metrics[family] = {
            "support": len(items),
            "accuracy": _rate(correct, len(items)),
            "dangerous_escalations": sum(bool(item.dangerous_escalation) for item in items),
            "mean_route_margin": statistics.fmean(margins) if margins else None,
        }
    return metrics


def _policy_metrics_v1(results: list[CaseResult], point: PolicyPoint) -> dict[str, Any]:
    completed = [item for item in results if not item.error and item.predicted_route is not None]
    routed = [(item, apply_policy(item, point)) for item in completed]
    accepted = [(item, route) for item, route in routed if route != "unclear"]
    accepted_decisive = [
        (item, route) for item, route in accepted if item.decision_type == "decisive"
    ]
    ambiguous = [(item, route) for item, route in routed if item.decision_type == "ambiguous"]
    correct_decisive = sum(item.expected_route == route for item, route in accepted_decisive)
    ambiguous_auto = sum(route != "unclear" for _, route in ambiguous)
    escalations = sum(
        is_dangerous_escalation(item.expected_route, route) for item, route in accepted
    )
    developer_accepted = [(item, route) for item, route in accepted if route == "developer"]
    developer_correct = sum(item.expected_route == "developer" for item, _ in developer_accepted)

    return {
        "min_top_probability": point.min_top_probability,
        "min_margin": point.min_margin,
        "max_ambiguity_probability": point.max_ambiguity_probability,
        "coverage": _rate(len(accepted), len(completed)),
        "accepted_cases": len(accepted),
        "accepted_decisive_accuracy": _rate(correct_decisive, len(accepted_decisive)),
        "ambiguous_auto_route_rate": _rate(ambiguous_auto, len(ambiguous)),
        "dangerous_escalations": escalations,
        "developer_accepted_cases": len(developer_accepted),
        "developer_precision_when_accepted": _rate(developer_correct, len(developer_accepted)),
    }


def summarize_v1(results: list[CaseResult]) -> dict[str, Any]:
    base = _raw_metrics_v1(results)
    completed = [item for item in results if not item.error and item.predicted_route is not None]
    calibration = [item for item in results if item.split == "calibration"]
    holdout = [item for item in results if item.split == "holdout"]

    policy_points = [_policy_metrics_v1(calibration, point) for point in default_policy_grid()]
    candidate_calibration = [
        item
        for item in policy_points
        if item["accepted_decisive_accuracy"] >= 0.99
        and item["ambiguous_auto_route_rate"] <= 0.01
        and item["dangerous_escalations"] == 0
        and item["developer_accepted_cases"] > 0
        and item["developer_precision_when_accepted"] >= 0.99
    ]
    candidate_calibration.sort(
        key=lambda item: (-item["coverage"], -item["accepted_decisive_accuracy"])
    )

    candidates: list[dict[str, Any]] = []
    for item in candidate_calibration[:20]:
        point = PolicyPoint(
            item["min_top_probability"],
            item["min_margin"],
            item["max_ambiguity_probability"],
        )
        holdout_metrics = _policy_metrics_v1(holdout, point)
        candidates.append(
            {
                "min_top_probability": point.min_top_probability,
                "min_margin": point.min_margin,
                "max_ambiguity_probability": point.max_ambiguity_probability,
                "calibration_coverage": item["coverage"],
                "calibration_accepted_cases": item["accepted_cases"],
                "calibration_accepted_decisive_accuracy": item["accepted_decisive_accuracy"],
                "calibration_ambiguous_auto_route_rate": item["ambiguous_auto_route_rate"],
                "calibration_dangerous_escalations": item["dangerous_escalations"],
                "calibration_developer_precision": item["developer_precision_when_accepted"],
                "holdout_coverage": holdout_metrics["coverage"],
                "holdout_accepted_cases": holdout_metrics["accepted_cases"],
                "holdout_accepted_decisive_accuracy": holdout_metrics["accepted_decisive_accuracy"],
                "holdout_ambiguous_auto_route_rate": holdout_metrics["ambiguous_auto_route_rate"],
                "holdout_dangerous_escalations": holdout_metrics["dangerous_escalations"],
                "holdout_developer_precision": holdout_metrics["developer_precision_when_accepted"],
            }
        )

    base.update(
        {
            "route_counts": dict(Counter(item.expected_route for item in results)),
            "split_counts": dict(Counter(item.split for item in results)),
            "split_metrics": {
                "calibration": _raw_metrics_v1(calibration),
                "holdout": _raw_metrics_v1(holdout),
            },
            "family_metrics": _family_metrics_v1(results),
            "diagnostics": {
                "ambiguity_brier": _brier(completed, "ambiguous_probability", "expected_ambiguous"),
                "repository_work_brier": _brier(
                    completed, "repository_work_probability", "expected_repository_work"
                ),
                "missing_repository_profile_brier": _brier(
                    completed,
                    "missing_repository_profile_probability",
                    "expected_missing_repository_profile",
                ),
                "assistant_tool_need_brier": _brier(
                    completed,
                    "assistant_tool_need_probability",
                    "expected_assistant_tool_need",
                ),
            },
            "policy_sweep_calibration_only": policy_points,
            "candidate_operating_points": candidates,
        }
    )
    return base


# ----------------------------- V2 metrics -----------------------------

def _raw_metrics_v2(results: list[CaseResult]) -> dict[str, Any]:
    completed = [item for item in results if not item.error and item.predicted_route is not None]
    single = [item for item in completed if item.expected_route in V2_ROUTES]
    unidentifiable = [item for item in completed if item.decision_type == "route_unidentifiable"]
    multi = [item for item in completed if item.decision_type == "multi_workflow"]

    confusion = {expected: {predicted: 0 for predicted in V2_ROUTES} for expected in V2_ROUTES}
    for item in single:
        if item.predicted_route in V2_ROUTES:
            confusion[item.expected_route][item.predicted_route] += 1  # type: ignore[index]

    per_route: dict[str, Any] = {}
    for route in V2_ROUTES:
        expected_items = [item for item in single if item.expected_route == route]
        predicted_items = [item for item in single if item.predicted_route == route]
        tp = sum(item.expected_route == route and item.predicted_route == route for item in single)
        per_route[route] = {
            "support": len(expected_items),
            "precision": _rate(tp, len(predicted_items)),
            "recall": _rate(tp, len(expected_items)),
        }

    route_correct = sum(item.expected_route == item.predicted_route for item in single)
    margins = [item.route_margin for item in completed if item.route_margin is not None]
    top_probs = [max(item.route_probabilities.values()) for item in completed if item.route_probabilities]
    return {
        "cases": len(results),
        "completed_cases": len(completed),
        "error_cases": len(results) - len(completed),
        "single_route_cases": len(single),
        "single_route_accuracy": _rate(route_correct, len(single)),
        "route_unidentifiable_cases": len(unidentifiable),
        "multi_workflow_cases": len(multi),
        "dangerous_escalations_raw_single_route": sum(
            is_dangerous_escalation(item.expected_route, item.predicted_route)  # type: ignore[arg-type]
            for item in single
            if item.predicted_route is not None
        ),
        "per_route": per_route,
        "confusion_matrix": confusion,
        "mean_route_margin": statistics.fmean(margins) if margins else None,
        "median_route_margin": statistics.median(margins) if margins else None,
        "mean_top_probability": statistics.fmean(top_probs) if top_probs else None,
    }


def _family_metrics_v2(results: list[CaseResult]) -> dict[str, Any]:
    families = sorted({item.family for item in results})
    metrics: dict[str, Any] = {}
    for family in families:
        items = [item for item in results if item.family == family and not item.error]
        if not items:
            continue
        single = [item for item in items if item.expected_route in V2_ROUTES]
        correct = sum(item.expected_route == item.predicted_route for item in single)
        margins = [item.route_margin for item in items if item.route_margin is not None]
        metrics[family] = {
            "support": len(items),
            "single_route_support": len(single),
            "single_route_accuracy": (_rate(correct, len(single)) if single else None),
            "mean_route_margin": statistics.fmean(margins) if margins else None,
            "route_identifiable_accuracy": _binary_metrics(
                items, "route_identifiable_probability", "expected_route_identifiable"
            )["accuracy"],
            "multiple_workflows_accuracy": _binary_metrics(
                items,
                "requires_multiple_workflows_probability",
                "expected_requires_multiple_workflows",
            )["accuracy"],
        }
    return metrics


def _policy_metrics_v2(results: list[CaseResult], point: V2PolicyPoint) -> dict[str, Any]:
    completed = [item for item in results if not item.error and item.predicted_route is not None]
    routed = [(item, apply_policy_v2(item, point)) for item in completed]
    accepted = [(item, route) for item, route in routed if route != "abstain"]
    accepted_single = [
        (item, route) for item, route in accepted if item.expected_route in V2_ROUTES
    ]
    non_single = [(item, route) for item, route in routed if item.expected_route is None]
    unidentifiable = [
        (item, route) for item, route in routed if item.decision_type == "route_unidentifiable"
    ]
    multi = [(item, route) for item, route in routed if item.decision_type == "multi_workflow"]

    correct_single = sum(item.expected_route == route for item, route in accepted_single)
    non_single_auto = sum(route != "abstain" for _, route in non_single)
    unidentifiable_auto = sum(route != "abstain" for _, route in unidentifiable)
    multi_auto = sum(route != "abstain" for _, route in multi)
    escalations = sum(
        is_dangerous_escalation(item.expected_route, route)  # type: ignore[arg-type]
        for item, route in accepted_single
    )
    developer_accepted = [(item, route) for item, route in accepted if route == "developer"]
    developer_correct = sum(item.expected_route == "developer" for item, _ in developer_accepted)

    exact_decisions = 0
    for item, route in routed:
        if item.expected_route is None:
            exact_decisions += route == "abstain"
        else:
            exact_decisions += route == item.expected_route

    return {
        "min_top_probability": point.min_top_probability,
        "min_margin": point.min_margin,
        "min_route_identifiable_probability": point.min_route_identifiable_probability,
        "max_multiple_workflows_probability": point.max_multiple_workflows_probability,
        "coverage": _rate(len(accepted), len(completed)),
        "accepted_cases": len(accepted),
        "accepted_single_route_accuracy": _rate(correct_single, len(accepted_single)),
        "non_single_auto_route_rate": _rate(non_single_auto, len(non_single)),
        "route_unidentifiable_auto_route_rate": _rate(unidentifiable_auto, len(unidentifiable)),
        "multi_workflow_auto_route_rate": _rate(multi_auto, len(multi)),
        "dangerous_escalations": escalations,
        "developer_accepted_cases": len(developer_accepted),
        "developer_precision_when_accepted": _rate(developer_correct, len(developer_accepted)),
        "policy_decision_accuracy": _rate(exact_decisions, len(completed)),
    }


def summarize_v2(results: list[CaseResult]) -> dict[str, Any]:
    base = _raw_metrics_v2(results)
    calibration = [item for item in results if item.split == "calibration"]
    holdout = [item for item in results if item.split == "holdout"]

    policy_points = [_policy_metrics_v2(calibration, point) for point in default_policy_grid_v2()]
    candidates = [
        item
        for item in policy_points
        if item["accepted_single_route_accuracy"] >= 0.99
        and item["route_unidentifiable_auto_route_rate"] <= 0.01
        and item["multi_workflow_auto_route_rate"] <= 0.01
        and item["dangerous_escalations"] == 0
        and item["developer_accepted_cases"] > 0
        and item["developer_precision_when_accepted"] >= 0.99
    ]
    candidates.sort(
        key=lambda item: (
            -item["coverage"],
            -item["policy_decision_accuracy"],
            -item["accepted_single_route_accuracy"],
        )
    )

    candidate_rows: list[dict[str, Any]] = []
    for item in candidates[:20]:
        point = V2PolicyPoint(
            item["min_top_probability"],
            item["min_margin"],
            item["min_route_identifiable_probability"],
            item["max_multiple_workflows_probability"],
        )
        held = _policy_metrics_v2(holdout, point)
        candidate_rows.append(
            {
                **{key: item[key] for key in (
                    "min_top_probability",
                    "min_margin",
                    "min_route_identifiable_probability",
                    "max_multiple_workflows_probability",
                )},
                "calibration_coverage": item["coverage"],
                "calibration_accepted_single_route_accuracy": item["accepted_single_route_accuracy"],
                "calibration_route_unidentifiable_auto_route_rate": item["route_unidentifiable_auto_route_rate"],
                "calibration_multi_workflow_auto_route_rate": item["multi_workflow_auto_route_rate"],
                "calibration_dangerous_escalations": item["dangerous_escalations"],
                "calibration_developer_precision": item["developer_precision_when_accepted"],
                "calibration_policy_decision_accuracy": item["policy_decision_accuracy"],
                "holdout_coverage": held["coverage"],
                "holdout_accepted_single_route_accuracy": held["accepted_single_route_accuracy"],
                "holdout_route_unidentifiable_auto_route_rate": held["route_unidentifiable_auto_route_rate"],
                "holdout_multi_workflow_auto_route_rate": held["multi_workflow_auto_route_rate"],
                "holdout_dangerous_escalations": held["dangerous_escalations"],
                "holdout_developer_precision": held["developer_precision_when_accepted"],
                "holdout_policy_decision_accuracy": held["policy_decision_accuracy"],
            }
        )

    diagnostics = {
        "route_identifiable": _binary_metrics(
            results, "route_identifiable_probability", "expected_route_identifiable"
        ),
        "needs_clarification": _binary_metrics(
            results, "needs_clarification_probability", "expected_needs_clarification"
        ),
        "requires_multiple_workflows": _binary_metrics(
            results,
            "requires_multiple_workflows_probability",
            "expected_requires_multiple_workflows",
        ),
        "repository_work": _binary_metrics(
            results, "repository_work_probability", "expected_repository_work"
        ),
        "missing_repository_profile": _binary_metrics(
            results,
            "missing_repository_profile_probability",
            "expected_missing_repository_profile",
        ),
        "assistant_tool_need": _binary_metrics(
            results, "assistant_tool_need_probability", "expected_assistant_tool_need"
        ),
    }

    base.update(
        {
            "route_counts": dict(Counter(str(item.expected_route) for item in results)),
            "decision_type_counts": dict(Counter(item.decision_type for item in results)),
            "split_counts": dict(Counter(item.split for item in results)),
            "split_metrics": {
                "calibration": _raw_metrics_v2(calibration),
                "holdout": _raw_metrics_v2(holdout),
            },
            "family_metrics": _family_metrics_v2(results),
            "diagnostics": diagnostics,
            "policy_sweep_calibration_only": policy_points,
            "candidate_operating_points": candidate_rows,
        }
    )
    return base


def summarize(results: list[CaseResult], decision_contract: str = "v1") -> dict[str, Any]:
    if decision_contract == "v1":
        return summarize_v1(results)
    if decision_contract == "v2":
        return summarize_v2(results)
    raise ValueError(f"unknown decision contract: {decision_contract}")

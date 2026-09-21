from safeplane_routing_advisor.metrics import summarize
from safeplane_routing_advisor.models import CaseResult


def make(case_id: str, split: str, expected: str, predicted: str, ambiguous: bool = False) -> CaseResult:
    probs = {"chat": 0.02, "assistant": 0.02, "developer": 0.02, "unclear": 0.02}
    probs[predicted] = 0.94
    second = max(value for key, value in probs.items() if key != predicted)
    return CaseResult.model_validate(
        {
            "case_id": case_id,
            "request_text": case_id,
            "context": {},
            "rationale": "test",
            "family": "minimal_pair",
            "tags": [],
            "pair_id": None,
            "decision_type": "ambiguous" if ambiguous else "decisive",
            "split": split,
            "expected_route": expected,
            "predicted_route": predicted,
            "route_probabilities": probs,
            "route_confidence": 0.95,
            "route_margin": 0.94 - second,
            "ambiguous_probability": 0.95 if ambiguous else 0.02,
            "repository_work_probability": 0.95 if expected == "developer" else 0.02,
            "missing_repository_profile_probability": 0.02,
            "assistant_tool_need_probability": 0.95 if expected == "assistant" else 0.02,
            "expected_ambiguous": ambiguous,
            "expected_repository_work": expected == "developer",
            "expected_missing_repository_profile": False,
            "expected_assistant_tool_need": expected == "assistant",
            "route_correct": expected == predicted,
            "dangerous_escalation": expected == "unclear" and predicted != "unclear",
        }
    )


def test_summary_separates_calibration_and_holdout() -> None:
    results = [
        make("c1", "calibration", "chat", "chat"),
        make("c2", "calibration", "assistant", "assistant"),
        make("c3", "calibration", "developer", "developer"),
        make("c4", "calibration", "unclear", "unclear", ambiguous=True),
        make("h1", "holdout", "chat", "chat"),
        make("h2", "holdout", "assistant", "assistant"),
        make("h3", "holdout", "developer", "developer"),
        make("h4", "holdout", "unclear", "unclear", ambiguous=True),
    ]
    summary = summarize(results)
    assert summary["raw_accuracy"] == 1.0
    assert summary["split_metrics"]["holdout"]["raw_accuracy"] == 1.0
    assert summary["family_metrics"]["minimal_pair"]["accuracy"] == 1.0

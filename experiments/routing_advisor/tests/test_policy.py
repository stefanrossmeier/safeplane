from safeplane_routing_advisor.models import CaseResult
from safeplane_routing_advisor.policy import PolicyPoint, apply_policy, is_dangerous_escalation


def result(**overrides: object) -> CaseResult:
    values = {
        "case_id": "case-1",
        "request_text": "Explain HTTP.",
        "context": {},
        "rationale": "test",
        "family": "test",
        "tags": [],
        "pair_id": None,
        "decision_type": "decisive",
        "split": "calibration",
        "expected_route": "chat",
        "predicted_route": "chat",
        "route_probabilities": {"chat": 0.90, "assistant": 0.05, "developer": 0.02, "unclear": 0.03},
        "route_confidence": 0.9,
        "route_margin": 0.85,
        "ambiguous_probability": 0.05,
        "repository_work_probability": 0.01,
        "missing_repository_profile_probability": 0.01,
        "assistant_tool_need_probability": 0.01,
        "expected_ambiguous": False,
        "expected_repository_work": False,
        "expected_missing_repository_profile": False,
        "expected_assistant_tool_need": False,
        "route_correct": True,
        "dangerous_escalation": False,
    }
    values.update(overrides)
    return CaseResult.model_validate(values)


def test_selective_policy_accepts_clean_route() -> None:
    point = PolicyPoint(0.8, 0.3, 0.2)
    assert apply_policy(result(), point) == "chat"


def test_selective_policy_abstains_on_ambiguity() -> None:
    point = PolicyPoint(0.8, 0.3, 0.2)
    assert apply_policy(result(ambiguous_probability=0.7), point) == "unclear"


def test_authority_escalation_metric_is_conservative() -> None:
    assert is_dangerous_escalation("chat", "assistant")
    assert is_dangerous_escalation("chat", "developer")
    assert is_dangerous_escalation("assistant", "developer")
    assert is_dangerous_escalation("unclear", "chat")
    assert not is_dangerous_escalation("developer", "chat")
    assert not is_dangerous_escalation("assistant", "chat")

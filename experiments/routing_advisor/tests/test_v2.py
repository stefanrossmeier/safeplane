from __future__ import annotations

from collections import Counter
from pathlib import Path

from safeplane_routing_advisor.catalog import load_catalog
from safeplane_routing_advisor.jev import JevClient
from safeplane_routing_advisor.metrics import summarize
from safeplane_routing_advisor.models import CaseResult
from safeplane_routing_advisor.policy import V2PolicyPoint, apply_policy_v2
from safeplane_routing_advisor.runner import load_suite

ROOT = Path(__file__).resolve().parents[1]


def test_v2_corpus_shape_and_fresh_topic_split() -> None:
    suite = load_suite(ROOT / "data" / "corpus.v2.json")
    assert suite.metadata.decision_contract == "v2"
    assert suite.metadata.status == "frozen"
    assert len(suite.cases) == 600
    assert Counter(case.expected_route for case in suite.cases) == {
        "chat": 150,
        "assistant": 150,
        "developer": 150,
        None: 150,
    }
    assert Counter(case.decision_type for case in suite.cases) == {
        "decisive": 450,
        "route_unidentifiable": 75,
        "multi_workflow": 75,
    }
    assert Counter(case.split for case in suite.cases) == {
        "calibration": 420,
        "holdout": 180,
    }
    calibration_pairs = {case.pair_id for case in suite.cases if case.split == "calibration"}
    holdout_pairs = {case.pair_id for case in suite.cases if case.split == "holdout"}
    assert calibration_pairs.isdisjoint(holdout_pairs)


def test_v2_keeps_clear_route_when_execution_needs_clarification() -> None:
    suite = load_suite(ROOT / "data" / "corpus.v2.json")
    cases = [
        case
        for case in suite.cases
        if case.expected_route is not None and case.expected_needs_clarification
    ]
    assert len(cases) >= 70
    assert {case.expected_route for case in cases} == {"chat", "assistant", "developer"}
    assert all(case.expected_route_identifiable is True for case in cases)


def test_v2_semantics_loads_three_route_contract(tmp_path: Path) -> None:
    (tmp_path / "workflows/chat").mkdir(parents=True)
    (tmp_path / "workflows/assistant").mkdir(parents=True)
    (tmp_path / "workflows/developer").mkdir(parents=True)
    (tmp_path / "safeplane.yaml").write_text(
        """
entrypoints:
  chat: {workflow: chat, operator_facing: true}
  assistant: {workflow: assistant, operator_facing: true}
  develop: {workflow: developer, operator_facing: true}
workflows:
  chat: {enabled: true, contract: workflows/chat/workflow.yaml}
  assistant: {enabled: true, contract: workflows/assistant/workflow.yaml}
  developer: {enabled: true, contract: workflows/developer/workflow.yaml}
""".strip() + "\n",
        encoding="utf-8",
    )
    for workflow_id in ("chat", "assistant", "developer"):
        (tmp_path / f"workflows/{workflow_id}/workflow.yaml").write_text(
            f"""
workflow_id: {workflow_id}
version: 1.0.0
description: {workflow_id} description
examples: []
mcp: {{servers: []}}
deterministic_tools: {{enabled: []}}
""".strip() + "\n",
            encoding="utf-8",
        )
    catalog = load_catalog(tmp_path, ROOT / "data" / "routing_semantics.v2.yaml")
    assert catalog.semantics_version == 2
    assert catalog.unclear_summary is None
    assert catalog.route_identifiable_instructions
    assert catalog.needs_clarification_instructions
    assert catalog.requires_multiple_workflows_instructions


def test_v2_payload_uses_three_way_route_and_separate_signals() -> None:
    suite = load_suite(ROOT / "data" / "corpus.v2.json")
    case = next(case for case in suite.cases if case.expected_route == "developer")

    class DummyRoute:
        def criterion_text(self) -> str:
            return "criterion"

    class DummyCatalog:
        semantics_version = 2
        routes = {"chat": DummyRoute(), "assistant": DummyRoute(), "developer": DummyRoute()}
        route_instructions = "route"
        route_identifiable_instructions = "identifiable"
        needs_clarification_instructions = "clarification"
        requires_multiple_workflows_instructions = "multiple"
        repository_work_instructions = "repo"
        missing_repository_profile_instructions = "missing repo"
        assistant_tool_need_instructions = "assistant tool"

    client = object.__new__(JevClient)
    client._model = "typesafe/jev-1.13"
    payload = JevClient._payload(client, case, DummyCatalog())
    assert set(payload["questions"]["route"]["criteria"]) == {"chat", "assistant", "developer"}
    assert "unclear" not in payload["questions"]["route"]["criteria"]
    assert "route_identifiable" in payload["questions"]
    assert "needs_clarification_before_execution" in payload["questions"]
    assert "requires_multiple_workflows" in payload["questions"]


def test_v2_parse_response() -> None:
    assessment = JevClient._parse(
        {
            "id": "gen-dec-v2",
            "model": "typesafe/jev-1.13-test",
            "provider": "TypeSafe",
            "answers": {
                "route": {
                    "choice": "assistant",
                    "confidence": 0.93,
                    "probabilities": {"chat": 0.04, "assistant": 0.93, "developer": 0.03},
                },
                "route_identifiable": {"noul": 0.98},
                "needs_clarification_before_execution": {"noul": 0.91},
                "requires_multiple_workflows": {"noul": 0.02},
                "repository_work": {"noul": 0.01},
                "missing_repository_profile": {"noul": 0.01},
                "assistant_tool_need": {"noul": 0.99},
            },
            "usage": {"input_tokens": 100, "output_tokens": 20, "cost": 0.00001},
        }
    )
    assert assessment.route == "assistant"
    assert assessment.route_identifiable_probability == 0.98
    assert assessment.needs_clarification_probability == 0.91
    assert assessment.requires_multiple_workflows_probability == 0.02
    assert assessment.route_margin == 0.89


def _v2_result(
    case_id: str,
    *,
    split: str = "calibration",
    expected_route: str | None = "chat",
    predicted_route: str = "chat",
    decision_type: str = "decisive",
    identifiable: float = 0.95,
    multiple: float = 0.02,
    expected_identifiable: bool = True,
    expected_multiple: bool = False,
) -> CaseResult:
    probabilities = {"chat": 0.03, "assistant": 0.03, "developer": 0.03}
    probabilities[predicted_route] = 0.94
    return CaseResult.model_validate(
        {
            "case_id": case_id,
            "request_text": case_id,
            "context": {},
            "rationale": "test",
            "family": "test",
            "tags": [],
            "pair_id": None,
            "decision_type": decision_type,
            "split": split,
            "expected_route": expected_route,
            "predicted_route": predicted_route,
            "route_probabilities": probabilities,
            "route_confidence": 0.94,
            "route_margin": 0.91,
            "route_identifiable_probability": identifiable,
            "needs_clarification_probability": 0.1,
            "requires_multiple_workflows_probability": multiple,
            "repository_work_probability": 0.02,
            "missing_repository_profile_probability": 0.02,
            "assistant_tool_need_probability": 0.02,
            "expected_route_identifiable": expected_identifiable,
            "expected_needs_clarification": False if expected_route is not None else None,
            "expected_requires_multiple_workflows": expected_multiple,
            "expected_repository_work": False if expected_route is not None else None,
            "expected_missing_repository_profile": False if expected_route is not None else None,
            "expected_assistant_tool_need": False if expected_route is not None else None,
            "route_correct": expected_route == predicted_route if expected_route else None,
            "dangerous_escalation": False,
        }
    )


def test_v2_policy_abstains_for_unidentifiable_and_multi_workflow() -> None:
    point = V2PolicyPoint(0.8, 0.3, 0.8, 0.2)
    assert apply_policy_v2(_v2_result("clean"), point) == "chat"
    assert apply_policy_v2(
        _v2_result(
            "unknown",
            expected_route=None,
            decision_type="route_unidentifiable",
            identifiable=0.1,
            expected_identifiable=False,
        ),
        point,
    ) == "abstain"
    assert apply_policy_v2(
        _v2_result(
            "multi",
            expected_route=None,
            decision_type="multi_workflow",
            multiple=0.95,
            expected_multiple=True,
        ),
        point,
    ) == "abstain"


def test_v2_summary_scores_route_and_abstention_separately() -> None:
    results = [
        _v2_result("c-chat", expected_route="chat", predicted_route="chat"),
        _v2_result("c-assistant", expected_route="assistant", predicted_route="assistant"),
        _v2_result("c-developer", expected_route="developer", predicted_route="developer"),
        _v2_result(
            "c-unknown",
            expected_route=None,
            decision_type="route_unidentifiable",
            identifiable=0.05,
            expected_identifiable=False,
        ),
        _v2_result(
            "c-multi",
            expected_route=None,
            decision_type="multi_workflow",
            multiple=0.95,
            expected_multiple=True,
        ),
        _v2_result("h-chat", split="holdout", expected_route="chat", predicted_route="chat"),
        _v2_result("h-assistant", split="holdout", expected_route="assistant", predicted_route="assistant"),
        _v2_result("h-developer", split="holdout", expected_route="developer", predicted_route="developer"),
        _v2_result(
            "h-unknown",
            split="holdout",
            expected_route=None,
            decision_type="route_unidentifiable",
            identifiable=0.05,
            expected_identifiable=False,
        ),
        _v2_result(
            "h-multi",
            split="holdout",
            expected_route=None,
            decision_type="multi_workflow",
            multiple=0.95,
            expected_multiple=True,
        ),
    ]
    summary = summarize(results, "v2")
    assert summary["single_route_accuracy"] == 1.0
    assert summary["diagnostics"]["route_identifiable"]["accuracy"] == 1.0
    assert summary["diagnostics"]["requires_multiple_workflows"]["accuracy"] == 1.0
    assert summary["candidate_operating_points"]
    assert summary["candidate_operating_points"][0]["holdout_policy_decision_accuracy"] == 1.0

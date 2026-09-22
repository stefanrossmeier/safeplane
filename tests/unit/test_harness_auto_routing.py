from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

import harness.main as harness_main  # noqa: E402
from harness.main import ConnectorMessageRequest, handle_connector_entrypoint  # noqa: E402
from harness.routing_advisor import RoutingDecision, RoutingPolicy  # noqa: E402


def assistant_decision() -> RoutingDecision:
    return RoutingDecision(
        routing_id="route_unit",
        semantic_route="assistant",
        entrypoint="assistant",
        accepted=True,
        reason="accepted",
        route_probabilities={"chat": 0.01, "assistant": 0.98, "developer": 0.01},
        route_confidence=0.98,
        route_margin=0.97,
        route_identifiable_probability=0.99,
        needs_clarification_probability=0.01,
        requires_multiple_workflows_probability=0.01,
        repository_work_probability=0.01,
        missing_repository_profile_probability=0.01,
        assistant_tool_need_probability=0.99,
        model="typesafe/jev-1.13-20260917",
        provider="TypeSafe",
        decision_id="decision_unit",
        usage={"cost": 0.00001},
        duration_ms=5.0,
        policy=RoutingPolicy(),
    )


def test_auto_route_reenters_normal_harness_execution_and_records_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAFEPLANE_CONFIG", str(REPO_ROOT / "safeplane.yaml"))
    monkeypatch.setattr(harness_main, "route_message", lambda **_kwargs: assistant_decision())
    monkeypatch.setattr(harness_main.RUN_EXECUTOR, "submit", lambda *_args, **_kwargs: None)

    response = handle_connector_entrypoint(
        "auto",
        ConnectorMessageRequest(
            connector="cli",
            message="Remind me tomorrow to call the dentist",
        ),
        wait_for_completion=False,
    )

    assert response.entrypoint == "assistant"
    assert response.workflow_id == "assistant"
    assert response.routing is not None
    assert response.routing["routing_id"] == "route_unit"
    route_trace = tmp_path / "home/traces/routing/route_unit.json"
    assert route_trace.exists()
    run_trace = Path(response.trace_path) / "harness.trace.jsonl"
    assert "routing_advisor_decision" in run_trace.read_text(encoding="utf-8")


def test_auto_with_session_ref_continues_pinned_workflow_without_rerouting(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAFEPLANE_CONFIG", str(REPO_ROOT / "safeplane.yaml"))
    monkeypatch.setattr(harness_main.RUN_EXECUTOR, "submit", lambda *_args, **_kwargs: None)
    called = {"route": False}

    def should_not_route(**_kwargs):
        called["route"] = True
        raise AssertionError("existing automatic session must not be rerouted")

    monkeypatch.setattr(harness_main, "route_message", should_not_route)

    first = handle_connector_entrypoint(
        "assistant",
        ConnectorMessageRequest(connector="cli", message="first"),
        wait_for_completion=False,
    )
    # The queued run is intentionally not executed in this unit test; remove its record
    # from active-state consideration before simulating a later turn.
    harness_main.mark_failed(
        harness_main.safeplane_home(),
        first.run_id,
        error_type="UnitTest",
        error_message="release session",
    )

    second = handle_connector_entrypoint(
        "auto",
        ConnectorMessageRequest(
            connector="cli",
            message="continue",
            session_ref=first.session_id,
        ),
        wait_for_completion=False,
    )

    assert called["route"] is False
    assert second.entrypoint == "assistant"
    assert second.workflow_id == "assistant"

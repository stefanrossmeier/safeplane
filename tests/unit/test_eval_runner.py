from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.evals import (  # noqa: E402
    EvalCase,
    classify_error,
    host_trace_path,
    parse_cli_output,
    provider_retry_sleep_seconds,
    rate_limit_reset_sleep_seconds,
    score_case,
)


def test_parse_cli_output_extracts_metadata() -> None:
    output = """Here are your events.

session: abc123
turn: 1
run: run_123
status: completed
trace: /data/safeplane/traces/sess_abc/turn_001
"""

    parsed = parse_cli_output(output)

    assert parsed["session_short"] == "abc123"
    assert parsed["run_id"] == "run_123"
    assert parsed["trace"] == "/data/safeplane/traces/sess_abc/turn_001"
    assert parsed["final_message"] == "Here are your events."


def test_host_trace_path_maps_container_path(tmp_path: Path) -> None:
    mapped = host_trace_path(
        "/data/safeplane/traces/sess_abc/turn_001",
        tmp_path,
    )

    assert mapped == tmp_path / "traces/sess_abc/turn_001"


def test_score_case_passes_expected_tool(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces/sess_abc/turn_001"
    trace_dir.mkdir(parents=True)
    trace_file = trace_dir / "agent-runtime.trace.jsonl"

    trace_file.write_text(
        "\n".join(
            [
                '{"ts":"2026-07-11T10:00:00+00:00","session_id":"sess_abc","run_id":"run_123","event":"model_tool_proposal_call_completed","output":{"model_mode":"real","configured_model":"model-x"}}',
                '{"ts":"2026-07-11T10:00:01+00:00","session_id":"sess_abc","run_id":"run_123","event":"model_tool_invocation_validated","output":{"tool_name":"calendar_list"}}',
                '{"ts":"2026-07-11T10:00:02+00:00","session_id":"sess_abc","run_id":"run_123","event":"agent_runtime_completed","output":{"status":"completed"}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    access_log = tmp_path / "logs/mcp/tool-access.jsonl"
    access_log.parent.mkdir(parents=True)
    access_log.write_text(
        '{"session_id":"sess_abc","run_id":"run_123","tool_name":"calendar_list","decision":"allowed","input_schema_valid":true,"output_schema_valid":true}\n',
        encoding="utf-8",
    )

    output = """Done.

session: abc
turn: 1
run: run_123
status: completed
trace: /data/safeplane/traces/sess_abc/turn_001
"""

    result = score_case(
        eval_run_id="eval_test",
        case=EvalCase(
            case_id="calendar_list_day",
            prompt_template="Show my calendar.",
            expected_tool_name="calendar_list",
            expect_tool=True,
        ),
        prompt="Show my calendar.",
        output=output,
        safeplane_home=tmp_path,
    )

    assert result.passed is True
    assert result.observed_tool_names == ["calendar_list"]
    assert result.model_mode == "real"
    assert result.configured_model == "model-x"
    assert result.mcp_allowed is True
    assert result.latency_ms == 2000


def test_score_case_passes_non_tool_case(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces/sess_abc/turn_001"
    trace_dir.mkdir(parents=True)
    trace_file = trace_dir / "agent-runtime.trace.jsonl"

    trace_file.write_text(
        '{"ts":"2026-07-11T10:00:00+00:00","session_id":"sess_abc","run_id":"run_123","event":"agent_runtime_completed","output":{"status":"completed"}}\n',
        encoding="utf-8",
    )

    output = """Here is a checklist.

session: abc
turn: 1
run: run_123
status: completed
trace: /data/safeplane/traces/sess_abc/turn_001
"""

    result = score_case(
        eval_run_id="eval_test",
        case=EvalCase(
            case_id="non_calendar_text_only",
            prompt_template="Draft checklist.",
            expected_tool_name=None,
            expect_tool=False,
        ),
        prompt="Draft checklist.",
        output=output,
        safeplane_home=tmp_path,
    )

    assert result.passed is True
    assert result.observed_tool_names == []


def test_latest_event_id_by_title_fragment(tmp_path: Path) -> None:
    from harness.evals import latest_event_id_by_title_fragment

    events_log = tmp_path / "data/calendar/events.jsonl"
    events_log.parent.mkdir(parents=True)
    events_log.write_text(
        "\n".join(
            [
                '{"op":"calendar_event_created","event":{"id":"cal_evt_old","title":"Safeplane eval eval_old"}}',
                '{"op":"calendar_event_created","event":{"id":"cal_evt_new","title":"Safeplane eval eval_abc123"}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert latest_event_id_by_title_fragment(tmp_path, "eval_abc123") == "cal_evt_new"


def test_classify_error_rate_limit() -> None:
    output = "Model gateway HTTP error 500: RateLimitError code 429"
    assert classify_error("safeplane exited with code 1", output) == "provider_rate_limited"


def test_classify_error_provider_error() -> None:
    output = "Model gateway HTTP error 500: OpenRouterException"
    assert classify_error("safeplane exited with code 1", output) == "provider_error"


def test_provider_retry_sleep_seconds_uses_exponential_backoff() -> None:
    assert provider_retry_sleep_seconds(
        category="provider_error",
        output="",
        attempt_index=0,
        base_sleep_seconds=10.0,
        max_sleep_seconds=90.0,
    ) == 10.0

    assert provider_retry_sleep_seconds(
        category="provider_error",
        output="",
        attempt_index=2,
        base_sleep_seconds=10.0,
        max_sleep_seconds=90.0,
    ) == 40.0


def test_rate_limit_reset_sleep_seconds_without_header() -> None:
    assert rate_limit_reset_sleep_seconds(
        output="Rate limit exceeded",
        max_sleep_seconds=90.0,
    ) is None


def test_classify_error_success_has_no_category() -> None:
    assert classify_error(None, "Normal successful assistant output") is None


def test_summarize_eval_batch_counts_cases() -> None:
    from harness.evals import EvalResult, summarize_eval_batch

    results = [
        EvalResult(
            eval_run_id="eval_1",
            case_id="calendar_list_day",
            prompt="Show my calendar",
            passed=True,
            expected_tool_name="calendar_list",
            observed_tool_names=["calendar_list"],
            model_mode="real",
            configured_model="route",
            actual_model="model-a",
            actual_provider="provider-a",
            generation_id="gen-a",
            proposal_invalid_count=0,
            mcp_allowed=True,
            input_schema_valid=True,
            output_schema_valid=True,
            latency_ms=100,
            session_id="sess_1",
            run_id="run_1",
            trace_path="/tmp/trace",
            final_message="ok",
            error=None,
            error_category=None,
        ),
        EvalResult(
            eval_run_id="eval_2",
            case_id="calendar_list_day",
            prompt="Show my calendar",
            passed=False,
            expected_tool_name="calendar_list",
            observed_tool_names=[],
            model_mode=None,
            configured_model=None,
            actual_model=None,
            actual_provider=None,
            generation_id=None,
            proposal_invalid_count=0,
            mcp_allowed=False,
            input_schema_valid=None,
            output_schema_valid=None,
            latency_ms=None,
            session_id=None,
            run_id=None,
            trace_path=None,
            final_message=None,
            error="rate limited",
            error_category="provider_rate_limited",
        ),
    ]

    summary = summarize_eval_batch(
        batch_id="batch_test",
        suite="assistant-calendar-tools",
        harness_url="http://127.0.0.1:8787",
        run_summaries=[
            {"failed": 0},
            {"failed": 1},
        ],
        results=results,
        case_delay_seconds=8.0,
        between_run_delay_seconds=20.0,
        provider_retry_count=3,
        provider_retry_base_sleep_seconds=20.0,
        provider_retry_max_sleep_seconds=90.0,
    )

    assert summary["total_runs"] == 2
    assert summary["passed_runs"] == 1
    assert summary["total_cases"] == 2
    assert summary["passed_cases"] == 1
    assert summary["actual_models"] == ["model-a"]
    assert summary["actual_providers"] == ["provider-a"]
    assert summary["error_categories"] == {"provider_rate_limited": 1}
    assert summary["per_case"]["calendar_list_day"]["pass_rate"] == 0.5


def test_router_profile_summary_for_openrouter_free() -> None:
    from harness.evals import EvalResult, router_profile_summary

    results = [
        EvalResult(
            eval_run_id="eval_1",
            case_id="calendar_list_day",
            prompt="Show my calendar",
            passed=True,
            expected_tool_name="calendar_list",
            observed_tool_names=["calendar_list"],
            model_mode="real",
            configured_model="openrouter/openrouter/free",
            actual_model="model-a:free",
            actual_provider="provider-a",
            generation_id="gen-a",
            proposal_invalid_count=0,
            mcp_allowed=True,
            input_schema_valid=True,
            output_schema_valid=True,
            latency_ms=100,
            session_id="sess_1",
            run_id="run_1",
            trace_path="/tmp/trace",
            final_message="ok",
            error=None,
            error_category=None,
        ),
        EvalResult(
            eval_run_id="eval_2",
            case_id="calendar_create_explicit",
            prompt="Create event",
            passed=True,
            expected_tool_name="calendar_create",
            observed_tool_names=["calendar_create"],
            model_mode="real",
            configured_model="openrouter/openrouter/free",
            actual_model="model-b:free",
            actual_provider="provider-b",
            generation_id="gen-b",
            proposal_invalid_count=0,
            mcp_allowed=True,
            input_schema_valid=True,
            output_schema_valid=True,
            latency_ms=200,
            session_id="sess_2",
            run_id="run_2",
            trace_path="/tmp/trace",
            final_message="ok",
            error=None,
            error_category=None,
        ),
    ]

    summary = router_profile_summary(results)

    assert summary["is_router_route"] is True
    assert summary["configured_route"] == "openrouter/openrouter/free"
    assert summary["actual_model_count"] == 2
    assert summary["actual_provider_count"] == 2
    assert summary["note"] is not None


def test_event_id_from_eval_result_reads_trace_output(tmp_path: Path) -> None:
    from harness.evals import EvalResult, event_id_from_eval_result

    trace_path = tmp_path / "agent-runtime.trace.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "event": "tool_invocation_completed",
                "output": {
                    "structured_content": {
                        "event": {
                            "event_id": "cal_evt_12345678-1234-1234-1234-123456789abc"
                        }
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = EvalResult(
        eval_run_id="eval_test",
        case_id="calendar_create_explicit",
        prompt="Create event",
        passed=True,
        expected_tool_name="calendar_create",
        observed_tool_names=["calendar_create"],
        model_mode="real",
        configured_model="openrouter/openrouter/free",
        actual_model="model",
        actual_provider="provider",
        generation_id="gen",
        proposal_invalid_count=0,
        mcp_allowed=True,
        input_schema_valid=True,
        output_schema_valid=True,
        latency_ms=100,
        session_id="sess",
        run_id="run",
        trace_path=str(trace_path),
        final_message=None,
        error=None,
        error_category=None,
    )

    assert event_id_from_eval_result(result) == "cal_evt_12345678-1234-1234-1234-123456789abc"

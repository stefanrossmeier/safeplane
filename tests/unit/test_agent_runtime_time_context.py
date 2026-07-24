from datetime import UTC, datetime
import json

from harness.agent_runtime import (
    append_runtime_time_context,
    call_model_gateway,
    runtime_time_context_block,
)


def assistant_contract() -> dict:
    return {
        "runtime_context": {
            "timezone": "Europe/Berlin",
        }
    }


def test_runtime_time_context_uses_current_local_date() -> None:
    message = runtime_time_context_block(
        assistant_contract(),
        now_utc=datetime(2026, 7, 18, 8, 15, 30, tzinfo=UTC),
    )

    assert "Current local datetime: 2026-07-18T10:15:30+02:00" in message
    assert "Current local date: 2026-07-18" in message
    assert "Current local weekday: Saturday" in message
    assert "Timezone: Europe/Berlin" in message


def test_runtime_time_context_warns_against_copying_example_dates() -> None:
    message = runtime_time_context_block(
        assistant_contract(),
        now_utc=datetime(2026, 7, 18, 8, 15, 30, tzinfo=UTC),
    )

    assert "Resolve relative date/time phrases" in message
    assert "Never copy a date from an example" in message


def test_append_runtime_time_context_adds_context_to_system_prompt() -> None:
    message = append_runtime_time_context(
        "Base prompt",
        assistant_contract(),
        now_utc=datetime(2026, 7, 18, 8, 15, 30, tzinfo=UTC),
    )

    assert message.startswith("Base prompt\n\nRuntime time context:")
    assert "Current local date: 2026-07-18" in message


def test_model_gateway_call_forwards_profile_timeout(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"status":"completed"}'

    def fake_urlopen(request, timeout):
        observed["payload"] = json.loads(request.data.decode("utf-8"))
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = call_model_gateway(
        model_gateway_url="http://model-gateway.test/chat",
        session_id="sess_test",
        turn=1,
        workflow_id="developer",
        model_profile="developer_documentation",
        messages=[{"role": "user", "content": "document"}],
        stage_id="baseline_documentation",
        timeout_seconds=900,
    )

    assert result == {"status": "completed"}
    assert observed["timeout"] == 905
    assert observed["payload"]["timeout_seconds"] == 900

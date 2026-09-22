from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))
sys.path.insert(0, str(REPO_ROOT / "connectors/telegram/src"))

import telegram_connector.main as telegram_main  # noqa: E402
from harness.main import list_workflows  # noqa: E402
from telegram_connector.main import TelegramSessionStore, handle_update  # noqa: E402


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_message(self, _chat_id: int, text: str) -> None:
        self.sent.append(text)


class RegistryBackedHarness:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.runs: dict[str, dict] = {}

    def get_workflows(self, *, connector: str = "telegram") -> dict:
        return list_workflows(connector=connector, exposed_only=True)

    def post_workflow(
        self,
        *,
        entrypoint: str,
        message: str,
        session_ref: str | None = None,
        repository_profile: str | None = None,
        start_async: bool = False,
    ) -> dict:
        self.calls.append(
            {
                "entrypoint": entrypoint,
                "message": message,
                "session_ref": session_ref,
                "repository_profile": repository_profile,
                "start_async": start_async,
            }
        )
        run_id = f"run_accept_{len(self.calls)}"
        workflow_id = "developer" if entrypoint == "develop" else entrypoint
        session_id = f"sess_{workflow_id}"
        response = {
            "status": "queued" if start_async else "completed",
            "session_id": session_id,
            "session_display_id": workflow_id[:8],
            "turn": 1,
            "run_id": run_id,
            "final_message": None if start_async else f"[{workflow_id}] {message}",
            "trace_path": "/tmp/trace",
        }
        self.runs[run_id] = {
            "run_id": run_id,
            "status": "completed",
            "workflow_id": workflow_id,
            "turn": 1,
            "final_message": (
                "Developer workflow reached waiting_for_remote_approval."
                if entrypoint == "develop"
                else response["final_message"]
            ),
            "developer_pipeline": (
                {
                    "current_state": "waiting_for_remote_approval",
                    "completed_stages": [
                        "repositories",
                        "baseline_documentation",
                        "analysis",
                        "planning",
                        "implementation",
                        "checks",
                        "final_documentation",
                        "review",
                        "pr",
                        "remote_approval",
                    ],
                    "check_summary": {"status": "passed"},
                    "review_verdict": "LGTM",
                    "remote_approval_possible": True,
                }
                if entrypoint == "develop"
                else {}
            ),
        }
        return response

    def post_auto(
        self,
        *,
        message: str,
        repository_profile: str | None = None,
    ) -> dict:
        assert repository_profile is None
        response = self.post_workflow(
            entrypoint="assistant",
            message=message,
            start_async=False,
        )
        response["workflow_id"] = "assistant"
        response["entrypoint"] = "assistant"
        response["routing"] = {"semantic_route": "assistant", "accepted": True}
        return response

    def get_run(self, run_id: str) -> dict:
        return self.runs[run_id]

    def post_approve_pr(self, *, run_id: str) -> dict:
        raise AssertionError(f"unexpected approval: {run_id}")


def update(text: str, update_id: int) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "from": {"id": 123},
            "chat": {"id": 123},
            "text": text,
        },
    }


def test_registry_backed_telegram_commands_reach_every_exposed_workflow(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path / "runtime"))
    monkeypatch.setenv("SAFEPLANE_CONFIG", str(REPO_ROOT / "safeplane.yaml"))

    class ImmediateThread:
        def __init__(self, *, target, kwargs, **_options):
            self.target = target
            self.kwargs = kwargs

        def start(self) -> None:
            self.target(**self.kwargs)

    monkeypatch.setattr(telegram_main, "Thread", ImmediateThread)
    store = TelegramSessionStore(tmp_path / "telegram-sessions.json")
    harness = RegistryBackedHarness()
    telegram = FakeTelegram()

    commands = [
        "/workflows",
        "/help",
        "/run chat Explain the boundary",
        "/assistant Schedule a reminder tomorrow",
        "/run develop --repo fixture Change the greeting",
        "/run slow 1",
    ]
    for update_id, command in enumerate(commands, start=1):
        handle_update(
            update=update(command, update_id),
            allowed_user_ids={123},
            store=store,
            harness=harness,
            telegram=telegram,
        )

    assert [call["entrypoint"] for call in harness.calls] == [
        "chat",
        "assistant",
        "develop",
    ]
    assert harness.calls[2]["repository_profile"] == "fixture"
    assert harness.calls[2]["start_async"] is True
    assert any("/develop <repository-profile> <task>" in message for message in telegram.sent)
    assert any("/run develop --repo" in message for message in telegram.sent)
    assert any("Ready for PR approval" in message for message in telegram.sent)
    assert any("Unknown or unavailable workflow: slow" in message for message in telegram.sent)


def test_registry_backed_telegram_plain_text_uses_automatic_routing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path / "runtime"))
    monkeypatch.setenv("SAFEPLANE_CONFIG", str(REPO_ROOT / "safeplane.yaml"))
    store = TelegramSessionStore(tmp_path / "telegram-sessions.json")
    harness = RegistryBackedHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update("Remind me tomorrow at 09:00 to call the dentist", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert harness.calls[0]["entrypoint"] == "assistant"
    assert telegram.sent[-1].startswith("[assistant]")
    binding = store.automatic_binding(123)
    assert binding is not None
    assert binding["workflow_id"] == "assistant"

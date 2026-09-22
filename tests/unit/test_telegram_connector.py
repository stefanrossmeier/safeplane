from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "connectors/telegram/src"))

import telegram_connector.main as telegram_main  # noqa: E402
from telegram_connector.main import (  # noqa: E402
    TelegramSessionStore,
    handle_update,
)


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


class FakeHarness:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.runs: dict[str, dict] = {}

    def get_workflows(self, *, connector: str = "telegram") -> dict:
        assert connector == "telegram"
        def workflow(
            entrypoint: str,
            workflow_id: str,
            *,
            command: str,
            usage: str,
            run_usage: str,
            start_mode: str = "wait",
            session_continuation: bool = True,
            arguments: list[dict] | None = None,
        ) -> dict:
            return {
                "entrypoint": entrypoint,
                "workflow_id": workflow_id,
                "description": f"{workflow_id} workflow",
                "connectors": {
                    "telegram": {
                        "exposed": True,
                        "command": command,
                        "usage": usage,
                        "run_usage": run_usage,
                        "start_mode": start_mode,
                        "session_continuation": session_continuation,
                        "arguments": arguments
                        or [
                            {
                                "name": "message",
                                "required": True,
                                "consume_rest": True,
                            }
                        ],
                    }
                },
            }

        return {
            "connector": "telegram",
            "routing_mode": "automatic",
            "automatic_routing": True,
            "default_entrypoint": "assistant",
            "workflows": [
                workflow(
                    "assistant",
                    "assistant",
                    command="assistant",
                    usage="/assistant <message>",
                    run_usage="/run assistant <message>",
                ),
                workflow(
                    "chat",
                    "chat",
                    command="chat",
                    usage="/chat <message>",
                    run_usage="/run chat <message>",
                ),
                workflow(
                    "develop",
                    "developer",
                    command="develop",
                    usage="/develop <repository-profile> <task>",
                    run_usage="/run develop --repo <repository-profile> <task>",
                    start_mode="async",
                    session_continuation=False,
                    arguments=[
                        {
                            "name": "repository_profile",
                            "flag": "--repo",
                            "required": True,
                        },
                        {
                            "name": "message",
                            "required": True,
                            "consume_rest": True,
                        },
                    ],
                ),
            ],
        }

    def post_workflow(
        self,
        *,
        entrypoint: str,
        message: str,
        session_ref: str | None = None,
        repository_profile: str | None = None,
        start_async: bool = False,
    ) -> dict:
        if entrypoint == "assistant":
            assert start_async is False
            return self.post_assistant(message=message, session_ref=session_ref)
        if entrypoint == "chat":
            assert start_async is False
            self.calls.append(
                {
                    "chat_message": message,
                    "session_ref": session_ref,
                }
            )
            run_id = f"run_chat_{len(self.calls)}"
            response = {
                "status": "completed",
                "session_id": "sess_chat",
                "session_display_id": "chat1234",
                "turn": len(self.calls),
                "run_id": run_id,
                "final_message": f"[fake chat] {message}",
                "trace_path": "/tmp/chat-trace",
            }
            self.runs[run_id] = {
                "run_id": run_id,
                "status": "completed",
                "session_display_id": "chat1234",
                "workflow_id": "chat",
                "entrypoint": "chat",
                "turn": len(self.calls),
                "trace_path": "/tmp/chat-trace",
            }
            return response
        if entrypoint == "develop":
            assert start_async is True
            assert repository_profile is not None
            return self.post_develop_start(
                message=message,
                repository_profile=repository_profile,
            )
        raise AssertionError(f"Unexpected entrypoint: {entrypoint}")

    def post_auto(
        self,
        *,
        message: str,
        repository_profile: str | None = None,
    ) -> dict:
        assert repository_profile is None
        self.calls.append({"auto_message": message})
        run_id = f"run_auto_{len(self.calls)}"
        response = {
            "status": "completed",
            "session_id": "sess_auto_assistant",
            "session_display_id": "auto1234",
            "turn": 1,
            "run_id": run_id,
            "workflow_id": "assistant",
            "entrypoint": "assistant",
            "final_message": f"[fake assistant] {message}",
            "trace_path": "/tmp/auto-trace",
            "routing": {"semantic_route": "assistant", "accepted": True},
        }
        self.runs[run_id] = {
            "run_id": run_id,
            "status": "completed",
            "session_display_id": "auto1234",
            "workflow_id": "assistant",
            "entrypoint": "assistant",
            "turn": 1,
            "trace_path": "/tmp/auto-trace",
        }
        return response

    def post_assistant(self, *, message: str, session_ref: str | None) -> dict:
        self.calls.append(
            {
                "message": message,
                "session_ref": session_ref,
            }
        )

        run_id = f"run_{len(self.calls)}"

        response = {
            "status": "completed",
            "session_id": "sess_abc",
            "session_display_id": "abc12345",
            "turn": len(self.calls),
            "run_id": run_id,
            "final_message": f"[fake assistant] {message}",
            "trace_path": "/tmp/trace",
        }

        self.runs[run_id] = {
            "run_id": run_id,
            "status": "completed",
            "session_display_id": "abc12345",
            "workflow_id": "assistant",
            "entrypoint": "assistant",
            "turn": len(self.calls),
            "trace_path": "/tmp/trace",
        }

        return response

    def post_develop_start(self, *, message: str, repository_profile: str) -> dict:
        self.calls.append(
            {
                "develop_message": message,
                "repository_profile": repository_profile,
            }
        )
        run_id = f"run_dev_{len(self.calls)}"
        response = {
            "status": "queued",
            "session_id": "sess_dev",
            "session_display_id": "dev12345",
            "turn": 1,
            "run_id": run_id,
            "final_message": None,
            "trace_path": "/tmp/dev-trace",
        }
        self.runs[run_id] = {
            "run_id": run_id,
            "status": "completed",
            "session_display_id": "dev12345",
            "workflow_id": "developer",
            "entrypoint": "develop",
            "turn": 1,
            "final_message": "Developer pipeline is waiting_for_remote_approval.",
            "developer_pipeline": {
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
            },
        }
        return response

    def post_approve_pr(self, *, run_id: str) -> dict:
        self.calls.append({"approve_pr_run_id": run_id})
        result = {
            "approval_id": "remote_approval_fixture",
            "run_id": run_id,
            "status": "completed",
            "branch_name": "safeplane/fixture",
            "commit_sha": "a" * 40,
            "pull_request_number": 7,
            "pull_request_url": "https://github.example/fixture/target/pull/7",
            "draft": True,
            "branch_reused": False,
            "pull_request_reused": False,
            "approval_ref": "workspaces/run/remote-approval.json",
            "evidence_ref": "workspaces/run/remote-evidence.json",
        }
        run = self.runs.get(run_id)
        if run:
            run["developer_pipeline"]["current_state"] = "completed"
            run["developer_pipeline"]["remote_approval_possible"] = False
            run["developer_pipeline"]["remote_write"] = result
            run["remote_write"] = result
        return result

    def get_run(self, run_id: str) -> dict:
        return self.runs[run_id]


def update(chat_id: int, text: str, update_id: int = 1, from_user_id: int | None = None) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "from": {
                "id": from_user_id if from_user_id is not None else chat_id,
            },
            "chat": {
                "id": chat_id,
            },
            "text": text,
        },
    }


def test_telegram_connector_rejects_unknown_chat(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))

    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "hello"),
        allowed_user_ids={999},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert harness.calls == []
    assert telegram.sent == [
        (123, "This Telegram user is not authorized for this Safeplane bot.")
    ]


def test_telegram_connector_creates_and_continues_assistant_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))

    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "Say hello", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    handle_update(
        update=update(123, "What did I just ask?", 2),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert harness.calls[0] == {"auto_message": "Say hello"}

    assert harness.calls[1] == {
        "message": "What did I just ask?",
        "session_ref": "sess_auto_assistant",
    }

    mapping = store.get(123)
    assert mapping is not None
    assert mapping["session_id"] == "sess_abc"
    assert mapping["session_display_id"] == "abc12345"
    assert mapping["workflow_id"] == "assistant"
    assert mapping["latest_run_id"] == "run_2"

    assert telegram.sent == [
        (123, "[fake assistant] Say hello"),
        (123, "[fake assistant] What did I just ask?"),
    ]


def test_telegram_new_command_clears_session_mapping(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))

    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "Say hello", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert store.get(123) is not None

    handle_update(
        update=update(123, "/new", 2),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert store.get(123) is None
    assert telegram.sent[-1] == (
        123,
        "Cleared Telegram workflow sessions. The next command starts a fresh session.",
    )


def test_telegram_status_command_reports_latest_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))

    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "Say hello", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    handle_update(
        update=update(123, "/status", 2),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert "Latest Safeplane run:" in telegram.sent[-1][1]
    assert "run: run_auto_1" in telegram.sent[-1][1]
    assert "status: completed" in telegram.sent[-1][1]


def test_telegram_authorization_uses_from_user_id_not_chat_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))

    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(chat_id=-100123, from_user_id=42, text="Say hello", update_id=1),
        allowed_user_ids={42},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert harness.calls == [{"auto_message": "Say hello"}]
    assert telegram.sent == [
        (-100123, "[fake assistant] Say hello"),
    ]


def test_telegram_develop_command_starts_fixed_workflow_and_reports_progress(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))

    class ImmediateThread:
        def __init__(self, *, target, kwargs, **_options):
            self.target = target
            self.kwargs = kwargs

        def start(self) -> None:
            self.target(**self.kwargs)

    monkeypatch.setattr(telegram_main, "Thread", ImmediateThread)
    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "/develop example-target Adjust the greeting", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert harness.calls == [
        {
            "develop_message": "Adjust the greeting",
            "repository_profile": "example-target",
        }
    ]
    messages = [text for chat_id, text in telegram.sent if chat_id == 123]
    assert messages[0].startswith("Developer run started")
    assert any(item.startswith("Repositories prepared") for item in messages)
    assert any(item.startswith("Implementation applied") for item in messages)
    assert any(item.startswith("Checks passed") for item in messages)
    assert any(item.startswith("Ready for PR approval") for item in messages)
    assert messages[-1] == "Developer pipeline is waiting_for_remote_approval."
    mapping = store.get(123)
    assert mapping is not None
    assert mapping["latest_run_id"].startswith("run_dev_")
    assert mapping["latest_workflow_id"] == "developer"


def test_telegram_develop_command_requires_profile_and_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "/develop example-target", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert harness.calls == []
    assert telegram.sent[-1] == (123, "Usage: /develop <repository-profile> <task>")


def test_telegram_approve_pr_uses_latest_developer_run_and_returns_url(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()
    response = harness.post_develop_start(
        message="Adjust the greeting",
        repository_profile="example-target",
    )
    store.record_developer_run(123, response)
    harness.calls.clear()

    handle_update(
        update=update(123, "/approve_pr", 2),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert harness.calls == [{"approve_pr_run_id": response["run_id"]}]
    message = telegram.sent[-1][1]
    assert message.startswith("Draft pull request created")
    assert "branch: safeplane/fixture" in message
    assert "PR: https://github.example/fixture/target/pull/7" in message
    assert "did not merge" in message


def test_telegram_approve_pr_requires_run_when_no_mapping(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "/approve_pr", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert harness.calls == []
    assert "Usage: /approve_pr" in telegram.sent[-1][1]


def test_telegram_workflows_lists_only_registry_exposed_commands(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "/workflows", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    message = telegram.sent[-1][1]
    assert "/chat <message>" in message
    assert "/assistant <message>" in message
    assert "/develop <repository-profile> <task>" in message
    assert "/run develop --repo <repository-profile> <task>" not in message
    assert "Send /help for every Telegram command." in message
    assert "/slow" not in message
    assert "routed automatically" in message


def test_telegram_help_lists_all_workflow_and_control_commands(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "/help", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    message = telegram.sent[-1][1]
    for expected in [
        "/chat <message>",
        "/assistant <message>",
        "/develop <repository-profile> <task>",
        "/workflows",
        "/status [run-id]",
        "/approve_pr [run-id]",
        "/new",
        "/help",
        "/start",
        "/run <entrypoint> <arguments>",
        "/run develop --repo <repository-profile> <task>",
    ]:
        assert expected in message
    assert "Advanced generic form:" in message
    assert "/slow" not in message

    events = [
        telegram_main.json.loads(line)
        for line in (tmp_path / "connectors/telegram/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(row["event"] == "command_received" for row in events)
    assert any(row["event"] == "help_sent" for row in events)


def test_telegram_run_and_direct_alias_keep_workflow_sessions_separate(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    for index, text in enumerate(
        [
            "/run chat First chat message",
            "/assistant First assistant message",
            "/chat Second chat message",
            "/run assistant Second assistant message",
        ],
        start=1,
    ):
        handle_update(
            update=update(123, text, index),
            allowed_user_ids={123},
            store=store,
            harness=harness,
            telegram=telegram,
        )

    assert harness.calls == [
        {"chat_message": "First chat message", "session_ref": None},
        {"message": "First assistant message", "session_ref": None},
        {"chat_message": "Second chat message", "session_ref": "sess_chat"},
        {"message": "Second assistant message", "session_ref": "sess_abc"},
    ]
    mapping = store.get(123)
    assert mapping is not None
    assert mapping["workflow_sessions"]["chat"]["session_id"] == "sess_chat"
    assert mapping["workflow_sessions"]["assistant"]["session_id"] == "sess_abc"


def test_telegram_generic_run_develop_requires_repo_flag_and_starts_pipeline(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))

    class ImmediateThread:
        def __init__(self, *, target, kwargs, **_options):
            self.target = target
            self.kwargs = kwargs

        def start(self) -> None:
            self.target(**self.kwargs)

    monkeypatch.setattr(telegram_main, "Thread", ImmediateThread)
    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "/run develop --repo fixture Adjust the greeting", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert harness.calls == [
        {
            "develop_message": "Adjust the greeting",
            "repository_profile": "fixture",
        }
    ]
    assert telegram.sent[0][1].startswith("Developer run started")
    assert "repository: fixture" in telegram.sent[0][1]
    events = [
        telegram_main.json.loads(line)
        for line in (tmp_path / "connectors/telegram/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    started = [row for row in events if row["event"] == "workflow_started"]
    assert started[-1]["payload"]["entrypoint"] == "develop"
    assert started[-1]["payload"]["repository_profile"] == "fixture"


def test_telegram_generic_run_rejects_missing_flag_unknown_and_hidden_workflows(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    for index, text in enumerate(
        [
            "/run develop fixture task",
            "/run slow 1",
            "/run missing hello",
        ],
        start=1,
    ):
        handle_update(
            update=update(123, text, index),
            allowed_user_ids={123},
            store=store,
            harness=harness,
            telegram=telegram,
        )

    assert harness.calls == []
    assert telegram.sent[0] == (
        123,
        "Usage: /run develop --repo <repository-profile> <task>",
    )
    assert "Unknown or unavailable workflow: slow" in telegram.sent[1][1]
    assert "Unknown or unavailable workflow: missing" in telegram.sent[2][1]


def test_telegram_plain_text_routes_automatically_then_pins_the_session(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    store = TelegramSessionStore(tmp_path / "sessions.json")
    harness = FakeHarness()
    telegram = FakeTelegram()

    handle_update(
        update=update(123, "Remind me tomorrow to call the dentist", 1),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )
    handle_update(
        update=update(123, "Make that 10 AM instead", 2),
        allowed_user_ids={123},
        store=store,
        harness=harness,
        telegram=telegram,
    )

    assert harness.calls == [
        {"auto_message": "Remind me tomorrow to call the dentist"},
        {"message": "Make that 10 AM instead", "session_ref": "sess_auto_assistant"},
    ]
    assert telegram.sent == [
        (123, "[fake assistant] Remind me tomorrow to call the dentist"),
        (123, "[fake assistant] Make that 10 AM instead"),
    ]
    binding = store.automatic_binding(123)
    assert binding is not None
    assert binding["entrypoint"] == "assistant"


def test_long_polling_records_readiness_and_replies_when_command_processing_fails(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_DELETE_WEBHOOK_ON_START", "true")
    monkeypatch.setattr(telegram_main, "telegram_bot_token", lambda: "test-token")
    monkeypatch.setattr(telegram_main, "telegram_allowed_user_ids", lambda: {123})
    monkeypatch.setattr(
        telegram_main,
        "start_outbound_notification_server",
        lambda _telegram, _allowed: None,
    )

    class PollingTelegram:
        def __init__(self) -> None:
            self.get_updates_calls = 0
            self.sent: list[tuple[int, str]] = []
            self.webhook_deleted = False

        def get_me(self) -> dict:
            return {"id": 77, "username": "safeplane_test_bot"}

        def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
            assert drop_pending_updates is False
            self.webhook_deleted = True

        def get_updates(self, *, offset, timeout_seconds):
            assert timeout_seconds == 30
            self.get_updates_calls += 1
            if self.get_updates_calls == 1:
                return [update(123, "/help", 1)]
            raise SystemExit("stop polling test")

        def send_message(self, chat_id: int, text: str) -> None:
            self.sent.append((chat_id, text))

    class FailingHarness:
        def get_workflows(self, *, connector: str = "telegram") -> dict:
            raise RuntimeError("registry unavailable")

    telegram = PollingTelegram()
    monkeypatch.setattr(telegram_main, "TelegramApi", lambda _token: telegram)
    monkeypatch.setattr(telegram_main, "HarnessClient", lambda _url: FailingHarness())

    with pytest.raises(SystemExit, match="stop polling test"):
        telegram_main.run_long_polling()

    assert telegram.webhook_deleted is True
    assert telegram.sent[0] == (
        123,
        "Safeplane workflow registry is unavailable: registry unavailable",
    )
    assert telegram.sent[1] == (
        123,
        "Safeplane could not process this command: registry unavailable",
    )

    events = [
        telegram_main.json.loads(line)
        for line in (tmp_path / "connectors/telegram/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(row["event"] == "bot_authenticated" for row in events)
    assert any(row["event"] == "polling_ready" for row in events)
    failed = [row for row in events if row["event"] == "update_handling_failed"]
    assert failed[-1]["payload"]["command"] == "/help"
    assert failed[-1]["error"]["message"] == "registry unavailable"

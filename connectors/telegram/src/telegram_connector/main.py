from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safeplane_home() -> Path:
    return Path(os.environ.get("SAFEPLANE_HOME", "/data/safeplane")).expanduser()


def connector_dir() -> Path:
    path = safeplane_home() / "connectors" / "telegram"
    path.mkdir(parents=True, exist_ok=True)
    return path


def events_path() -> Path:
    return connector_dir() / "events.jsonl"


def write_event(event: str, payload: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
    record = {
        "ts": utc_now(),
        "connector": "telegram",
        "event": event,
        "payload": payload or {},
        "error": error,
    }

    with events_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_secret_file(path: str) -> str:
    secret_path = Path(path)

    if not secret_path.exists():
        raise FileNotFoundError(f"Telegram bot token secret not found: {secret_path}")

    token = secret_path.read_text(encoding="utf-8").strip()

    if not token:
        raise ValueError(f"Telegram bot token secret is empty: {secret_path}")

    return token


def telegram_bot_token() -> str:
    token_file = os.environ.get("TELEGRAM_BOT_TOKEN_FILE", "/run/secrets/telegram_bot_token")

    if Path(token_file).exists():
        return read_secret_file(token_file)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return token

    raise FileNotFoundError(
        f"Telegram bot token not found. Expected secret file at {token_file}."
    )


def parse_id_list(raw: str | None) -> set[int]:
    if not raw:
        return set()

    allowed: set[int] = set()

    for part in raw.replace("\n", ",").split(","):
        value = part.strip()
        if not value:
            continue
        allowed.add(int(value))

    return allowed


def telegram_allowed_user_ids() -> set[int]:
    allowed_file = os.environ.get(
        "TELEGRAM_ALLOWED_USER_IDS_FILE",
        "/run/secrets/telegram_allowed_user_ids",
    )

    if Path(allowed_file).exists():
        return parse_id_list(Path(allowed_file).read_text(encoding="utf-8"))

    raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS")
    if raw:
        return parse_id_list(raw)

    return set()


def command_name(text: str) -> str:
    first = text.strip().split()[0]
    return first.split("@")[0].lower()


class TelegramApi:
    def __init__(self, token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None

        if params is not None:
            data = urllib.parse.urlencode(params).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}/{method}",
            data=data,
            method="POST" if data is not None else "GET",
        )

        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))

        if not body.get("ok"):
            raise RuntimeError(f"Telegram API error for {method}: {body}")

        return body

    def get_me(self) -> dict[str, Any]:
        return dict(self.request("getMe").get("result") or {})

    def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        self.request(
            "deleteWebhook",
            {
                "drop_pending_updates": "true" if drop_pending_updates else "false",
            },
        )

    def get_updates(self, *, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeout": timeout_seconds,
            "allowed_updates": json.dumps(["message"]),
        }

        if offset is not None:
            params["offset"] = offset

        body = self.request("getUpdates", params)
        return list(body.get("result", []))

    def send_message(self, chat_id: int, text: str) -> None:
        self.request(
            "sendMessage",
            {
                "chat_id": str(chat_id),
                "text": text,
            },
        )


class HarnessClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _request_json(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Harness HTTP error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Harness connection error: {exc}") from exc

    def get_workflows(self, *, connector: str = "telegram") -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {
                "connector": connector,
                "exposed_only": "true",
            }
        )
        return self._request_json(f"/workflows?{query}", timeout=10)

    def post_workflow(
        self,
        *,
        entrypoint: str,
        message: str,
        session_ref: str | None = None,
        repository_profile: str | None = None,
        start_async: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "connector": "telegram",
            "message": message,
        }
        if session_ref:
            payload["session_ref"] = session_ref
        if repository_profile:
            payload["repository_profile"] = repository_profile
        suffix = "/start" if start_async else ""
        timeout = 30 if start_async else 600
        return self._request_json(
            f"/connector/{urllib.parse.quote(entrypoint, safe='')}{suffix}",
            payload=payload,
            timeout=timeout,
        )

    def post_assistant(self, *, message: str, session_ref: str | None) -> dict[str, Any]:
        return self.post_workflow(
            entrypoint="assistant",
            message=message,
            session_ref=session_ref,
        )

    def post_develop_start(self, *, message: str, repository_profile: str) -> dict[str, Any]:
        return self.post_workflow(
            entrypoint="develop",
            message=message,
            repository_profile=repository_profile,
            start_async=True,
        )

    def post_approve_pr(self, *, run_id: str) -> dict[str, Any]:
        return self._request_json(
            f"/runs/{urllib.parse.quote(run_id, safe='')}/remote/approve",
            payload={"approved": True, "connector": "telegram"},
            timeout=180,
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request_json(
            f"/runs/{urllib.parse.quote(run_id, safe='')}",
            timeout=10,
        )


class TelegramSessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or connector_dir() / "sessions.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def key(self, chat_id: int) -> str:
        return f"telegram_chat_id:{chat_id}"

    def get(self, chat_id: int) -> dict[str, Any] | None:
        return self.load().get(self.key(chat_id))

    def session_ref(self, chat_id: int, workflow_id: str) -> str | None:
        mapping = self.get(chat_id) or {}
        workflow = (mapping.get("workflow_sessions") or {}).get(workflow_id) or {}
        if workflow.get("session_id"):
            return str(workflow["session_id"])
        if workflow_id == "assistant" and mapping.get("session_id"):
            return str(mapping["session_id"])
        return None

    def record_workflow_run(
        self,
        chat_id: int,
        *,
        entrypoint: str,
        workflow_id: str,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        data = self.load()
        key = self.key(chat_id)
        now = utc_now()
        existing = data.get(key, {})
        workflow_sessions = dict(existing.get("workflow_sessions") or {})
        workflow_sessions[workflow_id] = {
            "entrypoint": entrypoint,
            "workflow_id": workflow_id,
            "session_id": response["session_id"],
            "session_display_id": response["session_display_id"],
            "latest_run_id": response["run_id"],
            "updated_at": now,
        }
        mapping = {
            **existing,
            "workflow_sessions": workflow_sessions,
            "latest_run_id": response["run_id"],
            "latest_workflow_id": workflow_id,
            "latest_entrypoint": entrypoint,
            "created_at": existing.get("created_at", now),
            "updated_at": now,
        }
        if workflow_id == "assistant":
            mapping.update(
                {
                    "session_id": response["session_id"],
                    "session_display_id": response["session_display_id"],
                    "workflow_id": "assistant",
                }
            )
        if workflow_id == "developer":
            mapping.update(
                {
                    "developer_session_id": response["session_id"],
                    "developer_session_display_id": response["session_display_id"],
                }
            )
        data[key] = mapping
        self.save(data)
        return mapping

    def upsert_from_harness_response(self, chat_id: int, response: dict[str, Any]) -> dict[str, Any]:
        return self.record_workflow_run(
            chat_id,
            entrypoint="assistant",
            workflow_id="assistant",
            response=response,
        )

    def record_developer_run(self, chat_id: int, response: dict[str, Any]) -> dict[str, Any]:
        return self.record_workflow_run(
            chat_id,
            entrypoint="develop",
            workflow_id="developer",
            response=response,
        )

    def clear(self, chat_id: int, workflow_id: str | None = None) -> None:
        data = self.load()
        key = self.key(chat_id)
        if workflow_id is None:
            data.pop(key, None)
        else:
            mapping = data.get(key)
            if mapping is not None:
                workflow_sessions = dict(mapping.get("workflow_sessions") or {})
                workflow_sessions.pop(workflow_id, None)
                mapping["workflow_sessions"] = workflow_sessions
                if workflow_id == "assistant":
                    for field in ("session_id", "session_display_id", "workflow_id"):
                        mapping.pop(field, None)
                mapping["updated_at"] = utc_now()
                data[key] = mapping
        self.save(data)


def telegram_workflow_metadata(workflow: dict[str, Any]) -> dict[str, Any]:
    return dict((workflow.get("connectors") or {}).get("telegram") or {})


def format_workflows(payload: dict[str, Any]) -> str:
    workflows = list(payload.get("workflows") or [])
    lines = ["Safeplane workflows available in Telegram:", ""]
    for workflow in workflows:
        metadata = telegram_workflow_metadata(workflow)
        usage = str(metadata.get("usage") or "").strip()
        lines.append(f"{usage} — {workflow.get('description')}")
    lines.extend(
        [
            "",
            "Send /help for every Telegram command.",
        ]
    )
    default_entrypoint = payload.get("default_entrypoint")
    if default_entrypoint:
        lines.extend(
            [
                "",
                f"Plain text uses the configured default workflow: {default_entrypoint}.",
            ]
        )
    return "\n".join(lines)


def format_help(payload: dict[str, Any]) -> str:
    workflows = list(payload.get("workflows") or [])
    lines = [
        "Safeplane Telegram commands",
        "",
        "Start a workflow:",
    ]
    for workflow in workflows:
        metadata = telegram_workflow_metadata(workflow)
        usage = str(metadata.get("usage") or "").strip()
        lines.append(f"{usage} — {workflow.get('description')}")
    lines.extend(
        [
            "",
            "Inspect and control runs:",
            "/workflows — list workflows exposed to Telegram",
            "/status [run-id] — show the latest or named run",
            "/approve_pr [run-id] — create or reuse an allowed draft PR",
            "/new — clear saved Telegram workflow sessions",
            "/help — show this command reference",
            "/start — show this command reference",
            "",
            "Advanced generic form:",
            "/run <entrypoint> <arguments> — dispatch an exposed workflow by name",
        ]
    )
    for workflow in workflows:
        metadata = telegram_workflow_metadata(workflow)
        run_usage = str(metadata.get("run_usage") or "").strip()
        usage = str(metadata.get("usage") or "").strip()
        if run_usage and run_usage != usage:
            lines.append(f"  {run_usage}")
    default_entrypoint = payload.get("default_entrypoint")
    if default_entrypoint:
        lines.extend(
            [
                "",
                f"Plain text is shorthand for the default workflow: {default_entrypoint}.",
            ]
        )
    return "\n".join(lines)


def workflow_by_entrypoint(payload: dict[str, Any], entrypoint: str) -> dict[str, Any] | None:
    for workflow in payload.get("workflows") or []:
        if workflow.get("entrypoint") == entrypoint:
            return workflow
    return None


def workflow_by_command(payload: dict[str, Any], command: str) -> dict[str, Any] | None:
    normalized = command.removeprefix("/").lower()
    for workflow in payload.get("workflows") or []:
        metadata = telegram_workflow_metadata(workflow)
        if str(metadata.get("command") or "").lower() == normalized:
            return workflow
    return None


def parse_workflow_arguments(
    argument_text: str,
    metadata: dict[str, Any],
    *,
    generic_run: bool,
) -> dict[str, str]:
    remaining = argument_text.strip()
    parsed: dict[str, str] = {}
    for argument in metadata.get("arguments") or []:
        name = str(argument["name"])
        required = bool(argument.get("required", False))
        consume_rest = bool(argument.get("consume_rest", False))
        flag = str(argument.get("flag") or "").strip()

        if flag and generic_run:
            parts = remaining.split(maxsplit=1)
            if not parts or parts[0] != flag:
                if required:
                    raise ValueError(f"missing required flag {flag}")
                continue
            remaining = parts[1].strip() if len(parts) == 2 else ""

        if consume_rest:
            value = remaining.strip()
            remaining = ""
        else:
            parts = remaining.split(maxsplit=1)
            value = parts[0] if parts else ""
            remaining = parts[1].strip() if len(parts) == 2 else ""

        if required and not value:
            raise ValueError(f"missing required argument {name}")
        if value:
            parsed[name] = value

    if remaining:
        raise ValueError("unexpected extra arguments")
    return parsed


def dispatch_workflow(
    *,
    chat_id: int,
    workflow: dict[str, Any],
    argument_text: str,
    generic_run: bool,
    store: TelegramSessionStore,
    harness: HarnessClient,
    telegram: TelegramApi,
) -> None:
    metadata = telegram_workflow_metadata(workflow)
    usage = str(metadata.get("run_usage") if generic_run else metadata.get("usage") or "")
    try:
        arguments = parse_workflow_arguments(
            argument_text,
            metadata,
            generic_run=generic_run,
        )
    except ValueError:
        telegram.send_message(chat_id, f"Usage: {usage}")
        return

    entrypoint = str(workflow["entrypoint"])
    workflow_id = str(workflow["workflow_id"])
    session_ref = None
    if metadata.get("session_continuation"):
        session_ref = store.session_ref(chat_id, workflow_id)
    start_async = metadata.get("start_mode") == "async"
    response = harness.post_workflow(
        entrypoint=entrypoint,
        message=arguments.get("message", ""),
        session_ref=session_ref,
        repository_profile=arguments.get("repository_profile"),
        start_async=start_async,
    )
    store.record_workflow_run(
        chat_id,
        entrypoint=entrypoint,
        workflow_id=workflow_id,
        response=response,
    )
    run_id = str(response["run_id"])
    write_event(
        "workflow_started",
        {
            "telegram_chat_id": chat_id,
            "entrypoint": entrypoint,
            "workflow_id": workflow_id,
            "run_id": run_id,
            "repository_profile": arguments.get("repository_profile"),
            "start_mode": metadata.get("start_mode"),
        },
    )

    if start_async:
        repository_profile = arguments.get("repository_profile")
        detail = f"\nrepository: {repository_profile}" if repository_profile else ""
        telegram.send_message(
            chat_id,
            f"{workflow_id.title()} run started{detail}\nrun: {run_id}",
        )
        if entrypoint == "develop":
            Thread(
                target=finish_developer_progress_reporting,
                kwargs={
                    "chat_id": chat_id,
                    "run_id": run_id,
                    "harness": harness,
                    "telegram": telegram,
                },
                daemon=True,
                name=f"safeplane-developer-progress-{run_id}",
            ).start()
        return

    final_message = response.get("final_message") or "(Safeplane returned no final message.)"
    telegram.send_message(chat_id, final_message)
    write_event(
        "message_completed",
        {
            "telegram_chat_id": chat_id,
            "entrypoint": entrypoint,
            "workflow_id": workflow_id,
            "session_id": response.get("session_id"),
            "session_display_id": response.get("session_display_id"),
            "run_id": response.get("run_id"),
            "status": response.get("status"),
        },
    )


def format_status(mapping: dict[str, Any] | None, harness: HarnessClient) -> str:
    if not mapping:
        return "No Safeplane session is currently mapped to this Telegram chat."

    latest_run_id = mapping.get("latest_run_id")
    if not latest_run_id:
        return (
            "Safeplane session is mapped, but no run is known yet.\n\n"
            f"session: {mapping.get('session_display_id')}"
        )

    run = harness.get_run(latest_run_id)

    latest_workflow = mapping.get("latest_workflow_id") or mapping.get("workflow_id")
    workflow_session = (mapping.get("workflow_sessions") or {}).get(latest_workflow) or {}
    session_display = (
        workflow_session.get("session_display_id")
        or (
            mapping.get("developer_session_display_id")
            if latest_workflow == "developer"
            else mapping.get("session_display_id")
        )
    )
    lines = [
        "Latest Safeplane run:",
        "",
    ]
    if session_display:
        lines.append(f"session: {session_display}")
    lines.extend([
        f"run: {run['run_id']}",
        f"status: {run['status']}",
        f"workflow: {run['workflow_id']}",
        f"turn: {run['turn']}",
    ])

    pipeline = run.get("developer_pipeline") or {}
    if pipeline:
        lines.extend(["", f"pipeline: {pipeline.get('current_state')}"])
        check_summary = pipeline.get("check_summary") or {}
        if check_summary:
            lines.append(f"checks: {check_summary.get('status')}")
        if pipeline.get("review_verdict"):
            lines.append(f"review: {pipeline.get('review_verdict')}")
        lines.append(
            "remote approval: "
            + ("available" if pipeline.get("remote_approval_possible") else "not available")
        )
        binding = pipeline.get("remote_approval_binding") or {}
        if binding:
            lines.append(f"planned branch: {binding.get('branch_name')}")
        remote_write = pipeline.get("remote_write") or run.get("remote_write") or {}
        if remote_write:
            lines.append(f"remote branch: {remote_write.get('branch_name')}")
            lines.append(f"draft PR: {remote_write.get('pull_request_url')}")

    if run.get("error"):
        lines.append("")
        lines.append(f"error: {run['error'].get('message')}")

    return "\n".join(lines)


DEVELOPER_STAGE_PROGRESS_MESSAGES = {
    "repositories": "Repositories prepared",
    "baseline_documentation": "Documentation prepared",
    "analysis": "Requirements ready",
    "planning": "Plan ready",
    "implementation": "Implementation applied",
    "checks": "Checks passed",
    "final_documentation": "Documentation reconciled",
    "review": "Review passed",
    "remote_approval": "Ready for PR approval",
}


def report_developer_progress(
    *,
    chat_id: int,
    run_id: str,
    harness: HarnessClient,
    telegram: TelegramApi,
    timeout_seconds: int = 900,
    poll_seconds: float = 0.2,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    reported_stages: set[str] = set()
    while time.monotonic() < deadline:
        run = harness.get_run(run_id)
        pipeline = run.get("developer_pipeline") or {}
        completed_stages = [str(item) for item in pipeline.get("completed_stages") or []]
        current_state = str(pipeline.get("current_state") or "")
        for stage_id in completed_stages:
            if stage_id in reported_stages:
                continue
            message = DEVELOPER_STAGE_PROGRESS_MESSAGES.get(stage_id)
            if stage_id == "review" and current_state == "review_changes_requested":
                message = "Review requested changes"
            if stage_id == "remote_approval" and not pipeline.get(
                "remote_approval_possible"
            ):
                message = "PR proposal ready; remote approval unavailable"
            if message:
                telegram.send_message(chat_id, f"{message}\nrun: {run_id}")
            reported_stages.add(stage_id)
        if run.get("status") in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(poll_seconds)
    raise TimeoutError(f"Developer run did not finish within {timeout_seconds} seconds: {run_id}")


def finish_developer_progress_reporting(
    *,
    chat_id: int,
    run_id: str,
    harness: HarnessClient,
    telegram: TelegramApi,
) -> None:
    try:
        run = report_developer_progress(
            chat_id=chat_id,
            run_id=run_id,
            harness=harness,
            telegram=telegram,
        )
        if run.get("status") == "completed":
            telegram.send_message(
                chat_id,
                run.get("final_message") or f"Developer run completed: {run_id}",
            )
        else:
            error = (run.get("error") or {}).get("message") or run.get("status")
            telegram.send_message(chat_id, f"Developer run stopped: {error}\nrun: {run_id}")
    except Exception as exc:
        write_event(
            "developer_progress_failed",
            {"telegram_chat_id": chat_id, "run_id": run_id},
            {"type": type(exc).__name__, "message": str(exc)},
        )
        telegram.send_message(
            chat_id,
            f"Developer progress reporting failed: {exc}\nrun: {run_id}",
        )


def handle_update(
    *,
    update: dict[str, Any],
    allowed_user_ids: set[int],
    store: TelegramSessionStore,
    harness: HarnessClient,
    telegram: TelegramApi,
) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    from_user = message.get("from") or {}

    chat_id = chat.get("id")
    from_user_id = from_user.get("id")
    text = message.get("text")

    if chat_id is None or text is None:
        write_event("update_ignored", {"reason": "missing chat id or text", "update": update})
        return

    chat_id = int(chat_id)
    from_user_id = int(from_user_id) if from_user_id is not None else None

    write_event(
        "message_received",
        {
            "telegram_update_id": update.get("update_id"),
            "telegram_chat_id": chat_id,
            "telegram_from_user_id": from_user_id,
            "text_length": len(text),
        },
    )

    if from_user_id is None or from_user_id not in allowed_user_ids:
        write_event(
            "message_rejected",
            {
                "telegram_chat_id": chat_id,
                "telegram_from_user_id": from_user_id,
                "reason": "user id not allowed",
            },
        )
        telegram.send_message(chat_id, "This Telegram user is not authorized for this Safeplane bot.")
        return

    stripped = text.strip()

    def exposed_workflows() -> dict[str, Any]:
        try:
            return harness.get_workflows(connector="telegram")
        except Exception as exc:
            telegram.send_message(chat_id, f"Safeplane workflow registry is unavailable: {exc}")
            raise

    if stripped.startswith("/"):
        command = command_name(stripped)
        write_event(
            "command_received",
            {
                "telegram_update_id": update.get("update_id"),
                "telegram_chat_id": chat_id,
                "telegram_from_user_id": from_user_id,
                "command": command,
            },
        )

        if command in {"/start", "/help"}:
            telegram.send_message(chat_id, format_help(exposed_workflows()))
            write_event(
                "help_sent",
                {
                    "telegram_update_id": update.get("update_id"),
                    "telegram_chat_id": chat_id,
                    "command": command,
                },
            )
            return

        if command == "/workflows":
            telegram.send_message(chat_id, format_workflows(exposed_workflows()))
            write_event(
                "workflows_sent",
                {
                    "telegram_update_id": update.get("update_id"),
                    "telegram_chat_id": chat_id,
                },
            )
            return

        if command == "/new":
            store.clear(chat_id)
            telegram.send_message(
                chat_id,
                "Cleared Telegram workflow sessions. The next command starts a fresh session.",
            )
            return

        if command == "/status":
            parts = stripped.split(maxsplit=1)
            mapping = store.get(chat_id)
            if len(parts) == 2 and parts[1].strip():
                mapping = {"latest_run_id": parts[1].strip()}
            telegram.send_message(chat_id, format_status(mapping, harness))
            return

        if command == "/approve_pr":
            parts = stripped.split(maxsplit=1)
            mapping = store.get(chat_id)
            run_id = parts[1].strip() if len(parts) == 2 else ""
            if not run_id and mapping:
                run_id = str(mapping.get("latest_run_id") or "")
            if not run_id:
                telegram.send_message(
                    chat_id,
                    "Usage: /approve_pr <run-id> or start a developer run first.",
                )
                return
            result = harness.post_approve_pr(run_id=run_id)
            telegram.send_message(
                chat_id,
                "Draft pull request created\n"
                f"branch: {result['branch_name']}\n"
                f"commit: {result['commit_sha']}\n"
                f"PR: {result['pull_request_url']}\n"
                "Safeplane did not merge it. Human inspection is required.",
            )
            write_event(
                "developer_remote_write_completed",
                {
                    "telegram_chat_id": chat_id,
                    "run_id": run_id,
                    "approval_id": result.get("approval_id"),
                    "pull_request_url": result.get("pull_request_url"),
                },
            )
            return

        payload = exposed_workflows()
        if command == "/run":
            parts = stripped.split(maxsplit=2)
            if len(parts) < 2:
                telegram.send_message(
                    chat_id,
                    "Usage: /run <entrypoint> <arguments>. Send /workflows for choices.",
                )
                return
            entrypoint = parts[1].strip()
            workflow = workflow_by_entrypoint(payload, entrypoint)
            if workflow is None:
                telegram.send_message(
                    chat_id,
                    f"Unknown or unavailable workflow: {entrypoint}. Send /workflows for choices.",
                )
                return
            dispatch_workflow(
                chat_id=chat_id,
                workflow=workflow,
                argument_text=parts[2] if len(parts) == 3 else "",
                generic_run=True,
                store=store,
                harness=harness,
                telegram=telegram,
            )
            return

        workflow = workflow_by_command(payload, command)
        if workflow is not None:
            parts = stripped.split(maxsplit=1)
            dispatch_workflow(
                chat_id=chat_id,
                workflow=workflow,
                argument_text=parts[1] if len(parts) == 2 else "",
                generic_run=False,
                store=store,
                harness=harness,
                telegram=telegram,
            )
            return

        telegram.send_message(chat_id, "Unknown command. Send /help for all supported commands.")
        return

    payload = exposed_workflows()
    default_entrypoint = str(payload.get("default_entrypoint") or "")
    workflow = workflow_by_entrypoint(payload, default_entrypoint)
    if workflow is None:
        telegram.send_message(
            chat_id,
            "No default Telegram workflow is configured. Send /workflows for explicit commands.",
        )
        return
    dispatch_workflow(
        chat_id=chat_id,
        workflow=workflow,
        argument_text=stripped,
        generic_run=False,
        store=store,
        harness=harness,
        telegram=telegram,
    )


def run_long_polling() -> None:
    token = telegram_bot_token()
    allowed_user_ids = telegram_allowed_user_ids()
    harness_url = os.environ.get("SAFEPLANE_HARNESS_URL", "http://harness:8080")
    poll_timeout = int(os.environ.get("TELEGRAM_POLL_TIMEOUT_SECONDS", "30"))
    poll_sleep = float(os.environ.get("TELEGRAM_POLL_SLEEP_SECONDS", "1"))
    delete_webhook_on_start = os.environ.get("TELEGRAM_DELETE_WEBHOOK_ON_START", "true").lower() == "true"

    telegram = TelegramApi(token)
    bot = telegram.get_me()
    write_event(
        "bot_authenticated",
        {
            "bot_id": bot.get("id"),
            "bot_username": bot.get("username"),
        },
    )
    start_outbound_notification_server(telegram, allowed_user_ids)
    harness = HarnessClient(harness_url)
    store = TelegramSessionStore()

    write_event(
        "connector_started",
        {
            "harness_url": harness_url,
            "allowed_user_count": len(allowed_user_ids),
            "poll_timeout_seconds": poll_timeout,
        },
    )

    if not allowed_user_ids:
        write_event(
            "connector_warning",
            {
                "message": "telegram_allowed_user_ids is empty. All Telegram users will be rejected.",
            },
        )

    if delete_webhook_on_start:
        telegram.delete_webhook(drop_pending_updates=False)
        write_event("webhook_deleted", {"drop_pending_updates": False})

    offset: int | None = None
    polling_ready = False

    while True:
        try:
            updates = telegram.get_updates(
                offset=offset,
                timeout_seconds=poll_timeout,
            )
            if not polling_ready:
                write_event(
                    "polling_ready",
                    {
                        "bot_id": bot.get("id"),
                        "bot_username": bot.get("username"),
                    },
                )
                polling_ready = True

            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1

                try:
                    handle_update(
                        update=update,
                        allowed_user_ids=allowed_user_ids,
                        store=store,
                        harness=harness,
                        telegram=telegram,
                    )
                except Exception as exc:
                    message = update.get("message") or {}
                    chat_id = (message.get("chat") or {}).get("id")
                    text = str(message.get("text") or "")
                    command = command_name(text) if text.strip().startswith("/") else None
                    write_event(
                        "update_handling_failed",
                        {
                            "telegram_update_id": update.get("update_id"),
                            "telegram_chat_id": chat_id,
                            "command": command,
                        },
                        {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    )
                    if chat_id is not None:
                        try:
                            telegram.send_message(
                                int(chat_id),
                                f"Safeplane could not process this command: {exc}",
                            )
                        except Exception as send_exc:
                            write_event(
                                "failure_reply_failed",
                                {
                                    "telegram_update_id": update.get("update_id"),
                                    "telegram_chat_id": chat_id,
                                },
                                {
                                    "type": type(send_exc).__name__,
                                    "message": str(send_exc),
                                },
                            )

        except Exception as exc:
            write_event(
                "polling_failed",
                {"polling_was_ready": polling_ready},
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            time.sleep(poll_sleep)



def append_outbound_notification_log(event: str, payload: dict) -> None:
    log_dir = safeplane_home() / "logs" / "connectors" / "telegram"
    log_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "connector": "telegram",
        "event": event,
        **payload,
    }

    with (log_dir / "outbound-notifications.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def telegram_notification_chat_ids(allowed_user_ids: set[int]) -> list[int]:
    raw = os.environ.get("TELEGRAM_NOTIFICATION_CHAT_IDS", "").strip()

    if raw:
        return [
            int(value.strip())
            for value in raw.split(",")
            if value.strip()
        ]

    secret_path = os.environ.get(
        "TELEGRAM_NOTIFICATION_CHAT_IDS_FILE",
        "/run/secrets/telegram_allowed_user_ids",
    )

    try:
        file_raw = read_secret_file(secret_path)
    except FileNotFoundError:
        file_raw = ""

    if file_raw.strip():
        return [
            int(value.strip())
            for value in file_raw.replace("\n", ",").split(",")
            if value.strip()
        ]

    # For private Telegram chats, user id and chat id are usually the same.
    # This preserves the Telegram connector secret boundary: only the Telegram connector reads Telegram-related secrets.
    return sorted(allowed_user_ids)


def start_outbound_notification_server(
    telegram: TelegramApi,
    allowed_user_ids: set[int],
) -> Thread | None:
    enabled = os.environ.get("TELEGRAM_OUTBOUND_HTTP_ENABLED", "true").lower() == "true"
    if not enabled:
        return None

    host = os.environ.get("TELEGRAM_OUTBOUND_HTTP_HOST", "0.0.0.0")
    port = int(os.environ.get("TELEGRAM_OUTBOUND_HTTP_PORT", "8080"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def _send_json(self, status_code: int, payload: dict) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"status": "ok", "connector": "telegram"})
                return

            self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if self.path != "/notifications/send":
                self._send_json(404, {"error": "not_found"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length).decode("utf-8")
                payload = json.loads(raw_body) if raw_body else {}

                message = str(payload.get("message", "")).strip()
                if not message:
                    raise ValueError("message is required")

                notification_id = str(payload.get("notification_id", ""))
                outbox_id = str(payload.get("outbox_id", ""))

                chat_ids = telegram_notification_chat_ids(allowed_user_ids)
                if not chat_ids:
                    raise RuntimeError(
                        "No Telegram notification chat ids configured. "
                        "Set TELEGRAM_NOTIFICATION_CHAT_IDS_FILE or TELEGRAM_NOTIFICATION_CHAT_IDS."
                    )

                sent_count = 0
                for chat_id in chat_ids:
                    telegram.send_message(chat_id, message)
                    sent_count += 1

                append_outbound_notification_log(
                    "outbound_notification_sent",
                    {
                        "notification_id": notification_id,
                        "outbox_id": outbox_id,
                        "sent_count": sent_count,
                    },
                )

                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "sent_count": sent_count,
                    },
                )
            except Exception as exc:
                append_outbound_notification_log(
                    "outbound_notification_failed",
                    {
                        "error": str(exc),
                    },
                )
                self._send_json(
                    500,
                    {
                        "status": "error",
                        "error": str(exc),
                    },
                )

    server = ThreadingHTTPServer((host, port), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    append_outbound_notification_log(
        "outbound_notification_server_started",
        {
            "host": host,
            "port": port,
        },
    )

    return thread

def main() -> None:
    run_long_polling()


if __name__ == "__main__":
    main()

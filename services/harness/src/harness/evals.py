from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CONTAINER_SAFEPLANE_HOME = Path("/data/safeplane")


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    prompt_template: str
    expected_tool_name: str | None
    expect_tool: bool


@dataclass(frozen=True)
class EvalResult:
    eval_run_id: str
    case_id: str
    prompt: str
    passed: bool
    expected_tool_name: str | None
    observed_tool_names: list[str]
    model_mode: str | None
    configured_model: str | None
    actual_model: str | None
    actual_provider: str | None
    generation_id: str | None
    proposal_invalid_count: int
    mcp_allowed: bool
    input_schema_valid: bool | None
    output_schema_valid: bool | None
    latency_ms: int | None
    session_id: str | None
    run_id: str | None
    trace_path: str | None
    final_message: str | None
    error: str | None
    error_category: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "eval_run_id": self.eval_run_id,
            "case_id": self.case_id,
            "prompt": self.prompt,
            "passed": self.passed,
            "expected_tool_name": self.expected_tool_name,
            "observed_tool_names": self.observed_tool_names,
            "model_mode": self.model_mode,
            "configured_model": self.configured_model,
            "actual_model": self.actual_model,
            "actual_provider": self.actual_provider,
            "generation_id": self.generation_id,
            "proposal_invalid_count": self.proposal_invalid_count,
            "mcp_allowed": self.mcp_allowed,
            "input_schema_valid": self.input_schema_valid,
            "output_schema_valid": self.output_schema_valid,
            "latency_ms": self.latency_ms,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "trace_path": self.trace_path,
            "final_message": self.final_message,
            "error": self.error,
            "error_category": self.error_category,
        }


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_safeplane_home() -> Path:
    return Path(os.environ.get("SAFEPLANE_HOME", str(Path.home() / ".safeplane"))).expanduser()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))

    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_cli_output(output: str) -> dict[str, str | None]:
    session = None
    run = None
    trace = None

    for line in output.splitlines():
        stripped = line.strip()

        if stripped.startswith("session:"):
            session = stripped.split(":", 1)[1].strip()

        if stripped.startswith("run:"):
            run = stripped.split(":", 1)[1].strip()

        if stripped.startswith("trace:"):
            trace = stripped.split(":", 1)[1].strip()

    final_lines: list[str] = []

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(("session:", "turn:", "run:", "status:", "trace:")):
            break
        if stripped:
            final_lines.append(line.rstrip())

    return {
        "session_short": session,
        "run_id": run,
        "trace": trace,
        "final_message": "\n".join(final_lines).strip() or None,
    }


def host_trace_path(trace_value: str | None, safeplane_home: Path) -> Path | None:
    if not trace_value:
        return None

    path = Path(trace_value)

    if path.is_absolute() and path.parts[:3] == CONTAINER_SAFEPLANE_HOME.parts:
        relative = path.relative_to(CONTAINER_SAFEPLANE_HOME)
        return safeplane_home / relative

    return path


def trace_events_for_cli_output(output: str, safeplane_home: Path) -> tuple[Path | None, list[dict[str, Any]]]:
    parsed = parse_cli_output(output)
    trace_dir = host_trace_path(parsed["trace"], safeplane_home)

    if trace_dir is None:
        return None, []

    trace_file = trace_dir / "agent-runtime.trace.jsonl"
    return trace_file, load_jsonl(trace_file)


def session_id_from_trace(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        value = event.get("session_id")
        if isinstance(value, str):
            return value
    return None


def run_id_from_trace(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        value = event.get("run_id")
        if isinstance(value, str):
            return value
    return None


def latency_ms_from_trace(events: list[dict[str, Any]]) -> int | None:
    timestamps: list[datetime] = []

    for event in events:
        value = event.get("ts")
        if not isinstance(value, str):
            continue

        try:
            timestamps.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            continue

    if len(timestamps) < 2:
        return None

    delta = max(timestamps) - min(timestamps)
    return int(delta.total_seconds() * 1000)


def first_output_value(events: list[dict[str, Any]], key: str) -> Any:
    for event in events:
        output = event.get("output")
        if isinstance(output, dict) and output.get(key) is not None:
            return output.get(key)
    return None


def observed_tool_names(events: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []

    for event in events:
        if event.get("event") not in {
            "model_tool_invocation_validated",
            "model_tool_invocation_completed",
            "tool_invocation_completed",
        }:
            continue

        output = event.get("output")
        if not isinstance(output, dict):
            continue

        tool_name = output.get("tool_name")
        if isinstance(tool_name, str) and tool_name not in names:
            names.append(tool_name)

    return names


def count_invalid_proposals(events: list[dict[str, Any]]) -> int:
    return sum(1 for event in events if event.get("event") == "model_tool_proposal_invalid")


def mcp_access_for_case(
    *,
    safeplane_home: Path,
    session_id: str | None,
    run_id: str | None,
    expected_tool_name: str | None,
) -> dict[str, Any] | None:
    if not session_id or not run_id or not expected_tool_name:
        return None

    access_log = safeplane_home / "logs/mcp/tool-access.jsonl"
    rows = load_jsonl(access_log)

    for row in reversed(rows):
        if row.get("session_id") != session_id:
            continue
        if row.get("run_id") != run_id:
            continue
        if row.get("tool_name") != expected_tool_name:
            continue
        return row

    return None


def event_id_from_trace(trace_path: str | None) -> str | None:
    if not trace_path:
        return None

    path = Path(trace_path)
    if not path.exists():
        return None

    events = load_jsonl(path)

    for event in reversed(events):
        output = event.get("output")
        if not isinstance(output, dict):
            continue

        candidates = [
            output,
            output.get("structured_content") if isinstance(output.get("structured_content"), dict) else None,
            output.get("tool_result") if isinstance(output.get("tool_result"), dict) else None,
        ]

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            event_id = candidate.get("event_id")
            if isinstance(event_id, str) and event_id.startswith("cal_evt_"):
                return event_id

            event_data = candidate.get("event")
            if isinstance(event_data, dict):
                nested_event_id = event_data.get("event_id")
                if isinstance(nested_event_id, str) and nested_event_id.startswith("cal_evt_"):
                    return nested_event_id

        text_blob = json.dumps(output, ensure_ascii=False, default=str)
        match = re.search(r"cal_evt_[a-f0-9-]+", text_blob)
        if match:
            return match.group(0)

    return None


def event_id_from_eval_result(result: EvalResult | None) -> str | None:
    if result is None:
        return None

    event_id = event_id_from_trace(result.trace_path)
    if event_id:
        return event_id

    if result.final_message:
        match = re.search(r"cal_evt_[a-f0-9-]+", result.final_message)
        if match:
            return match.group(0)

    return None


def latest_event_id_by_title_fragment(safeplane_home: Path, title_fragment: str) -> str | None:
    events_log = safeplane_home / "data/calendar/events.jsonl"
    rows = load_jsonl(events_log)

    for row in reversed(rows):
        if row.get("op") != "calendar_event_created":
            continue

        event = row.get("event")
        if not isinstance(event, dict):
            continue

        event_id = event.get("id")
        title = event.get("title")

        if not event_id or not isinstance(title, str):
            continue

        if title_fragment in title:
            return str(event_id)

    return None


def score_case(
    *,
    eval_run_id: str,
    case: EvalCase,
    prompt: str,
    output: str,
    safeplane_home: Path,
    error: str | None = None,
) -> EvalResult:
    parsed = parse_cli_output(output)
    trace_file, events = trace_events_for_cli_output(output, safeplane_home)

    session_id = session_id_from_trace(events)
    run_id = run_id_from_trace(events) or parsed["run_id"]

    tools = observed_tool_names(events)
    mcp_access = mcp_access_for_case(
        safeplane_home=safeplane_home,
        session_id=session_id,
        run_id=run_id,
        expected_tool_name=case.expected_tool_name,
    )

    mcp_allowed = bool(mcp_access and mcp_access.get("decision") == "allowed")
    input_schema_valid = None if mcp_access is None else bool(mcp_access.get("input_schema_valid"))
    output_schema_valid = None if mcp_access is None else bool(mcp_access.get("output_schema_valid"))

    if case.expect_tool:
        passed = (
            error is None
            and case.expected_tool_name in tools
            and mcp_allowed
            and input_schema_valid is True
            and output_schema_valid is True
        )
    else:
        passed = error is None and not tools

    return EvalResult(
        eval_run_id=eval_run_id,
        case_id=case.case_id,
        prompt=prompt,
        passed=passed,
        expected_tool_name=case.expected_tool_name,
        observed_tool_names=tools,
        model_mode=first_output_value(events, "model_mode"),
        configured_model=first_output_value(events, "configured_model"),
        actual_model=first_output_value(events, "actual_model"),
        actual_provider=first_output_value(events, "actual_provider"),
        generation_id=first_output_value(events, "generation_id"),
        proposal_invalid_count=count_invalid_proposals(events),
        mcp_allowed=mcp_allowed,
        input_schema_valid=input_schema_valid,
        output_schema_valid=output_schema_valid,
        latency_ms=latency_ms_from_trace(events),
        session_id=session_id,
        run_id=run_id,
        trace_path=str(trace_file) if trace_file else None,
        final_message=parsed["final_message"],
        error=error,
        error_category=classify_error(error, output),
    )


def eval_cases() -> list[EvalCase]:
    return [
        EvalCase(
            case_id="calendar_create_explicit",
            prompt_template=(
                "Add a calendar event called {title} on {date} "
                "from 09:00 to 10:00 Europe/Berlin."
            ),
            expected_tool_name="calendar_create",
            expect_tool=True,
        ),
        EvalCase(
            case_id="calendar_list_day",
            prompt_template="Show my calendar for {date}.",
            expected_tool_name="calendar_list",
            expect_tool=True,
        ),
        EvalCase(
            case_id="calendar_cancel_by_event_id",
            prompt_template="Cancel calendar event {event_id}.",
            expected_tool_name="calendar_cancel",
            expect_tool=True,
        ),
        EvalCase(
            case_id="non_calendar_text_only",
            prompt_template="Draft a short two item checklist for cleaning my desk.",
            expected_tool_name=None,
            expect_tool=False,
        ),
    ]


def classify_error(error: str | None, output: str) -> str | None:
    if error is None:
        return None

    text = (error + "\n" + (output or "")).lower()

    if not text.strip():
        return None

    if "ratelimit" in text or "rate limit" in text or "code\\\":429" in text or "code\":429" in text or " 429" in text:
        return "provider_rate_limited"

    if "model gateway http error" in text or "litellm" in text or "openrouterexception" in text:
        return "provider_error"

    if "timed out" in text or "timeout" in text:
        return "timeout"

    if "safeplane exited with code" in text:
        return "safeplane_cli_error"

    return "unknown_error"


def rate_limit_reset_sleep_seconds(
    *,
    output: str,
    max_sleep_seconds: float,
) -> float | None:
    cleaned = output.replace('\\\"', '"').replace("\\'", "'")
    match = re.search(
        r'"?X-RateLimit-Reset"?\s*:\s*"?(?P<value>\d{10,13})"?',
        cleaned,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    raw_value = int(match.group("value"))
    reset_seconds = raw_value / 1000 if raw_value > 10_000_000_000 else raw_value
    sleep_seconds = reset_seconds - time.time() + 2.0

    if sleep_seconds <= 0:
        return None

    return min(sleep_seconds, max_sleep_seconds)


def provider_retry_sleep_seconds(
    *,
    category: str | None,
    output: str,
    attempt_index: int,
    base_sleep_seconds: float,
    max_sleep_seconds: float,
) -> float:
    if category == "provider_rate_limited":
        reset_sleep = rate_limit_reset_sleep_seconds(
            output=output,
            max_sleep_seconds=max_sleep_seconds,
        )
        if reset_sleep is not None:
            return reset_sleep

    return min(
        max_sleep_seconds,
        base_sleep_seconds * (2 ** attempt_index),
    )


def run_safeplane_assistant(
    *,
    prompt: str,
    harness_url: str,
    timeout_seconds: int,
    provider_retry_count: int = 3,
    provider_retry_base_sleep_seconds: float = 20.0,
    provider_retry_max_sleep_seconds: float = 90.0,
) -> tuple[str, str | None]:
    env = dict(os.environ)
    env["SAFEPLANE_HARNESS_URL"] = harness_url

    attempts: list[str] = []

    for attempt_index in range(provider_retry_count + 1):
        try:
            completed = subprocess.run(
                ["./scripts/safeplane", "assistant", prompt],
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )

            output = (completed.stdout or "") + (completed.stderr or "")

            if completed.returncode == 0:
                if attempts:
                    attempts.append(
                        f"attempt {attempt_index + 1}: success after provider retry\n{output}"
                    )
                    return "\n\n".join(attempts), None

                return output, None

            error = f"safeplane exited with code {completed.returncode}"
            category = classify_error(error, output)
            attempts.append(
                f"attempt {attempt_index + 1}: {category or 'unknown_error'}: {error}\n{output}"
            )

            if category not in {"provider_rate_limited", "provider_error", "timeout"}:
                return output, error

            if attempt_index < provider_retry_count:
                sleep_seconds = provider_retry_sleep_seconds(
                    category=category,
                    output=output,
                    attempt_index=attempt_index,
                    base_sleep_seconds=provider_retry_base_sleep_seconds,
                    max_sleep_seconds=provider_retry_max_sleep_seconds,
                )
                time.sleep(sleep_seconds)
                continue

            return "\n\n".join(attempts), error

        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""

            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")

            output = stdout + stderr
            error = f"safeplane timed out after {timeout_seconds} seconds"
            attempts.append(
                f"attempt {attempt_index + 1}: timeout: {error}\n{output}"
            )

            if attempt_index < provider_retry_count:
                sleep_seconds = provider_retry_sleep_seconds(
                    category="timeout",
                    output=output,
                    attempt_index=attempt_index,
                    base_sleep_seconds=provider_retry_base_sleep_seconds,
                    max_sleep_seconds=provider_retry_max_sleep_seconds,
                )
                time.sleep(sleep_seconds)
                continue

            return "\n\n".join(attempts), error

    return "\n\n".join(attempts), "safeplane eval exhausted retries"


def make_summary(results: list[EvalResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)

    retry_counts = [result.proposal_invalid_count for result in results]
    latencies = [result.latency_ms for result in results if result.latency_ms is not None]

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else 0.0,
        "max_invalid_proposals": max(retry_counts) if retry_counts else 0,
        "total_invalid_proposals": sum(retry_counts),
        "max_latency_ms": max(latencies) if latencies else None,
        "configured_models": sorted(
            {
                result.configured_model
                for result in results
                if result.configured_model
            }
        ),
        "actual_models": sorted(
            {
                result.actual_model
                for result in results
                if result.actual_model
            }
        ),
        "actual_providers": sorted(
            {
                result.actual_provider
                for result in results
                if result.actual_provider
            }
        ),
        "error_categories": {
            category: sum(1 for result in results if result.error_category == category)
            for category in sorted(
                {
                    result.error_category
                    for result in results
                    if result.error_category
                }
            )
        },
    }


def run_assistant_calendar_eval(
    *,
    safeplane_home: Path,
    harness_url: str,
    timeout_seconds: int = 120,
    case_delay_seconds: float = 8.0,
    provider_retry_count: int = 3,
    provider_retry_base_sleep_seconds: float = 20.0,
    provider_retry_max_sleep_seconds: float = 90.0,
) -> tuple[Path, Path, list[EvalResult], dict[str, Any]]:
    eval_run_id = "eval_" + uuid.uuid4().hex[:12]
    date = "2026-07-19"
    title = f"Safeplane eval {eval_run_id}"

    state: dict[str, str] = {
        "date": date,
        "title": title,
        "event_id": "missing_event_id",
    }

    results: list[EvalResult] = []

    for case in eval_cases():
        if case.case_id == "calendar_cancel_by_event_id":
            create_result = next(
                (
                    result
                    for result in results
                    if result.case_id == "calendar_create_explicit"
                ),
                None,
            )
            event_id = event_id_from_eval_result(create_result)
            if not event_id:
                event_id = latest_event_id_by_title_fragment(safeplane_home, eval_run_id)

            if event_id:
                state["event_id"] = event_id
            else:
                result = EvalResult(
                    eval_run_id=eval_run_id,
                    case_id=case.case_id,
                    prompt=case.prompt_template.format(**state),
                    passed=False,
                    expected_tool_name=case.expected_tool_name,
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
                    error="could not resolve event_id from calendar_create case",
                    error_category="eval_state_error",
                )
                results.append(result)
                continue

        prompt = case.prompt_template.format(**state)
        output, error = run_safeplane_assistant(
            prompt=prompt,
            harness_url=harness_url,
            timeout_seconds=timeout_seconds,
            provider_retry_count=provider_retry_count,
            provider_retry_base_sleep_seconds=provider_retry_base_sleep_seconds,
            provider_retry_max_sleep_seconds=provider_retry_max_sleep_seconds,
        )

        result = score_case(
            eval_run_id=eval_run_id,
            case=case,
            prompt=prompt,
            output=output,
            safeplane_home=safeplane_home,
            error=error,
        )
        results.append(result)

        if case_delay_seconds > 0:
            time.sleep(case_delay_seconds)

    output_dir = safeplane_home / "evals/assistant-calendar-tools"
    jsonl_path = output_dir / f"{eval_run_id}.jsonl"
    summary_path = output_dir / f"{eval_run_id}.summary.json"

    rows = [result.to_json() for result in results]
    summary = {
        "eval_run_id": eval_run_id,
        "created_at": utc_now_iso(),
        "suite": "assistant-calendar-tools",
        "harness_url": harness_url,
        "case_delay_seconds": case_delay_seconds,
        "provider_retry_count": provider_retry_count,
        "provider_retry_base_sleep_seconds": provider_retry_base_sleep_seconds,
        "provider_retry_max_sleep_seconds": provider_retry_max_sleep_seconds,
        **make_summary(results),
    }

    write_jsonl(jsonl_path, rows)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return jsonl_path, summary_path, results, summary


def summarize_result_group(results: list[EvalResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    latencies = [result.latency_ms for result in results if result.latency_ms is not None]

    error_categories: dict[str, int] = {}
    for result in results:
        if not result.error_category:
            continue
        error_categories[result.error_category] = error_categories.get(result.error_category, 0) + 1

    case_ids = sorted({result.case_id for result in results})
    per_case: dict[str, dict[str, Any]] = {}

    for case_id in case_ids:
        case_results = [result for result in results if result.case_id == case_id]
        case_total = len(case_results)
        case_passed = sum(1 for result in case_results if result.passed)
        per_case[case_id] = {
            "total": case_total,
            "passed": case_passed,
            "failed": case_total - case_passed,
            "pass_rate": case_passed / case_total if case_total else 0.0,
        }

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else 0.0,
        "total_invalid_proposals": sum(result.proposal_invalid_count for result in results),
        "max_invalid_proposals": max(
            (result.proposal_invalid_count for result in results),
            default=0,
        ),
        "max_latency_ms": max(latencies) if latencies else None,
        "error_categories": error_categories,
        "per_case": per_case,
    }


def grouped_result_summaries(
    *,
    results: list[EvalResult],
    field_name: str,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[EvalResult]] = {}

    for result in results:
        value = getattr(result, field_name)
        if not value:
            value = "unknown"

        grouped.setdefault(str(value), []).append(result)

    return {
        key: summarize_result_group(group_results)
        for key, group_results in sorted(grouped.items())
    }


def router_profile_summary(results: list[EvalResult]) -> dict[str, Any]:
    configured_models = sorted(
        {
            result.configured_model
            for result in results
            if result.configured_model
        }
    )
    actual_models = sorted(
        {
            result.actual_model
            for result in results
            if result.actual_model
        }
    )
    actual_providers = sorted(
        {
            result.actual_provider
            for result in results
            if result.actual_provider
        }
    )

    is_router = configured_models == ["openrouter/openrouter/free"]

    return {
        "is_router_route": is_router,
        "configured_route": configured_models[0] if len(configured_models) == 1 else None,
        "configured_model_count": len(configured_models),
        "actual_model_count": len(actual_models),
        "actual_provider_count": len(actual_providers),
        "actual_models": actual_models,
        "actual_providers": actual_providers,
        "note": (
            "Configured route is a router. Actual model/provider are observations, not stable selections."
            if is_router
            else None
        ),
    }



def summarize_eval_batch(
    *,
    batch_id: str,
    suite: str,
    harness_url: str,
    run_summaries: list[dict[str, Any]],
    results: list[EvalResult],
    case_delay_seconds: float,
    between_run_delay_seconds: float,
    provider_retry_count: int,
    provider_retry_base_sleep_seconds: float,
    provider_retry_max_sleep_seconds: float,
) -> dict[str, Any]:
    total_cases = len(results)
    passed_cases = sum(1 for result in results if result.passed)
    total_runs = len(run_summaries)
    passed_runs = sum(1 for summary in run_summaries if summary.get("failed") == 0)

    case_ids = sorted({result.case_id for result in results})
    per_case: dict[str, dict[str, Any]] = {}

    for case_id in case_ids:
        case_results = [result for result in results if result.case_id == case_id]
        case_total = len(case_results)
        case_passed = sum(1 for result in case_results if result.passed)
        per_case[case_id] = {
            "total": case_total,
            "passed": case_passed,
            "failed": case_total - case_passed,
            "pass_rate": case_passed / case_total if case_total else 0.0,
            "max_invalid_proposals": max(
                (result.proposal_invalid_count for result in case_results),
                default=0,
            ),
        }

    error_categories: dict[str, int] = {}
    for result in results:
        if not result.error_category:
            continue
        error_categories[result.error_category] = error_categories.get(result.error_category, 0) + 1

    latencies = [result.latency_ms for result in results if result.latency_ms is not None]

    return {
        "batch_id": batch_id,
        "created_at": utc_now_iso(),
        "suite": suite,
        "harness_url": harness_url,
        "total_runs": total_runs,
        "passed_runs": passed_runs,
        "failed_runs": total_runs - passed_runs,
        "run_pass_rate": passed_runs / total_runs if total_runs else 0.0,
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": total_cases - passed_cases,
        "case_pass_rate": passed_cases / total_cases if total_cases else 0.0,
        "total_invalid_proposals": sum(result.proposal_invalid_count for result in results),
        "max_invalid_proposals": max(
            (result.proposal_invalid_count for result in results),
            default=0,
        ),
        "max_latency_ms": max(latencies) if latencies else None,
        "configured_models": sorted(
            {
                result.configured_model
                for result in results
                if result.configured_model
            }
        ),
        "actual_models": sorted(
            {
                result.actual_model
                for result in results
                if result.actual_model
            }
        ),
        "actual_providers": sorted(
            {
                result.actual_provider
                for result in results
                if result.actual_provider
            }
        ),
        "error_categories": error_categories,
        "per_case": per_case,
        "run_summaries": run_summaries,
        "router_profile": router_profile_summary(results),
        "per_actual_model": grouped_result_summaries(
            results=results,
            field_name="actual_model",
        ),
        "per_actual_provider": grouped_result_summaries(
            results=results,
            field_name="actual_provider",
        ),
        "case_delay_seconds": case_delay_seconds,
        "between_run_delay_seconds": between_run_delay_seconds,
        "provider_retry_count": provider_retry_count,
        "provider_retry_base_sleep_seconds": provider_retry_base_sleep_seconds,
        "provider_retry_max_sleep_seconds": provider_retry_max_sleep_seconds,
    }


def run_assistant_calendar_eval_batch(
    *,
    safeplane_home: Path,
    harness_url: str,
    runs: int,
    timeout_seconds: int = 120,
    case_delay_seconds: float = 8.0,
    between_run_delay_seconds: float = 20.0,
    provider_retry_count: int = 3,
    provider_retry_base_sleep_seconds: float = 20.0,
    provider_retry_max_sleep_seconds: float = 90.0,
) -> tuple[Path, Path, list[EvalResult], dict[str, Any]]:
    if runs < 1:
        raise ValueError("runs must be >= 1")

    batch_id = "batch_" + uuid.uuid4().hex[:12]
    output_dir = safeplane_home / "evals/assistant-calendar-tools"

    all_results: list[EvalResult] = []
    run_summaries: list[dict[str, Any]] = []

    for run_index in range(runs):
        _, _, results, summary = run_assistant_calendar_eval(
            safeplane_home=safeplane_home,
            harness_url=harness_url,
            timeout_seconds=timeout_seconds,
            case_delay_seconds=case_delay_seconds,
            provider_retry_count=provider_retry_count,
            provider_retry_base_sleep_seconds=provider_retry_base_sleep_seconds,
            provider_retry_max_sleep_seconds=provider_retry_max_sleep_seconds,
        )

        summary = {
            **summary,
            "batch_id": batch_id,
            "run_index": run_index + 1,
        }
        run_summaries.append(summary)
        all_results.extend(results)

        if run_index < runs - 1 and between_run_delay_seconds > 0:
            time.sleep(between_run_delay_seconds)

    batch_jsonl_path = output_dir / f"{batch_id}.jsonl"
    batch_summary_path = output_dir / f"{batch_id}.summary.json"

    rows: list[dict[str, Any]] = []
    for result in all_results:
        row = result.to_json()
        row["batch_id"] = batch_id
        rows.append(row)

    batch_summary = summarize_eval_batch(
        batch_id=batch_id,
        suite="assistant-calendar-tools",
        harness_url=harness_url,
        run_summaries=run_summaries,
        results=all_results,
        case_delay_seconds=case_delay_seconds,
        between_run_delay_seconds=between_run_delay_seconds,
        provider_retry_count=provider_retry_count,
        provider_retry_base_sleep_seconds=provider_retry_base_sleep_seconds,
        provider_retry_max_sleep_seconds=provider_retry_max_sleep_seconds,
    )

    write_jsonl(batch_jsonl_path, rows)
    batch_summary_path.parent.mkdir(parents=True, exist_ok=True)
    batch_summary_path.write_text(
        json.dumps(batch_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return batch_jsonl_path, batch_summary_path, all_results, batch_summary

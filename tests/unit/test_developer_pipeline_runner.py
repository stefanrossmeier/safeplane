from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import harness.developer_pipeline as developer_pipeline_module

from harness.developer_pipeline import (
    DeveloperPipelineStore,
    DeveloperPipelineTransitionError,
    ImplementationApplyResult,
    ImplementationPatch,
    ImplementationPlan,
    StageModelCallResult,
    _run_declared_checks,
    _render_stage_user_message,
    _validate_plan_against_operator_constraints,
    _validate_planned_check_commands,
    run_developer_pipeline,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_contract() -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "workflows/developer/workflow.yaml").read_text(encoding="utf-8")
    )


def fake_response_file(profile: dict, response_key: str, messages: list[dict]) -> Path:
    configured = profile["fake_responses"][response_key]
    if isinstance(configured, list):
        assistant_turns = sum(1 for message in messages if message.get("role") == "assistant")
        configured = configured[min(assistant_turns, len(configured) - 1)]
    return REPO_ROOT / configured


def compatibility_tool_caller(repo: Path):
    def tool(stage_id, agent_id, server_id, tool_name, arguments, approval_id, approval_token):
        if tool_name == "dev_check_run":
            assert stage_id == "implementation_candidate_checks"
            assert agent_id is None
            assert server_id == "dev-check"
            return {
                "status": "passed",
                "exit_code": 0,
                "duration_ms": 1,
                "stdout": "PASS\n",
                "stderr": "",
                "candidate_patch_applied": True,
            }
        assert stage_id == "implementation"
        assert agent_id == "implementation"
        assert server_id == "dev-workspace"
        if tool_name == "dev_workspace_read":
            target = repo / arguments["path"]
            lines = target.read_text(encoding="utf-8").splitlines()
            start = int(arguments.get("start_line", 1))
            count = int(arguments.get("max_lines", 200))
            selected = lines[start - 1 : start - 1 + count]
            return {
                "command": ["read", arguments["path"]],
                "cwd": str(repo),
                "workspace_root": str(repo),
                "exit_code": 0,
                "truncated": start - 1 + count < len(lines),
                "path": arguments["path"],
                "start_line": start,
                "end_line": start + len(selected) - 1,
                "next_start_line": start + len(selected) if start - 1 + len(selected) < len(lines) else None,
                "content": "\n".join(selected) + ("\n" if selected else ""),
            }
        if tool_name == "dev_workspace_grep":
            matches = []
            query = arguments["query"]
            base = repo / arguments.get("path", ".")
            for candidate in sorted(base.rglob(arguments.get("file_glob", "*"))):
                if not candidate.is_file():
                    continue
                for line_number, line in enumerate(candidate.read_text(encoding="utf-8").splitlines(), start=1):
                    if query in line:
                        matches.append({
                            "path": str(candidate.relative_to(repo)),
                            "line_number": line_number,
                            "line": line,
                        })
            return {
                "command": ["grep", query],
                "cwd": str(repo),
                "workspace_root": str(repo),
                "exit_code": 0,
                "truncated": False,
                "matches": matches,
            }
        raise AssertionError(tool_name)

    return tool


def run_pipeline(
    tmp_path: Path,
    *,
    run_id: str,
    message: str,
    invalid_once_stage: str | None = None,
    malformed_implementation_once: bool = False,
    planning_constraint_violation_once: bool = False,
    raise_stage: str | None = None,
):
    contract = load_contract()
    home = tmp_path / "home"
    repo = home / "workspaces" / run_id / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "greeter.py").write_text(
        'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
        encoding="utf-8",
    )
    (repo / "checks").mkdir(exist_ok=True)
    (repo / "checks" / "check_greeting.py").write_text(
        'from pathlib import Path\n'
        'source = Path("src/greeter.py").read_text(encoding="utf-8")\n'
        'assert "developer pipeline" in source\n',
        encoding="utf-8",
    )
    calls: list[dict] = []
    traces: list[dict] = []
    invalid_returned = False
    malformed_implementation_returned = False
    planning_constraint_violation_returned = False

    def caller(stage_id, response_key, model_profile, messages):
        nonlocal invalid_returned, malformed_implementation_returned
        nonlocal planning_constraint_violation_returned
        calls.append(
            {
                "stage_id": stage_id,
                "response_key": response_key,
                "model_profile": model_profile,
                "messages": messages,
            }
        )
        profile = contract["model_profiles"][model_profile]
        if stage_id == raise_stage:
            raise RuntimeError(f"interrupted at {stage_id}")
        if stage_id == invalid_once_stage and not invalid_returned:
            invalid_returned = True
            return StageModelCallResult(
                content="not valid JSON",
                model={
                    "mode": "fake",
                    "configured_model": profile["litellm_model"],
                    "actual_model": f"fake/{model_profile}",
                    "actual_provider": "safeplane-fake",
                    "model_profile": model_profile,
                },
            )
        if (
            stage_id == "planning"
            and planning_constraint_violation_once
            and not planning_constraint_violation_returned
        ):
            planning_constraint_violation_returned = True
            contradictory = {
                "developer_plan_markdown": "# Developer Plan\n\nModify the requested file and add a focused verification script.",
                "files_to_modify": ["src/greeter.py"],
                "files_to_create": ["tests/verify_greeting.py"],
                "files_to_delete": [],
                "file_change_policy": {
                    "src/greeter.py": {
                        "expected_change_summary": "Change only the returned greeting text.",
                        "max_changed_lines": 4,
                        "max_hunks": 1,
                    },
                    "tests/verify_greeting.py": {
                        "expected_change_summary": "Add a focused verification script.",
                        "max_changed_lines": 12,
                        "max_hunks": 1,
                    },
                },
                "test_commands": [["python3", "tests/verify_greeting.py"]],
                "documentation_impact": "None.",
                "risks": ["The added script exceeds the operator scope."],
                "assumptions": ["A new verification script is permitted."],
                "commit_message": "Adjust fixture greeting",
            }
            return StageModelCallResult(
                content=json.dumps(contradictory),
                model={
                    "mode": "fake",
                    "configured_model": profile["litellm_model"],
                    "actual_model": f"fake/{model_profile}",
                    "actual_provider": "safeplane-fake",
                    "model_profile": model_profile,
                },
            )
        if (
            stage_id == "implementation"
            and malformed_implementation_once
            and not malformed_implementation_returned
        ):
            malformed_implementation_returned = True
            malformed = {
                "type": "final",
                "implementation_summary_markdown": "# Implementation Summary\n\nMalformed first attempt.",
                "replacements": [
                    {
                        "path": "src/greeter.py",
                        "old_text": "    return f\"Hello from stale context, {name}!\"",
                        "new_text": "    return f\"Hello from the developer pipeline, {name}!\"",
                    }
                ],
                "changed_files": ["src/greeter.py"],
            }
            return StageModelCallResult(
                content=json.dumps(malformed),
                model={
                    "mode": "fake",
                    "configured_model": profile["litellm_model"],
                    "actual_model": f"fake/{model_profile}",
                    "actual_provider": "safeplane-fake",
                    "model_profile": model_profile,
                },
            )
        response_file = fake_response_file(profile, response_key, messages)
        return StageModelCallResult(
            content=response_file.read_text(encoding="utf-8"),
            model={
                "mode": "fake",
                "configured_model": profile["litellm_model"],
                "actual_model": f"fake/{model_profile}",
                "actual_provider": "safeplane-fake",
                "model_profile": model_profile,
            },
        )

    def trace(event, input_data, output_data, artifact_refs, error):
        traces.append(
            {
                "event": event,
                "input": input_data,
                "output": output_data,
                "artifact_refs": artifact_refs,
                "error": error,
            }
        )

    result = run_developer_pipeline(
        contract=contract,
        config_path=REPO_ROOT / "safeplane.yaml",
        safeplane_home=home,
        run_id=run_id,
        operator_message=message,
        workspace_manifest={
            "workspace_kind": "local_snapshot",
            "repository_root": str(repo),
            "read_only": True,
        },
        call_stage_model=caller,
        trace=trace,
        call_stage_tool=compatibility_tool_caller(repo),
    )
    state = json.loads(
        (home / "workspaces" / run_id / "pipeline" / "pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    return result, state, calls, traces, home


def test_fake_pipeline_reaches_waiting_for_remote_approval_with_per_agent_model_metadata(tmp_path: Path) -> None:
    result, state, calls, traces, home = run_pipeline(
        tmp_path,
        run_id="run_lgtm",
        message="Implement the bounded fixture greeting task",
    )

    assert result.current_state == "waiting_for_remote_approval"
    assert state["current_state"] == "waiting_for_remote_approval"
    assert state["completed_stages"] == [
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
    ]
    assert len(state["agent_runs"]) == 7
    assert len({item["model_profile"] for item in state["agent_runs"]}) == 6
    assert all(item["prompt_id"] for item in state["agent_runs"])
    assert all(item["actual_provider"] == "safeplane-fake" for item in state["agent_runs"])
    assert (home / state["artifacts"]["pr.md"]).exists()
    assert "remote-approval-request.json" not in state["artifacts"]
    waiting_trace = next(
        item
        for item in traces
        if item["event"] == "developer_pipeline_waiting_for_remote_approval"
    )
    assert waiting_trace["output"]["approval_request_created"] is False
    assert any(item["event"] == "developer_pipeline_stage_completed" for item in traces)

    analysis_call = next(item for item in calls if item["stage_id"] == "analysis")
    assert "baseline_documentation" in analysis_call["messages"][1]["content"]
    assert [item["stage_id"] for item in calls] == [
        "baseline_documentation",
        "analysis",
        "planning",
        "implementation",
        "implementation",
        "final_documentation",
        "review",
        "pr",
    ]


def test_request_changes_stops_without_pr_stage(tmp_path: Path) -> None:
    result, state, calls, _, home = run_pipeline(
        tmp_path,
        run_id="run_changes",
        message=(
            "[safeplane-fake-scenario:review_changes_requested] "
            "Implement the bounded fixture greeting task"
        ),
    )

    assert result.current_state == "review_changes_requested"
    assert state["current_state"] == "review_changes_requested"
    assert state["completed_stages"][-1] == "review"
    assert "pr" not in [item["stage_id"] for item in calls]
    assert "pr.md" not in state["artifacts"]
    assert not (home / "workspaces" / "run_changes" / "pipeline" / "pr.md").exists()


def test_pipeline_store_rejects_out_of_order_and_repeated_stages(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "workspaces" / "run_state").mkdir(parents=True)
    store = DeveloperPipelineStore(
        safeplane_home=home,
        run_id="run_state",
        fake_scenario="default",
    )

    with pytest.raises(DeveloperPipelineTransitionError, match="requires state"):
        store.transition(stage_id="analysis", target_state="analysis_ready")

    store.transition(stage_id="repositories", target_state="repositories_ready")
    with pytest.raises(DeveloperPipelineTransitionError, match="already completed"):
        store.transition(stage_id="repositories", target_state="repositories_ready")


def test_pipeline_resume_does_not_repeat_completed_stages(tmp_path: Path) -> None:
    first, first_state, first_calls, _, _ = run_pipeline(
        tmp_path,
        run_id="run_resume",
        message="Implement the bounded fixture greeting task",
    )
    second, second_state, second_calls, _, _ = run_pipeline(
        tmp_path,
        run_id="run_resume",
        message="Implement the bounded fixture greeting task",
    )

    assert first.current_state == "waiting_for_remote_approval"
    assert second.current_state == "waiting_for_remote_approval"
    assert len(first_calls) == 8
    assert second_calls == []
    assert second_state == first_state


def test_invalid_model_output_is_retried_within_agent_budget(tmp_path: Path) -> None:
    result, state, calls, traces, _ = run_pipeline(
        tmp_path,
        run_id="run_retry",
        message="Implement the bounded fixture greeting task",
        invalid_once_stage="analysis",
    )

    assert result.current_state == "waiting_for_remote_approval"
    assert [item["stage_id"] for item in calls].count("analysis") == 2
    analysis_run = next(item for item in state["agent_runs"] if item["stage_id"] == "analysis")
    assert analysis_run["retry_count"] == 1
    assert any(item["event"] == "developer_pipeline_stage_attempt_failed" for item in traces)


def test_documentation_stage_message_withholds_operator_task() -> None:
    task = "README only. Do not add new files or check scripts."
    message = json.loads(
        _render_stage_user_message(
            stage_id="baseline_documentation",
            task=task,
            input_artifacts={
                "developer_request": {"task": task},
                "repository_context": {"repository_profile": "fixture"},
            },
        )
    )

    assert "operator_task" not in message
    assert "developer_request" not in message["input_artifacts"]
    assert task not in json.dumps(message)
    assert "README.md" in message["stage_boundary"]
    assert "docs/" in message["stage_boundary"]


def test_planning_retries_when_plan_violates_operator_file_constraints(
    tmp_path: Path,
) -> None:
    result, state, calls, traces, _ = run_pipeline(
        tmp_path,
        run_id="run_operator_constraint_retry",
        message=(
            "Only modify src/greeter.py. Do not add new files. "
            "Do not add check scripts."
        ),
        planning_constraint_violation_once=True,
    )

    assert result.current_state == "waiting_for_remote_approval"
    planning_calls = [item for item in calls if item["stage_id"] == "planning"]
    assert len(planning_calls) == 2
    repair_message = planning_calls[1]["messages"][-1]["content"]
    assert "contradicts explicit operator file constraints" in repair_message
    assert "tests/verify_greeting.py" in repair_message
    assert "paths outside explicit only-scope ['src/greeter.py']" in repair_message
    assert "new files were forbidden" in repair_message
    assert "check-script changes were forbidden" in repair_message
    planning_run = next(
        item for item in state["agent_runs"] if item["stage_id"] == "planning"
    )
    assert planning_run["retry_count"] == 1
    assert planning_run["model_call_count"] == 2
    assert any(
        item["event"] == "developer_pipeline_stage_attempt_failed"
        and item["input"]["stage_id"] == "planning"
        for item in traces
    )


def test_fake_scenario_retries_malformed_implementation_with_repair_fixture(
    tmp_path: Path,
) -> None:
    result, state, calls, _, _ = run_pipeline(
        tmp_path,
        run_id="run_fake_implementation_repair",
        message=(
            "[safeplane-fake-scenario:implementation_patch_retry] "
            "Implement the bounded fixture greeting task"
        ),
    )

    assert result.current_state == "waiting_for_remote_approval"
    implementation_calls = [
        item for item in calls if item["stage_id"] == "implementation"
    ]
    assert [item["response_key"] for item in implementation_calls] == [
        "implementation_malformed",
        "implementation_malformed",
        "implementation_malformed",
    ]
    implementation_run = next(
        item for item in state["agent_runs"] if item["stage_id"] == "implementation"
    )
    assert implementation_run["retry_count"] == 1
    assert implementation_run["model_call_count"] == 3
    assert implementation_run["tool_call_count"] == 1


def test_fake_scenario_retries_implementation_that_exceeds_plan_budget(
    tmp_path: Path,
) -> None:
    result, state, calls, traces, _ = run_pipeline(
        tmp_path,
        run_id="run_fake_implementation_budget_repair",
        message=(
            "[safeplane-fake-scenario:implementation_budget_retry] "
            "Implement the bounded fixture greeting task"
        ),
    )

    assert result.current_state == "waiting_for_remote_approval"
    implementation_calls = [
        item for item in calls if item["stage_id"] == "implementation"
    ]
    assert [item["response_key"] for item in implementation_calls] == [
        "implementation_budget_retry",
        "implementation_budget_retry",
        "implementation_budget_retry",
    ]
    implementation_run = next(
        item for item in state["agent_runs"] if item["stage_id"] == "implementation"
    )
    assert implementation_run["retry_count"] == 1
    assert implementation_run["model_call_count"] == 3
    assert implementation_run["tool_call_count"] == 1
    failed = [
        item
        for item in traces
        if item["event"] == "developer_pipeline_stage_attempt_failed"
        and item["input"]["stage_id"] == "implementation"
    ]
    assert len(failed) == 1
    assert "changed-line budget exceeded" in failed[0]["error"]["message"]


def test_implementation_patch_budget_counts_added_and_removed_lines(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "greeter.py").write_text(
        'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
        encoding="utf-8",
    )
    plan = ImplementationPlan.model_validate(
        json.loads(
            (REPO_ROOT / "prompts/developer/fake/planning.v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    over_budget = ImplementationPatch(
        implementation_summary_markdown="Too broad",
        unified_diff=(
            "diff --git a/src/greeter.py b/src/greeter.py\n"
            "--- a/src/greeter.py\n"
            "+++ b/src/greeter.py\n"
            "@@ -1,2 +1,5 @@\n"
            " def greet(name: str) -> str:\n"
            "-    return f\"Hello, {name}!\"\n"
            "+    prefix = \"Hello from\"\n"
            "+    source = \"the developer pipeline\"\n"
            "+    punctuation = \"!\"\n"
            "+    return f\"{prefix} {source}, {name}{punctuation}\"\n"
        ),
        changed_files=["src/greeter.py"],
    )

    with pytest.raises(
        developer_pipeline_module.DeveloperPipelineError,
        match=r"changed-line budget exceeded for src/greeter.py: 5 > 4",
    ):
        developer_pipeline_module._validate_implementation_attempt(
            over_budget,
            plan=plan,
            repository_root=repo,
        )


def test_implementation_patch_applicability_rejects_malformed_and_stale_diffs(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "greeter.py").write_text(
        'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
        encoding="utf-8",
    )
    valid_patch = (
        "diff --git a/src/greeter.py b/src/greeter.py\n"
        "--- a/src/greeter.py\n"
        "+++ b/src/greeter.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet(name: str) -> str:\n"
        "-    return f\"Hello, {name}!\"\n"
        "+    return f\"Hello from the developer pipeline, {name}!\"\n"
    )

    assert developer_pipeline_module._validate_implementation_patch_applicability(
        valid_patch,
        repository_root=repo,
    ) == {"src/greeter.py"}

    malformed_patch = valid_patch.replace("@@ -1,2 +1,2 @@", "@@ -1,2 +1,3 @@")
    with pytest.raises(
        developer_pipeline_module.DeveloperPipelineError,
        match="implementation unified_diff is malformed or does not apply cleanly",
    ):
        developer_pipeline_module._validate_implementation_patch_applicability(
            malformed_patch,
            repository_root=repo,
        )

    stale_patch = valid_patch.replace('Hello, {name}!', 'Goodbye, {name}!')
    with pytest.raises(
        developer_pipeline_module.DeveloperPipelineError,
        match="implementation unified_diff is malformed or does not apply cleanly",
    ):
        developer_pipeline_module._validate_implementation_patch_applicability(
            stale_patch,
            repository_root=repo,
        )

    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    plan = ImplementationPlan.model_validate(
        json.loads(
            (REPO_ROOT / "prompts/developer/fake/planning.v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    wrong_path_patch = ImplementationPatch(
        implementation_summary_markdown="# Implementation Summary\n\nWrong path.",
        unified_diff=(
            "diff --git a/README.md b/README.md\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -1 +1 @@\n"
            "-fixture\n"
            "+changed fixture\n"
        ),
        changed_files=["src/greeter.py"],
    )
    with pytest.raises(
        developer_pipeline_module.DeveloperPipelineError,
        match="implementation unified_diff paths must exactly match planned change paths",
    ):
        developer_pipeline_module._validate_implementation_attempt(
            wrong_path_patch,
            plan=plan,
            repository_root=repo,
        )


def test_invalid_implementation_replacement_is_retried_with_exact_feedback(
    tmp_path: Path,
) -> None:
    result, state, calls, traces, _ = run_pipeline(
        tmp_path,
        run_id="run_implementation_retry",
        message="Implement the bounded fixture greeting task",
        malformed_implementation_once=True,
    )

    assert result.current_state == "waiting_for_remote_approval"
    implementation_calls = [
        item for item in calls if item["stage_id"] == "implementation"
    ]
    assert len(implementation_calls) == 2
    repair_message = implementation_calls[1]["messages"][-1]["content"]
    assert "Validation error: DeveloperPipelineError:" in repair_message
    assert "implementation replacement old_text must match exactly once" in repair_message
    assert "src/greeter.py" in repair_message
    implementation_run = next(
        item for item in state["agent_runs"] if item["stage_id"] == "implementation"
    )
    assert implementation_run["retry_count"] == 1
    failed = [
        item
        for item in traces
        if item["event"] == "developer_pipeline_stage_attempt_failed"
        and item["input"]["stage_id"] == "implementation"
    ]
    assert len(failed) == 1
    assert "old_text must match exactly once" in failed[0]["error"]["message"]


def test_resume_after_interruption_skips_completed_model_and_deterministic_stages(
    tmp_path: Path,
) -> None:
    with pytest.raises(Exception, match="planning produced no valid output"):
        run_pipeline(
            tmp_path,
            run_id="run_interrupted",
            message="Implement the bounded fixture greeting task",
            raise_stage="planning",
        )

    result, state, calls, _, _ = run_pipeline(
        tmp_path,
        run_id="run_interrupted",
        message="Implement the bounded fixture greeting task",
    )

    assert result.current_state == "waiting_for_remote_approval"
    assert [item["stage_id"] for item in calls] == [
        "planning",
        "implementation",
        "implementation",
        "final_documentation",
        "review",
        "pr",
    ]
    assert state["completed_stages"].count("repositories") == 1
    assert state["completed_stages"].count("baseline_documentation") == 1
    assert state["completed_stages"].count("analysis") == 1


def test_planning_check_validation_accepts_existing_or_planned_scripts(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    repo = tmp_path / "repo"
    (repo / "checks").mkdir(parents=True)
    (repo / "checks" / "existing.py").write_text("assert True\n", encoding="utf-8")

    existing_plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "# Plan",
            "files_to_modify": ["src/main.py"],
            "files_to_create": [],
            "files_to_delete": [],
            "file_change_policy": {
                "src/main.py": {
                    "expected_change_summary": "Change behavior",
                    "max_changed_lines": 4,
                    "max_hunks": 1,
                }
            },
            "test_commands": [["python3", "checks/existing.py"]],
            "documentation_impact": "none",
            "risks": [],
            "assumptions": [],
            "commit_message": "Change behavior",
        }
    )
    _validate_planned_check_commands(
        contract=contract,
        plan=existing_plan,
        repository_root=repo,
    )

    planned_plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "# Plan",
            "files_to_modify": ["src/main.py"],
            "files_to_create": ["tests/test_task.py"],
            "files_to_delete": [],
            "file_change_policy": {
                "src/main.py": {
                    "expected_change_summary": "Change behavior",
                    "max_changed_lines": 4,
                    "max_hunks": 1,
                },
                "tests/test_task.py": {
                    "expected_change_summary": "Add direct focused check",
                    "max_changed_lines": 12,
                    "max_hunks": 1,
                },
            },
            "test_commands": [["python3", "tests/test_task.py"]],
            "documentation_impact": "none",
            "risks": [],
            "assumptions": [],
            "commit_message": "Change behavior",
        }
    )
    _validate_planned_check_commands(
        contract=contract,
        plan=planned_plan,
        repository_root=repo,
    )


def test_operator_file_constraint_validation_rejects_contradictory_plan() -> None:
    contract = load_contract()
    plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "# Plan",
            "files_to_modify": ["README.md"],
            "files_to_create": ["tests/verify_readme_section.py"],
            "files_to_delete": [],
            "file_change_policy": {
                "README.md": {
                    "expected_change_summary": "Add the requested README section.",
                    "max_changed_lines": 12,
                    "max_hunks": 1,
                },
                "tests/verify_readme_section.py": {
                    "expected_change_summary": "Add a focused README verification script.",
                    "max_changed_lines": 20,
                    "max_hunks": 1,
                },
            },
            "test_commands": [["python3", "tests/verify_readme_section.py"]],
            "documentation_impact": "README only.",
            "risks": [],
            "assumptions": [],
            "commit_message": "Document the requested behavior",
        }
    )

    with pytest.raises(
        Exception,
        match="implementation plan contradicts explicit operator file constraints",
    ) as error:
        _validate_plan_against_operator_constraints(
            contract=contract,
            task="README only. No new files. Do not add check scripts.",
            plan=plan,
        )

    message = str(error.value)
    assert "paths outside explicit only-scope ['README.md']" in message
    assert "new files were forbidden" in message
    assert "check-script changes were forbidden" in message



def test_readme_only_plan_allows_no_repository_check_command() -> None:
    contract = load_contract()
    plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "# Plan",
            "files_to_modify": ["README.md"],
            "files_to_create": [],
            "files_to_delete": [],
            "file_change_policy": {
                "README.md": {
                    "expected_change_summary": "Add the requested README section.",
                    "max_changed_lines": 12,
                    "max_hunks": 1,
                }
            },
            "test_commands": [],
            "documentation_impact": "README only.",
            "risks": [],
            "assumptions": [],
            "commit_message": "Document development setup verification",
        }
    )

    _validate_plan_against_operator_constraints(
        contract=contract,
        task=(
            "Update only README.md. Do not create, modify, or delete any other file. "
            "Do not add check scripts."
        ),
        plan=plan,
    )
    _validate_planned_check_commands(
        contract=contract,
        plan=plan,
        repository_root=Path("."),
    )


def test_no_declared_checks_pass_without_tool_invocation(tmp_path: Path) -> None:
    contract = load_contract()
    plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "# Plan",
            "files_to_modify": ["README.md"],
            "files_to_create": [],
            "files_to_delete": [],
            "file_change_policy": {
                "README.md": {
                    "expected_change_summary": "Add the requested README section.",
                    "max_changed_lines": 12,
                    "max_hunks": 1,
                }
            },
            "test_commands": [],
            "documentation_impact": "README only.",
            "risks": [],
            "assumptions": [],
            "commit_message": "Document development setup verification",
        }
    )
    applied = ImplementationApplyResult(
        proposal_id="patch_proposal_test",
        patch_sha256="a" * 64,
        authorization_source="developer_pipeline_plan",
        changed_files=[
            {
                "path": "README.md",
                "operation": "modified",
                "after_sha256": "b" * 64,
            }
        ],
        evidence_ref="evidence/apply.json",
        plan_budget_result={"status": "passed"},
    )

    def unexpected_tool(*args, **kwargs):
        raise AssertionError("no check tool call is expected")

    result = _run_declared_checks(
        contract=contract,
        store=DeveloperPipelineStore(
            safeplane_home=tmp_path,
            run_id="run_no_checks",
            fake_scenario="default",
        ),
        plan=plan,
        implementation_apply=applied,
        call_stage_tool=unexpected_tool,
    )

    assert result.status == "passed"
    assert result.command_results == []
    assert result.summary == (
        "No repository checks were declared; deterministic scope, patch, and review "
        "validation remain in force."
    )

def test_operator_file_constraint_validation_allows_existing_check_command() -> None:
    contract = load_contract()
    plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "# Plan",
            "files_to_modify": ["README.md"],
            "files_to_create": [],
            "files_to_delete": [],
            "file_change_policy": {
                "README.md": {
                    "expected_change_summary": "Add the requested README section.",
                    "max_changed_lines": 12,
                    "max_hunks": 1,
                }
            },
            "test_commands": [["python3", "checks/check_readme.py"]],
            "documentation_impact": "README only.",
            "risks": [],
            "assumptions": [],
            "commit_message": "Document the requested behavior",
        }
    )

    _validate_plan_against_operator_constraints(
        contract=contract,
        task="Only modify README.md. Do not add new files. No check scripts.",
        plan=plan,
    )


def test_planning_check_validation_rejects_ungrounded_placeholder(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    repo = tmp_path / "repo"
    repo.mkdir()
    plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "# Plan",
            "files_to_modify": ["src/main.py"],
            "files_to_create": [],
            "files_to_delete": [],
            "file_change_policy": {
                "src/main.py": {
                    "expected_change_summary": "Change behavior",
                    "max_changed_lines": 4,
                    "max_hunks": 1,
                }
            },
            "test_commands": [["python3", "checks/check_task.py"]],
            "documentation_impact": "none",
            "risks": [],
            "assumptions": [],
            "commit_message": "Change behavior",
        }
    )

    with pytest.raises(
        developer_pipeline_module.DeveloperPipelineError,
        match="must already exist as a regular repository file",
    ):
        _validate_planned_check_commands(
            contract=contract,
            plan=plan,
            repository_root=repo,
        )


def test_planning_retries_invalid_check_command_with_deterministic_feedback(
    tmp_path: Path,
) -> None:
    result, state, calls, traces, _ = run_pipeline(
        tmp_path,
        run_id="run_planning_check_retry",
        message=(
            "[safeplane-fake-scenario:planning_check_command_retry] "
            "Implement the bounded fixture greeting task"
        ),
    )

    assert result.current_state == "waiting_for_remote_approval"
    planning_calls = [item for item in calls if item["stage_id"] == "planning"]
    assert len(planning_calls) == 2
    repair_messages = planning_calls[1]["messages"]
    assert repair_messages[-2]["role"] == "assistant"
    assert repair_messages[-1]["role"] == "user"
    assert "checks/check_task.py" in repair_messages[-1]["content"]
    assert "must already exist as a regular repository file" in repair_messages[-1]["content"]
    planning_run = next(
        item for item in state["agent_runs"] if item["stage_id"] == "planning"
    )
    assert planning_run["retry_count"] == 1
    assert planning_run["model_call_count"] == 2
    failed = [
        item
        for item in traces
        if item["event"] == "developer_pipeline_stage_attempt_failed"
        and item["input"]["stage_id"] == "planning"
    ]
    assert len(failed) == 1


def test_controlled_check_failure_is_recorded_and_uses_no_agent_identity(tmp_path: Path) -> None:
    contract = load_contract()
    plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "# Plan",
            "files_to_modify": ["src/greeter.py"],
            "files_to_create": [],
            "files_to_delete": [],
            "file_change_policy": {
                "src/greeter.py": {
                    "expected_change_summary": "change greeting",
                    "max_changed_lines": 4,
                    "max_hunks": 1,
                }
            },
            "test_commands": [["python3", "checks/check_greeting.py"]],
            "documentation_impact": "none",
            "risks": [],
            "assumptions": [],
            "commit_message": "Adjust greeting",
        }
    )
    applied = ImplementationApplyResult(
        proposal_id="patch_proposal_test",
        patch_sha256="a" * 64,
        authorization_source="developer_pipeline_plan",
        changed_files=[
            {
                "path": "src/greeter.py",
                "operation": "modified",
                "after_sha256": "b" * 64,
            }
        ],
        evidence_ref="evidence/apply.json",
        plan_budget_result={"status": "passed"},
    )
    calls: list[dict] = []

    def tool(stage_id, agent_id, server_id, tool_name, arguments, approval_id, approval_token):
        calls.append(
            {
                "stage_id": stage_id,
                "agent_id": agent_id,
                "server_id": server_id,
                "tool_name": tool_name,
                "arguments": arguments,
            }
        )
        return {
            "profile_id": "python_check",
            "status": "failed",
            "exit_code": 7,
            "duration_ms": 5,
            "stdout_ref": "evidence/stdout.txt",
            "stderr_ref": "evidence/stderr.txt",
            "evidence_ref": "evidence/check.json",
            "network_policy": "disabled",
        }

    store = DeveloperPipelineStore(
        safeplane_home=tmp_path,
        run_id="run_checks",
        fake_scenario="default",
    )
    result = _run_declared_checks(
        contract=contract,
        store=store,
        plan=plan,
        implementation_apply=applied,
        call_stage_tool=tool,
    )

    assert result.status == "failed"
    assert result.command_results[0].exit_code == 7
    assert calls[0]["agent_id"] is None
    assert calls[0]["server_id"] == "dev-check"
    assert calls[0]["arguments"]["expected_files"] == {
        "src/greeter.py": "b" * 64
    }


def test_published_implementation_approval_stays_applied_when_consumer_visibility_fails(
    tmp_path: Path, monkeypatch
) -> None:
    plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "# Plan",
            "files_to_modify": ["src/greeter.py"],
            "files_to_create": [],
            "files_to_delete": [],
            "file_change_policy": {
                "src/greeter.py": {
                    "expected_change_summary": "change greeting",
                    "max_changed_lines": 4,
                    "max_hunks": 1,
                }
            },
            "test_commands": [["python3", "checks/check_greeting.py"]],
            "documentation_impact": "none",
            "risks": [],
            "assumptions": [],
            "commit_message": "Adjust greeting",
        }
    )
    patch = ImplementationPatch.model_validate(
        {
            "implementation_summary_markdown": "# Implementation",
            "unified_diff": (
                "diff --git a/src/greeter.py b/src/greeter.py\n"
                "--- a/src/greeter.py\n"
                "+++ b/src/greeter.py\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            ),
            "changed_files": ["src/greeter.py"],
        }
    )
    approval_updates: list[dict] = []
    cleanup_calls: list[str] = []

    monkeypatch.setattr(
        developer_pipeline_module,
        "load_run",
        lambda *_args, **_kwargs: {"run_id": "run_tx"},
    )
    monkeypatch.setattr(
        developer_pipeline_module,
        "create_patch_approval",
        lambda *_args, **_kwargs: ({"approval_id": "approval_tx"}, "token_tx"),
    )

    def update_approval(_home, approval, **fields):
        approval_updates.append(dict(fields))
        return {**approval, **fields}

    monkeypatch.setattr(developer_pipeline_module, "update_patch_approval", update_approval)
    monkeypatch.setattr(
        developer_pipeline_module,
        "prepare_patch_apply_workspace",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        developer_pipeline_module,
        "publish_patch_apply_workspace",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        developer_pipeline_module,
        "cleanup_patch_apply_workspace",
        lambda *_args, **_kwargs: cleanup_calls.append("cleanup"),
    )

    def tool(stage_id, agent_id, server_id, tool_name, arguments, approval_id, approval_token):
        if tool_name == "dev_workspace_propose_patch":
            return {"proposal_id": "proposal_tx", "artifact_ref": "patches/proposal.patch"}
        if tool_name == "dev_workspace_apply_patch":
            return {
                "proposal_id": "proposal_tx",
                "patch_sha256": arguments["patch_sha256"],
                "changed_files": [
                    {
                        "path": "src/greeter.py",
                        "operation": "modified",
                        "after_sha256": "b" * 64,
                    }
                ],
                "plan_budget_result": {"status": "passed"},
                "evidence_ref": "evidence/apply.json",
            }
        if tool_name == "dev_workspace_ready":
            raise RuntimeError("consumer did not observe the published tree")
        raise AssertionError(tool_name)

    with pytest.raises(RuntimeError, match="consumer did not observe"):
        developer_pipeline_module._apply_implementation_patch(
            safeplane_home=tmp_path,
            run_id="run_tx",
            patch=patch,
            plan=plan,
            call_stage_tool=tool,
        )

    assert any(update.get("status") == "applied" for update in approval_updates)
    assert not any(update.get("status") == "failed" for update in approval_updates)
    assert cleanup_calls == []


def test_agent_run_metadata_records_usage_duration_and_gateway_configured_model(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    home = tmp_path / "home"
    run_id = "run_usage"
    repo = home / "workspaces" / run_id / "repo"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "greeter.py").write_text(
        'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
        encoding="utf-8",
    )
    (repo / "checks").mkdir()
    (repo / "checks" / "check_greeting.py").write_text(
        'from pathlib import Path\n'
        'source = Path("src/greeter.py").read_text(encoding="utf-8")\n'
        'assert "developer pipeline" in source\n',
        encoding="utf-8",
    )

    def caller(stage_id, response_key, model_profile, messages):
        profile = contract["model_profiles"][model_profile]
        response_file = fake_response_file(profile, response_key, messages)
        return StageModelCallResult(
            content=response_file.read_text(encoding="utf-8"),
            model={
                "mode": "fake",
                "configured_model": f"override/{model_profile}",
                "actual_model": f"fake/{model_profile}",
                "actual_provider": "safeplane-fake",
                "generation_id": f"generation-{stage_id}",
            },
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cost": 0.001,
            },
            finish_reason="stop",
        )

    run_developer_pipeline(
        contract=contract,
        config_path=REPO_ROOT / "safeplane.yaml",
        safeplane_home=home,
        run_id=run_id,
        operator_message="Implement the bounded fixture greeting task",
        workspace_manifest={
            "workspace_kind": "local_snapshot",
            "repository_root": str(repo),
            "read_only": True,
        },
        call_stage_model=caller,
        trace=lambda *args: None,
        call_stage_tool=compatibility_tool_caller(repo),
    )

    state = json.loads(
        (home / "workspaces" / run_id / "pipeline" / "pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["agent_runs"]
    for item in state["agent_runs"]:
        assert item["configured_model"] == f"override/{item['model_profile']}"
        assert item["generation_id"] == f"generation-{item['stage_id']}"
        assert item["finish_reason"] == "stop"
        if item["stage_id"] == "implementation":
            assert item["prompt_tokens"] == 20
            assert item["completion_tokens"] == 10
            assert item["total_tokens"] == 30
            assert item["cost"] == 0.002
            assert item["model_call_count"] == 2
            assert item["tool_call_count"] == 1
        else:
            assert item["prompt_tokens"] == 10
            assert item["completion_tokens"] == 5
            assert item["total_tokens"] == 15
            assert item["cost"] == 0.001
            assert item["model_call_count"] == 1
            assert item["tool_call_count"] == 0
        assert item["duration_ms"] >= 0


def test_implementation_agent_can_use_multiple_tools_before_final(tmp_path: Path) -> None:
    result, state, calls, traces, _ = run_pipeline(
        tmp_path,
        run_id="run_multi_tool_implementation",
        message=(
            "[safeplane-fake-scenario:implementation_multi_tool_loop] "
            "Implement the bounded fixture greeting task"
        ),
    )

    assert result.current_state == "waiting_for_remote_approval"
    implementation_calls = [
        item for item in calls if item["stage_id"] == "implementation"
    ]
    assert len(implementation_calls) == 3
    implementation_run = next(
        item for item in state["agent_runs"] if item["stage_id"] == "implementation"
    )
    assert implementation_run["model_call_count"] == 3
    assert implementation_run["tool_call_count"] == 2
    assert implementation_run["retry_count"] == 0
    completed = [
        item
        for item in traces
        if item["event"] == "developer_pipeline_implementation_tool_turn_completed"
    ]
    assert [item["input"]["tool_name"] for item in completed] == [
        "dev_workspace_grep",
        "dev_workspace_read",
    ]


def test_implementation_tool_loop_is_not_limited_by_generic_retry_count(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    plan = ImplementationPlan.model_validate(
        json.loads(
            (REPO_ROOT / "prompts/developer/fake/planning.v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    home = tmp_path / "home"
    repo = home / "workspaces" / "run_many_tools" / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "greeter.py").write_text(
        'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
        encoding="utf-8",
    )
    store = DeveloperPipelineStore(
        safeplane_home=home,
        run_id="run_many_tools",
        fake_scenario="default",
    )
    model_calls = 0
    observed_messages: list[list[dict[str, str]]] = []

    def caller(stage_id, response_key, model_profile, messages):
        nonlocal model_calls
        model_calls += 1
        observed_messages.append(messages)
        if model_calls <= 7:
            content = json.dumps(
                {
                    "type": "tool_call",
                    "server_id": "dev-workspace",
                    "tool_name": "dev_workspace_read",
                    "arguments": {
                        "path": "src/greeter.py",
                        "start_line": 1,
                        "max_lines": 200,
                        "max_bytes": 65536,
                    },
                }
            )
        else:
            content = (
                REPO_ROOT / "prompts/developer/fake/implementation-final.v2.json"
            ).read_text(encoding="utf-8")
        return StageModelCallResult(
            content=content,
            model={
                "mode": "fake",
                "configured_model": "fake/model",
                "actual_model": "fake/model",
                "actual_provider": "safeplane-fake",
            },
        )

    traces: list[dict] = []

    def trace(event, input_data, output_data, artifact_refs, error):
        traces.append(
            {
                "event": event,
                "input": input_data,
                "output": output_data,
                "artifact_refs": artifact_refs,
                "error": error,
            }
        )

    result = developer_pipeline_module._run_implementation_agent_loop(
        contract=contract,
        agent=contract["agents"]["implementation"],
        model_profile="developer_implementation",
        response_key="implementation",
        system_prompt="implementation system prompt",
        user_message="implementation task",
        plan=plan,
        repository_root=repo,
        max_attempts=3,
        tool_loop_timeout_seconds=60,
        require_repository_inspection=True,
        call_stage_model=caller,
        call_stage_tool=compatibility_tool_caller(repo),
        trace=trace,
        store=store,
    )

    assert result.model_call_count == 8
    assert result.tool_call_count == 7
    assert result.retry_count == 0
    assert model_calls == 8
    assert len(observed_messages[-1]) == 16
    assert any(
        item["event"] == "developer_pipeline_implementation_tool_loop_finished"
        for item in traces
    )


def test_implementation_candidate_check_failure_is_returned_for_repair(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    home = tmp_path / "home"
    repo = home / "workspaces" / "run_candidate_check_retry" / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "checks").mkdir(parents=True)
    (repo / "src" / "greeter.py").write_text(
        'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
        encoding="utf-8",
    )
    (repo / "checks" / "check_greeting.py").write_text(
        'from pathlib import Path\n'
        'source = Path("src/greeter.py").read_text(encoding="utf-8")\n'
        'assert "developer pipeline" in source\n',
        encoding="utf-8",
    )
    plan = ImplementationPlan.model_validate(
        json.loads(
            (REPO_ROOT / "prompts/developer/fake/planning.v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    store = DeveloperPipelineStore(
        safeplane_home=home,
        run_id="run_candidate_check_retry",
        fake_scenario="default",
    )
    model_calls = 0
    check_calls: list[dict] = []
    observed_messages: list[list[dict[str, str]]] = []

    def caller(stage_id, response_key, model_profile, messages):
        nonlocal model_calls
        model_calls += 1
        observed_messages.append(messages)
        if model_calls == 1:
            content = (
                REPO_ROOT / "prompts/developer/fake/implementation-tool-read.v2.json"
            ).read_text(encoding="utf-8")
        elif model_calls == 2:
            content = json.dumps(
                {
                    "type": "final",
                    "implementation_summary_markdown": "# Implementation Summary\n\nBroken candidate.",
                    "replacements": [
                        {
                            "path": "src/greeter.py",
                            "old_text": '    return f"Hello, {name}!"',
                            "new_text": '    return f"Hello from a broken candidate, {name}!"',
                        }
                    ],
                    "changed_files": ["src/greeter.py"],
                }
            )
        else:
            content = (
                REPO_ROOT / "prompts/developer/fake/implementation-final.v2.json"
            ).read_text(encoding="utf-8")
        return StageModelCallResult(
            content=content,
            model={
                "mode": "fake",
                "configured_model": "fake/model",
                "actual_model": "fake/model",
                "actual_provider": "safeplane-fake",
            },
        )

    def tool(stage_id, agent_id, server_id, tool_name, arguments, approval_id, approval_token):
        if tool_name == "dev_workspace_read":
            return compatibility_tool_caller(repo)(
                stage_id,
                agent_id,
                server_id,
                tool_name,
                arguments,
                approval_id,
                approval_token,
            )
        assert stage_id == "implementation_candidate_checks"
        assert agent_id is None
        assert server_id == "dev-check"
        assert tool_name == "dev_check_run"
        check_calls.append(arguments)
        patch = arguments["candidate_patch"]
        if "broken candidate" in patch:
            return {
                "status": "failed",
                "exit_code": 1,
                "duration_ms": 5,
                "stdout": "",
                "stderr": "AssertionError: developer pipeline greeting missing",
                "candidate_patch_applied": True,
            }
        return {
            "status": "passed",
            "exit_code": 0,
            "duration_ms": 5,
            "stdout": "PASS\n",
            "stderr": "",
            "candidate_patch_applied": True,
        }

    traces: list[dict] = []

    def trace(event, input_data, output_data, artifact_refs, error):
        traces.append(
            {
                "event": event,
                "input": input_data,
                "output": output_data,
                "artifact_refs": artifact_refs,
                "error": error,
            }
        )

    result = developer_pipeline_module._run_implementation_agent_loop(
        contract=contract,
        agent=contract["agents"]["implementation"],
        model_profile="developer_implementation",
        response_key="implementation",
        system_prompt="implementation system prompt",
        user_message="implementation task",
        plan=plan,
        repository_root=repo,
        max_attempts=3,
        tool_loop_timeout_seconds=60,
        require_repository_inspection=True,
        call_stage_model=caller,
        call_stage_tool=tool,
        trace=trace,
        store=store,
    )

    assert result.retry_count == 1
    assert result.model_call_count == 3
    assert result.tool_call_count == 1
    assert len(check_calls) == 2
    assert all(call["candidate_patch"] for call in check_calls)
    repair_messages = "\n".join(
        message["content"]
        for turn in observed_messages
        for message in turn
        if message.get("role") == "user"
    )
    assert "candidate implementation failed a declared check" in repair_messages
    assert "AssertionError: developer pipeline greeting missing" in repair_messages
    assert any(
        item["event"] == "developer_pipeline_implementation_candidate_checks_passed"
        for item in traces
    )


def test_implementation_import_failure_repair_guidance_prefers_source_inspection(
) -> None:
    plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "Remove one static entry.",
            "files_to_modify": ["settings.py"],
            "files_to_create": ["tests/test_settings.py"],
            "files_to_delete": [],
            "file_change_policy": {
                "settings.py": {
                    "expected_change_summary": "Remove one deprecated entry.",
                    "max_changed_lines": 6,
                    "max_hunks": 1,
                },
                "tests/test_settings.py": {
                    "expected_change_summary": "Verify the deprecated entry is excluded.",
                    "max_changed_lines": 15,
                    "max_hunks": 1,
                },
            },
            "test_commands": [["python3", "tests/test_settings.py"]],
            "documentation_impact": "none",
            "risks": [],
            "assumptions": [],
            "commit_message": "Remove deprecated configuration entry",
        }
    )
    error = developer_pipeline_module.DeveloperPipelineError(
        "candidate implementation failed a declared check before final acceptance; "
        "argv=[\"python3\", \"tests/test_settings.py\"]; "
        "stderr: ModuleNotFoundError: No module named 'settings'"
    )

    message = developer_pipeline_module._implementation_repair_message(
        error,
        plan=plan,
    )

    assert "Do not repair this only by changing `sys.path`" in message
    assert "importlib.util.spec_from_file_location" in message
    assert "`ast.parse` without importing or executing" in message
    assert '["settings.py"]' in message


def test_implementation_tool_loop_rejects_non_inspection_tool() -> None:
    contract = load_contract()
    call = developer_pipeline_module.ImplementationToolCall.model_validate(
        {
            "type": "tool_call",
            "server_id": "dev-workspace",
            "tool_name": "dev_workspace_propose_patch",
            "arguments": {
                "summary": "proposal",
                "patch": "diff --git a/a b/a\n--- a/a\n+++ b/a\n",
            },
        }
    )

    with pytest.raises(
        developer_pipeline_module.DeveloperPipelineError,
        match="read-only repository inspection only",
    ):
        developer_pipeline_module._validate_implementation_tool_call(
            call,
            agent=contract["agents"]["implementation"],
        )


def test_implementation_budget_repair_guidance_compacts_created_python_check() -> None:
    plan = ImplementationPlan.model_validate(
        {
            "developer_plan_markdown": "Remove one static entry.",
            "files_to_modify": ["settings.py"],
            "files_to_create": ["tests/test_settings_excludes_deprecated.py"],
            "files_to_delete": [],
            "file_change_policy": {
                "settings.py": {
                    "expected_change_summary": "Remove the deprecated entry.",
                    "max_changed_lines": 5,
                    "max_hunks": 1,
                },
                "tests/test_settings_excludes_deprecated.py": {
                    "expected_change_summary": "Inspect ITEMS with AST.",
                    "max_changed_lines": 70,
                    "max_hunks": 1,
                },
            },
            "test_commands": [
                ["python3", "tests/test_settings_excludes_deprecated.py"]
            ],
            "documentation_impact": "none",
            "risks": [],
            "assumptions": [],
            "commit_message": "Remove deprecated configuration entry",
        }
    )
    error = developer_pipeline_module.DeveloperPipelineError(
        "implementation exceeds approved plan budget: changed-line budget "
        "exceeded for tests/test_settings_excludes_deprecated.py: 80 > 70"
    )

    message = developer_pipeline_module._implementation_repair_message(
        error,
        plan=plan,
    )

    assert "with 80 changed lines" in message
    assert "at most 70 physical lines" in message
    assert "Count the complete `new_text`" in message
    assert "Remove shebangs" in message
    assert "`ast.literal_eval`" in message
    assert "Do not weaken the assertion" in message


def test_implementation_fourth_attempt_handles_check_then_budget_repairs(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    home = tmp_path / "home"
    repo = home / "workspaces" / "run_chained_retry" / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "checks").mkdir(parents=True)
    (repo / "src" / "greeter.py").write_text(
        'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
        encoding="utf-8",
    )
    (repo / "checks" / "check_greeting.py").write_text(
        'from pathlib import Path\n'
        'source = Path("src/greeter.py").read_text(encoding="utf-8")\n'
        'assert "developer pipeline" in source\n',
        encoding="utf-8",
    )
    plan = ImplementationPlan.model_validate(
        json.loads(
            (REPO_ROOT / "prompts/developer/fake/planning.v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    store = DeveloperPipelineStore(
        safeplane_home=home,
        run_id="run_chained_retry",
        fake_scenario="default",
    )
    response_paths = [
        "prompts/developer/fake/implementation-tool-read.v2.json",
        "prompts/developer/fake/implementation-final-check-fails.v2.json",
        "prompts/developer/fake/implementation-final-over-budget.v2.json",
        "prompts/developer/fake/implementation-final-over-budget.v2.json",
        "prompts/developer/fake/implementation-final.v2.json",
    ]
    model_calls = 0
    check_calls: list[dict] = []
    observed_messages: list[list[dict[str, str]]] = []

    def caller(stage_id, response_key, model_profile, messages):
        nonlocal model_calls
        observed_messages.append(messages)
        content = (REPO_ROOT / response_paths[model_calls]).read_text(
            encoding="utf-8"
        )
        model_calls += 1
        return StageModelCallResult(
            content=content,
            model={
                "mode": "fake",
                "configured_model": "fake/model",
                "actual_model": "fake/model",
                "actual_provider": "safeplane-fake",
            },
        )

    def tool(stage_id, agent_id, server_id, tool_name, arguments, approval_id, approval_token):
        if tool_name == "dev_workspace_read":
            return compatibility_tool_caller(repo)(
                stage_id,
                agent_id,
                server_id,
                tool_name,
                arguments,
                approval_id,
                approval_token,
            )
        check_calls.append(arguments)
        if "broken candidate" in arguments["candidate_patch"]:
            return {
                "status": "failed",
                "exit_code": 1,
                "duration_ms": 5,
                "stdout": "",
                "stderr": "AssertionError: developer pipeline greeting missing",
                "candidate_patch_applied": True,
            }
        return {
            "status": "passed",
            "exit_code": 0,
            "duration_ms": 5,
            "stdout": "PASS\n",
            "stderr": "",
            "candidate_patch_applied": True,
        }

    result = developer_pipeline_module._run_implementation_agent_loop(
        contract=contract,
        agent=contract["agents"]["implementation"],
        model_profile="developer_implementation",
        response_key="implementation",
        system_prompt="implementation system prompt",
        user_message="implementation task",
        plan=plan,
        repository_root=repo,
        max_attempts=4,
        tool_loop_timeout_seconds=60,
        require_repository_inspection=True,
        call_stage_model=caller,
        call_stage_tool=tool,
        trace=lambda *args: None,
        store=store,
    )

    assert result.retry_count == 3
    assert result.model_call_count == 5
    assert result.tool_call_count == 1
    assert len(check_calls) == 2
    repair_messages = "\n".join(
        message["content"]
        for turn in observed_messages
        for message in turn
        if message.get("role") == "user"
    )
    assert "candidate implementation failed a declared check" in repair_messages
    assert "changed-line budget exceeded for src/greeter.py: 5 > 4" in repair_messages

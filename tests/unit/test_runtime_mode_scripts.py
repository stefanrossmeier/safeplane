from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("script_name", "expected_files"),
    [
        (
            "compose-safeplane-fake",
            ["docker-compose.yml", "docker-compose.local.yml"],
        ),
        (
            "compose-safeplane-real",
            [
                "docker-compose.yml",
                "docker-compose.local.yml",
                "docker-compose.real.yml",
            ],
        ),
        (
            "compose-safeplane-telegram-fake",
            ["docker-compose.yml", "docker-compose.telegram.yml"],
        ),
        (
            "compose-safeplane-telegram-real",
            [
                "docker-compose.yml",
                "docker-compose.real.yml",
                "docker-compose.telegram.yml",
            ],
        ),
        (
            "compose-safeplane-developer-fake",
            [
                "docker-compose.yml",
                "docker-compose.local.yml",
                "docker-compose.developer.yml",
            ],
        ),
        (
            "compose-safeplane-developer-real",
            [
                "docker-compose.yml",
                "docker-compose.local.yml",
                "docker-compose.real.yml",
                "docker-compose.developer.yml",
            ],
        ),
        (
            "compose-safeplane-developer-github-fake",
            [
                "docker-compose.yml",
                "docker-compose.local.yml",
                "docker-compose.developer.yml",
                "docker-compose.github.yml",
            ],
        ),
        (
            "compose-safeplane-developer-github-real",
            [
                "docker-compose.yml",
                "docker-compose.local.yml",
                "docker-compose.real.yml",
                "docker-compose.developer.yml",
                "docker-compose.github.yml",
            ],
        ),
        (
            "compose-safeplane-developer-github-mock",
            [
                "docker-compose.yml",
                "docker-compose.local.yml",
                "docker-compose.developer.yml",
                "docker-compose.github.yml",
                "docker-compose.github-mock.yml",
            ],
        ),
    ],
)
def test_compose_mode_wrapper_uses_expected_overlays(
    tmp_path: Path,
    script_name: str,
    expected_files: list[str],
) -> None:
    capture_path = tmp_path / "docker-args.txt"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$SAFEPLANE_TEST_DOCKER_ARGS\"\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    env["SAFEPLANE_TEST_DOCKER_ARGS"] = str(capture_path)

    subprocess.run(
        [str(REPO_ROOT / "tests/scripts" / script_name), "ps"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )

    arguments = capture_path.read_text(encoding="utf-8").splitlines()
    assert arguments[0] == "compose"
    assert arguments[-1] == "ps"

    selected_files = [
        arguments[index + 1]
        for index, argument in enumerate(arguments[:-1])
        if argument == "-f"
    ]
    assert selected_files == expected_files


def test_status_script_checks_mode_and_secret_without_printing_secret() -> None:
    script = (REPO_ROOT / "tests/scripts/status-safeplane-mode").read_text(
        encoding="utf-8"
    )

    assert "MODEL_GATEWAY_MODE" in script
    assert "SAFEPLANE_NOTIFICATION_CONNECTORS" in script
    assert "telegram-connector" in script
    assert "calendar-task-mcp" in script
    assert "notification-task-mcp" in script
    assert "dev-workspace-mcp" in script
    assert "compose-safeplane-developer-fake" in script
    assert "compose-safeplane-developer-real" in script
    assert "test -s /run/secrets/openrouter_api_key" in script
    assert "test -s /run/secrets/github_token" in script
    assert "cat /run/secrets/openrouter_api_key" not in script
    assert "cat /run/secrets/github_token" not in script


def test_real_assistant_telegram_smoke_is_manual_and_checks_full_path() -> None:
    script_path = REPO_ROOT / "tests/scripts/validate-real-assistant-telegram-reminder"
    script = script_path.read_text(encoding="utf-8")

    assert os.access(script_path, os.X_OK)
    assert "SAFEPLANE_CONFIRM_REAL_TELEGRAM_SMOKE" in script
    assert "compose-safeplane-telegram-real" in script
    assert "HarnessClient" in script
    assert "model_tool_invocation_validated" in script
    assert "notification_schedule" in script
    assert "telegram_connector_delivered" in script
    assert "notification_delivery_succeeded" in script
    assert "outbound_notification_sent" in script
    assert "telegram-connector python -u -" in script
    assert "SAFEPLANE_NOTIFICATION_CONNECTORS" in script
    assert "existing_schedule_ids" in script
    assert "matching_new_schedules" in script
    assert 'record.get("message") == marker' not in script

    result = subprocess.run(
        [str(script_path)],
        cwd=REPO_ROOT,
        env={
            key: value
            for key, value in os.environ.items()
            if key != "SAFEPLANE_CONFIRM_REAL_TELEGRAM_SMOKE"
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "manual real-mode smoke test" in result.stderr



def test_external_developer_capability_fixtures_match_default_fake_pipeline() -> None:
    smoke_paths = [
        REPO_ROOT / "tests/scripts/docker-smoke-external-repositories",
        REPO_ROOT / "tests/scripts/docker-smoke-developer-tools",
        REPO_ROOT / "tests/scripts/docker-smoke-documentation-agent",
    ]

    for smoke_path in smoke_paths:
        smoke = smoke_path.read_text(encoding="utf-8")
        assert '"$work/src/greeter.py"' in smoke
        assert '"$work/checks/check_greeting.py"' in smoke
        assert 'return f"Hello, {name}!"' in smoke
        assert 'Hello from the developer pipeline' in smoke

    for smoke_path in smoke_paths[:2]:
        smoke = smoke_path.read_text(encoding="utf-8")
        assert "Developer run returned HTTP $http_status" in smoke
        assert 'curl -sS -o "$response_file" -w \'%{http_code}\'' in smoke

    developer_tools_smoke = smoke_paths[1].read_text(encoding="utf-8")
    assert 'assert status["clean"] is False, status' in developer_tools_smoke
    assert '"src/greeter.py": (" ", "M")' in developer_tools_smoke
    for path in [
        "docs/API_SURFACE.md",
        "docs/ARCHITECTURE.md",
        "docs/OPERATIONS.md",
        "docs/REPO_MAP.md",
    ]:
        assert f'"{path}": ("?", "?")' in developer_tools_smoke

def test_external_documentation_validation_is_executable_and_fixture_only() -> None:
    validate_path = REPO_ROOT / "tests/scripts/accept-external-documentation"
    smoke_path = REPO_ROOT / "tests/scripts/docker-smoke-documentation-agent"
    validate = validate_path.read_text(encoding="utf-8")
    smoke = smoke_path.read_text(encoding="utf-8")
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert os.access(validate_path, os.X_OK)
    assert os.access(smoke_path, os.X_OK)
    assert "docker-smoke-documentation-agent" in validate
    assert "file:///data/safeplane/git-fixtures" in smoke
    assert "SAFEPLANE_ARCHDOC_REPOSITORY_URL" in smoke
    assert "External archdoc fixture v1" in smoke
    assert "external skill content supplied at runtime; not persisted" in smoke
    assert '"$COMPOSE" exec -T harness python3 - "/data/safeplane"' in smoke
    assert 'python3 - "$SAFEPLANE_HOME"' not in smoke
    assert "Developer run returned HTTP $http_status" in smoke
    assert "curl -sS -o \"$response_file\" -w '%{http_code}'" in smoke
    assert "github.com" not in smoke
    assert "accept-external-documentation:" in makefile


def test_developer_workflow_validation_is_executable_and_proves_single_pass_stop_paths() -> None:
    validate_path = REPO_ROOT / "tests/scripts/accept-developer-workflow"
    smoke_path = REPO_ROOT / "tests/scripts/docker-smoke-single-pass-developer"
    validate = validate_path.read_text(encoding="utf-8")
    smoke = smoke_path.read_text(encoding="utf-8")
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert os.access(validate_path, os.X_OK)
    assert os.access(smoke_path, os.X_OK)
    assert "docker-smoke-single-pass-developer" in validate
    assert "waiting_for_remote_approval" in smoke
    assert "review_changes_requested" in smoke
    assert "intentional controlled check failure" in smoke
    assert 'assert len(failed)==4, failed' in smoke
    assert 'assert [row["data"]["attempt"] for row in failed]==[1,2,3,4], failed' in smoke
    assert 'assert len(failed)==3, failed' in smoke
    assert "dev-check-mcp" in smoke
    assert '"$COMPOSE" up -d --build' in smoke
    assert "wait_health" in smoke
    assert smoke.index('"$COMPOSE" up -d --build') < smoke.index('response="$(post_run')
    assert smoke.index("wait_health") < smoke.index('response="$(post_run')
    assert "Source fixture remotes remained unchanged" in smoke
    assert "github.com" not in smoke
    assert "accept-developer-workflow:" in makefile


def test_cli_status_exposes_single_pass_pipeline_evidence() -> None:
    rendering = (
        REPO_ROOT / "connectors/cli/src/safeplane_cli/rendering.py"
    ).read_text(encoding="utf-8")
    assert "pipeline state:" in rendering
    assert "completed stages:" in rendering
    assert "checks:" in rendering
    assert "review:" in rendering
    assert "remote approval:" in rendering
    assert "models:" in rendering


def test_draft_pr_validation_is_executable_and_proves_remote_write_boundaries() -> None:
    validate_path = REPO_ROOT / "tests/scripts/accept-draft-pr-workflow"
    smoke_path = REPO_ROOT / "tests/scripts/docker-smoke-remote-draft-pr"
    validate = validate_path.read_text(encoding="utf-8")
    smoke = smoke_path.read_text(encoding="utf-8")
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert os.access(validate_path, os.X_OK)
    assert os.access(smoke_path, os.X_OK)
    assert "docker-smoke-remote-draft-pr" in validate
    assert "compose-safeplane-developer-github-mock" in smoke
    assert "/runs/${run_id}/remote/approve" in smoke
    assert "remote-approval-request.json" in smoke
    assert "Duplicate approval reused one branch and one draft pull request" in smoke
    assert "REQUEST_CHANGES blocked remote approval" in smoke
    assert "Failed checks blocked remote approval" in smoke
    assert "Changed workspace blocked remote approval" in smoke
    assert "Incompatible moved base blocked remote approval" in smoke
    assert "GitHub credential is mounted only into the harness" in smoke
    assert "Writable publication remotes exist only in the harness-owned test volume" in smoke
    assert "file:///data/safeplane/publication-remotes/target-success.git" in smoke
    assert "remote_git target-success" in smoke
    assert 'output="$(remote_git "$remote_name" show-ref --verify --quiet "refs/heads/$branch" 2>&1)"' in smoke
    assert 'if [[ "$status" -ne 1 ]]; then' in smoke
    assert "Unable to verify remote branch absence" in smoke
    assert "file:///data/safeplane/git-fixtures/skills.git" in smoke
    assert "does not merge" in smoke
    assert "force" not in " ".join(
        line.strip() for line in smoke.splitlines() if "git -C" in line and "push" in line
    )
    assert "accept-draft-pr-workflow:" in makefile


def test_cli_exposes_remote_approval_and_draft_pr_status() -> None:
    launcher = (REPO_ROOT / "scripts/safeplane").read_text(encoding="utf-8")
    cli = (REPO_ROOT / "connectors/cli/src/safeplane_cli/main.py").read_text(encoding="utf-8")
    client = (REPO_ROOT / "connectors/common/src/safeplane_connector/client.py").read_text(encoding="utf-8")
    rendering = (REPO_ROOT / "connectors/cli/src/safeplane_cli/rendering.py").read_text(encoding="utf-8")
    assert "safeplane approve-pr <run-id>" in launcher
    assert "/remote/approve" in client
    assert 'connector_name="cli"' in cli
    assert "planned branch:" in rendering
    assert "approved workspace:" in rendering
    assert "remote branch:" in rendering
    assert "draft PR:" in rendering


def test_real_draft_pr_github_draft_pr_smoke_is_guarded_and_dedicated() -> None:
    script_path = REPO_ROOT / "tests/scripts/validate-real-draft-pr"
    script = script_path.read_text(encoding="utf-8")
    assert os.access(script_path, os.X_OK)
    assert "SAFEPLANE_CONFIRM_REAL_GITHUB_DRAFT_PR" in script
    assert "SAFEPLANE_DRAFT_PR_RUN_ID" in script
    assert "SAFEPLANE_DRAFT_PR_EXPECTED_REPOSITORY" in script
    assert "dedicated test repository" in script
    assert "compose-safeplane-developer-github-fake" in script
    assert "/remote/approve" in script
    assert "must be outside SAFEPLANE_HOME" in script
    assert "waiting_for_remote_approval','completed" in script
    assert "Draft PR reused:" in script
    assert "pull_request_number" in script
    assert "draft" in script
    assert "did not merge" in script
    result = subprocess.run(
        [str(script_path)],
        cwd=REPO_ROOT,
        env={
            key: value
            for key, value in os.environ.items()
            if key != "SAFEPLANE_CONFIRM_REAL_GITHUB_DRAFT_PR"
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "guarded manual" in result.stderr


def test_draft_pr_documentation_describes_approval_and_external_github_secret() -> None:
    remote_write = (REPO_ROOT / "docs/remote-write.md").read_text(encoding="utf-8")
    secrets = (REPO_ROOT / "docs/security/secrets.md").read_text(encoding="utf-8")
    repository = (REPO_ROOT / "docs/repository-workspaces.md").read_text(encoding="utf-8")
    pipeline = (REPO_ROOT / "docs/developer-pipeline.md").read_text(encoding="utf-8")
    telegram = (REPO_ROOT / "docs/connectors/telegram.md").read_text(encoding="utf-8")
    secret_helper = (REPO_ROOT / "scripts/safeplane-secret").read_text(encoding="utf-8")
    github_compose = (REPO_ROOT / "docker-compose.github.yml").read_text(encoding="utf-8")

    assert "approve-pr" in remote_write
    assert "remote-approval-request.json" in remote_write
    assert "without force" in remote_write
    assert "does not merge" in remote_write
    assert "validate-real-draft-pr" in remote_write
    assert "~/.config/safeplane/secrets/github_token" in secrets
    assert "remote_write_allowed: true" in repository
    assert "explicit operator approval" in pipeline
    assert "/approve_pr [run-id]" in telegram
    assert 'SAFEPLANE_SECRET_ROOT' in secret_helper
    assert '.config" / "safeplane" / "secrets"' in secret_helper
    assert "SAFEPLANE_HOME" not in github_compose.split("file:", 1)[1]


def test_real_compose_passes_independent_developer_model_overrides() -> None:
    compose = (REPO_ROOT / "docker-compose.real.yml").read_text(encoding="utf-8")
    for profile in (
        "DEVELOPER_DOCUMENTATION",
        "DEVELOPER_ANALYSIS",
        "DEVELOPER_PLANNING",
        "DEVELOPER_IMPLEMENTATION",
        "DEVELOPER_REVIEW",
        "DEVELOPER_PR",
    ):
        assert f"SAFEPLANE_MODEL_PROFILE_{profile}" in compose


def test_real_external_repository_acceptance_is_guarded_and_two_step() -> None:
    script_path = REPO_ROOT / "tests/scripts/validate-real-external-repository"
    script = script_path.read_text(encoding="utf-8")
    assert os.access(script_path, os.X_OK)
    assert "SAFEPLANE_CONFIRM_REAL_EXTERNAL_REPOSITORY" in script
    assert "SAFEPLANE_REAL_REPOSITORY_TASK" in script
    assert "prepare)" in script
    assert "approve|record" in script
    assert "waiting_for_remote_approval" in script
    assert "/connector/develop/start" in script
    assert "SAFEPLANE_REAL_REPOSITORY_RUN_TIMEOUT_SECONDS" in script
    assert "wait_for_terminal_run" in script
    assert "/remote/approve" in script
    assert "compose-safeplane-developer-github-real" in script
    assert "model_mode') == 'real'" in script
    assert "Safeplane source checkout remained unchanged" in script
    assert "GitHub credential is absent" in script
    assert "safeplane case-study" in script
    assert "did not merge" in script

    result = subprocess.run(
        [str(script_path), "prepare"],
        cwd=REPO_ROOT,
        env={
            key: value
            for key, value in os.environ.items()
            if key != "SAFEPLANE_CONFIRM_REAL_EXTERNAL_REPOSITORY"
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "guarded manual real external-repository" in result.stderr


def test_safeplane_routes_case_study_command() -> None:
    script = (REPO_ROOT / "scripts/safeplane").read_text(encoding="utf-8")
    assert "case-study)" in script
    assert 'exec "$SCRIPT_DIR/safeplane-case-study" "$@"' in script


def test_status_script_reports_developer_model_profile_overrides() -> None:
    script = (REPO_ROOT / "tests/scripts/status-safeplane-mode").read_text(
        encoding="utf-8"
    )
    assert "Developer model profile overrides" in script
    assert "SAFEPLANE_MODEL_PROFILE_DEVELOPER_DOCUMENTATION" in script
    assert "SAFEPLANE_MODEL_PROFILE_DEVELOPER_IMPLEMENTATION" in script
    assert "SAFEPLANE_MODEL_PROFILE_DEVELOPER_REVIEW" in script
    assert "contract default" in script


def test_status_script_reports_developer_model_profile_overrides() -> None:
    script = (REPO_ROOT / "tests/scripts/status-safeplane-mode").read_text(
        encoding="utf-8"
    )
    assert "Developer model profile overrides" in script
    assert "SAFEPLANE_MODEL_PROFILE_${profile}" in script
    assert "DEVELOPER_DOCUMENTATION" in script
    assert "DEVELOPER_IMPLEMENTATION" in script
    assert "DEVELOPER_REVIEW" in script
    assert "contract default" in script


def test_safeplane_help_and_evidence_commands_are_operator_facing() -> None:
    script = (REPO_ROOT / "scripts/safeplane").read_text(encoding="utf-8")
    docs = (REPO_ROOT / "docs/scripts.md").read_text(encoding="utf-8")
    assert "help|--help|-h)" in script
    assert "evidence)" in script
    assert "safeplane evidence [latest|run-id]" in script
    assert "accept-publication-path" in docs


def test_capability_acceptance_scripts_replace_mvp_only_entrypoints() -> None:
    developer = REPO_ROOT / "tests/scripts/accept-developer-workflow"
    draft_pr = REPO_ROOT / "tests/scripts/accept-draft-pr-workflow"
    publication = REPO_ROOT / "tests/scripts/accept-publication-path"
    for path in (developer, draft_pr, publication):
        assert os.access(path, os.X_OK)
    assert "accept-developer-workflow" in publication.read_text(encoding="utf-8")
    assert "accept-draft-pr-workflow" in publication.read_text(encoding="utf-8")
    assert not list((REPO_ROOT / "tests/scripts").glob("validate-" + "m" + "vp*"))


def test_real_external_repository_acceptance_requires_automatic_draft_pr_policy() -> None:
    script = (REPO_ROOT / "tests/scripts/validate-real-external-repository").read_text(encoding="utf-8")
    assert "draft_pr_creation" in script
    assert "automatic" in script
    assert "./scripts/safeplane evidence $RUN_ID" in script
    assert "approve|record" in script


def test_developer_workflow_async_polling_fails_cleanly_on_http_or_json_errors() -> None:
    smoke = (
        REPO_ROOT / "tests/scripts/docker-smoke-single-pass-developer"
    ).read_text(encoding="utf-8")

    assert 'body="$(curl -fsS "http://127.0.0.1:${PORT}/runs/${run_id}")"' not in smoke
    assert "curl -sS -o \"$response_file\" -w '%{http_code}'" in smoke
    assert "Run-status poll returned HTTP $http_status" in smoke
    assert "Run-status poll returned invalid JSON" in smoke
    assert '[[ ! "$http_status" =~ ^2[0-9][0-9]$ ]]' in smoke


def test_real_telegram_acceptance_separates_basic_and_developer_paths() -> None:
    primary_path = REPO_ROOT / "tests/scripts/validate-real-telegram-workflows"
    developer_path = REPO_ROOT / "tests/scripts/validate-real-telegram-developer-workflow"
    primary = primary_path.read_text(encoding="utf-8")
    developer = developer_path.read_text(encoding="utf-8")

    assert os.access(primary_path, os.X_OK)
    assert os.access(developer_path, os.X_OK)

    assert "compose-safeplane-telegram-real" in primary
    assert "compose-safeplane-developer-telegram-real" not in primary
    assert "SAFEPLANE_REAL_TELEGRAM_PROFILE" not in primary
    assert "SAFEPLANE_REAL_TELEGRAM_TASK" not in primary
    assert '"/help" "help_sent"' in primary
    assert '"/assistant" "assistant"' in primary
    assert '"/chat" "chat"' in primary
    assert "dev-workspace-mcp" not in primary
    assert "/develop " not in primary
    assert "SAFEPLANE_HARNESS_PORT" not in primary
    assert '"$COMPOSE" exec -T harness python -' in primary
    assert "http://127.0.0.1:8080/health" in primary
    assert "--remove-orphans" in primary
    assert "--no-deps --force-recreate telegram-connector" in primary

    assert "compose-safeplane-developer-telegram-real" in developer
    assert "SAFEPLANE_REAL_TELEGRAM_PROFILE" in developer
    assert "SAFEPLANE_REAL_TELEGRAM_TASK" in developer
    assert "dev-workspace-mcp" in developer
    assert "/develop ${SAFEPLANE_REAL_TELEGRAM_PROFILE}" in developer
    assert "review_verdict" in developer
    assert "LGTM" in developer

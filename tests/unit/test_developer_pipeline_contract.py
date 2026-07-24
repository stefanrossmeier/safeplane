from __future__ import annotations

from pathlib import Path

import yaml

from harness.developer_pipeline import validate_developer_pipeline_contract
from harness.workflow_registry import build_registry


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_contract() -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "workflows/developer/workflow.yaml").read_text(encoding="utf-8")
    )


def test_developer_pipeline_contract_has_six_versioned_agents() -> None:
    contract = load_contract()
    validate_developer_pipeline_contract(contract)

    assert set(contract["agents"]) == {
        "documentation",
        "analysis",
        "planning",
        "implementation",
        "review",
        "pr",
    }
    profiles = {agent["model_profile"] for agent in contract["agents"].values()}
    assert len(profiles) == 6
    assert profiles <= set(contract["model_profiles"])
    assert contract["developer_pipeline"]["automatic_rework"] is False
    assert contract["developer_pipeline"]["single_pass"] is True
    assert {
        profile_id: contract["model_profiles"][profile_id]["request_timeout_seconds"]
        for profile_id in profiles
    } == {
        "developer_documentation": 900,
        "developer_analysis": 600,
        "developer_planning": 600,
        "developer_implementation": 1200,
        "developer_review": 600,
        "developer_pr": 300,
    }
    assert {
        profile_id: contract["model_profiles"][profile_id]["litellm_model"]
        for profile_id in profiles
    } == {
        "developer_documentation": "openrouter/openai/gpt-5-mini",
        "developer_analysis": "openrouter/anthropic/claude-haiku-4.5",
        "developer_planning": "openrouter/anthropic/claude-sonnet-4.6",
        "developer_implementation": "openrouter/openai/gpt-5-mini",
        "developer_review": "openrouter/anthropic/claude-haiku-4.5",
        "developer_pr": "openrouter/openai/gpt-5.4-nano",
    }


def test_developer_agent_prompts_exist_and_record_provenance() -> None:
    contract = load_contract()

    for agent_id, agent in contract["agents"].items():
        prompt = agent["prompt"]
        path = REPO_ROOT / prompt["path"]
        assert path.exists(), (agent_id, path)
        raw = path.read_text(encoding="utf-8")
        assert raw.startswith("---\n")
        frontmatter = yaml.safe_load(raw.split("---\n", 2)[1])
        assert frontmatter["id"] == prompt["id"]
        assert frontmatter["version"] == prompt["version"]
        assert frontmatter["role"] == agent_id
        assert frontmatter["provenance"]["derived_from"]
        assert "app.zip" in raw

    documentation_prompt = (
        REPO_ROOT / contract["agents"]["documentation"]["prompt"]["path"]
    ).read_text(encoding="utf-8")
    for marker in (
        "${ARCHDOC_COMMIT}",
        "${ARCHDOC_SKILL_SHA256}",
        "${DOCUMENTATION_PROMPT}",
        "${REPOSITORY_PROFILE}",
    ):
        assert marker in documentation_prompt
    assert "complete replacement JSON object" in documentation_prompt
    assert "Doc Status: DRAFT" in documentation_prompt
    assert (
        "Source Basis: repository files supplied through Safeplane MCP tools "
        "and the external archdoc skill"
    ) in documentation_prompt
    assert "The validator checks the literal field names `Doc Status:` and `Source Basis:`" in documentation_prompt
    assert "operator task is not an implementation instruction" in documentation_prompt
    assert "`README.md`" in documentation_prompt
    assert "developer_request" not in contract["agents"]["documentation"]["input_artifacts"]


def test_archdoc_is_referenced_as_external_and_not_copied() -> None:
    manifest = yaml.safe_load(
        (REPO_ROOT / "prompts/developer/manifest.yaml").read_text(encoding="utf-8")
    )
    archdoc = manifest["source_notes"]["archdoc"]
    assert archdoc["external_repository"].endswith("/ai-craftkit.git")
    assert archdoc["path"] == "skills/archdoc"
    assert archdoc["copied_into_safeplane"] is False

    copied = [
        path
        for path in (REPO_ROOT / "prompts").rglob("*")
        if path.is_file() and "archdoc" in path.parts
    ]
    assert copied == []


def test_develop_entrypoint_exposes_agent_configuration() -> None:
    config_path = REPO_ROOT / "safeplane.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    registry = build_registry(config, config_path)

    entry = registry["develop"]
    assert entry.workflow_id == "developer"
    assert entry.agents["implementation"]["model_profile"] == "developer_implementation"
    assert entry.developer_pipeline["entrypoint"] == "develop"


def test_repository_workspace_contract_scopes_archdoc_to_documentation_agent() -> None:
    contract = load_contract()
    source = contract["repository_workspace"]["external_sources"]["archdoc"]
    assert source["repository_url"].endswith("/ai-craftkit.git")
    assert source["required_path"] == "skills/archdoc"
    assert source["allowed_agents"] == ["documentation"]
    assert source["read_only"] is True


def test_documentation_runtime_uses_external_archdoc_without_persisting_skill_content() -> None:
    contract = load_contract()
    runtime = contract["developer_pipeline"]["documentation_runtime"]
    assert runtime["enabled"] is True
    assert runtime["source_id"] == "archdoc"
    assert runtime["skill_entrypoint"] == "SKILL.md"
    assert runtime["target_document_paths"] == [
        "docs/REPO_MAP.md",
        "docs/ARCHITECTURE.md",
        "docs/API_SURFACE.md",
        "docs/OPERATIONS.md",
    ]
    assert runtime["read_page_lines"] == 2000
    assert runtime["tracked_file_page_size"] == 1000
    assert runtime["max_repository_files"] == 10000
    assert runtime["require_complete_repository_evidence"] is True

    manifest = yaml.safe_load(
        (REPO_ROOT / "prompts/developer/manifest.yaml").read_text(encoding="utf-8")
    )
    archdoc = manifest["source_notes"]["archdoc"]
    assert archdoc["documentation_agent_consumes_at_runtime"] == "external documentation workflow implemented"
    assert archdoc["runtime_content_persisted_in_prompt_bundle"] is False


def test_single_pass_contract_keeps_agent_authorship_and_deterministic_side_effects_separate() -> None:
    contract = load_contract()
    mcp = contract["mcp"]

    assert "dev_check_run" in mcp["allowed_servers"]["dev-check"]["tools"]
    assert "dev_workspace_apply_patch" in mcp["approval_required_servers"]["dev-workspace-apply"]["tools"]
    assert "dev_workspace_propose_patch" in contract["agents"]["implementation"]["allowed_mcp_servers"]["dev-workspace"]["tools"]

    for agent in contract["agents"].values():
        tools = {
            tool
            for policy in agent["allowed_mcp_servers"].values()
            for tool in policy.get("tools", [])
        }
        assert "dev_check_run" not in tools
        assert "dev_workspace_apply_patch" not in tools
        assert "dev_workspace_ready" not in tools

    model_tools = {
        tool
        for policy in mcp["model_allowed_servers"].values()
        for tool in policy.get("tools", [])
    }
    assert "dev_check_run" not in model_tools
    assert "dev_workspace_apply_patch" not in model_tools
    assert "dev_workspace_ready" not in model_tools
    assert "dev_external_skill_read" not in model_tools


def test_review_and_pr_receive_apply_and_controlled_check_evidence() -> None:
    contract = load_contract()
    assert "implementation_apply" in contract["agents"]["review"]["input_artifacts"]
    assert "implementation_apply" in contract["agents"]["pr"]["input_artifacts"]
    assert "check_result" in contract["agents"]["review"]["input_artifacts"]
    assert "check_result" in contract["agents"]["pr"]["input_artifacts"]


def test_developer_pipeline_contract_rejects_unbounded_model_timeout() -> None:
    contract = load_contract()
    contract["model_profiles"]["developer_documentation"][
        "request_timeout_seconds"
    ] = 3601

    try:
        validate_developer_pipeline_contract(contract)
    except Exception as exc:
        assert "request_timeout_seconds must be between 1 and 3600" in str(exc)
    else:
        raise AssertionError("unbounded model timeout was accepted")


def test_developer_documentation_profile_requires_json_object_response() -> None:
    contract = load_contract()

    profile = contract["model_profiles"]["developer_documentation"]
    assert profile["response_format"] == "json_object"

    profile["response_format"] = "yaml"
    try:
        validate_developer_pipeline_contract(contract)
    except Exception as exc:
        assert "response_format must be json_object" in str(exc)
    else:
        raise AssertionError("unsupported response format was accepted")


def test_planning_agent_requires_grounded_direct_check_scripts() -> None:
    contract = load_contract()
    planning = contract["agents"]["planning"]

    assert planning["prompt"]["version"] == "v6"
    prompt = (REPO_ROOT / planning["prompt"]["path"]).read_text(encoding="utf-8")
    assert "explicit operator scope constraints" in prompt
    assert '"README only"' in prompt
    assert '"no check scripts"' in prompt
    assert "must already exist as a regular repository file" in prompt
    assert "Never copy an example or placeholder path" in prompt
    assert "directly runnable by the exact argv" in prompt
    assert "Do not plan a new focused check that imports or executes" in prompt
    assert "`ast.literal_eval`" in prompt
    assert "State that mechanism explicitly" in prompt
    roots = contract["developer_tools"]["command_profiles"]["python_check"]["allowed_roots"]
    assert roots == ["checks", "scripts/checks", "tests"]


def test_implementation_agent_uses_versioned_unbounded_tool_loop_contract() -> None:
    contract = load_contract()
    implementation = contract["agents"]["implementation"]

    assert implementation["prompt"]["version"] == "v7"
    assert implementation["tool_loop_timeout_seconds"] == 3600
    prompt = (REPO_ROOT / implementation["prompt"]["path"]).read_text(encoding="utf-8")
    assert "as many tool calls as needed" in prompt
    assert 'Finish only by returning a `type: "final"` response' in prompt
    assert "Do not return Git diff syntax" in prompt
    assert "directly runnable by the exact argv" in prompt
    assert "every line of a created file counts as changed" in prompt
    assert "simplify the implementation" in prompt
    assert "runs every declared check against your candidate patch" in prompt
    assert "Python places the script directory" in prompt
    assert "standard-library source or AST inspection" in prompt
    assert "expected_change_summary` as a required implementation mechanism" in prompt
    assert "Passing the declared checks is necessary but not sufficient" in prompt
    assert "count physical lines before returning final" in prompt
    assert "`ast.literal_eval`" in prompt
    assert implementation["max_model_attempts"] == 4


def test_implementation_tool_loop_timeout_is_required_and_bounded() -> None:
    contract = load_contract()
    del contract["agents"]["implementation"]["tool_loop_timeout_seconds"]

    try:
        validate_developer_pipeline_contract(contract)
    except Exception as exc:
        assert "implementation agent must define tool_loop_timeout_seconds" in str(exc)
    else:
        raise AssertionError("implementation tool loop timeout was optional")

    contract = load_contract()
    contract["agents"]["implementation"]["tool_loop_timeout_seconds"] = 14401
    try:
        validate_developer_pipeline_contract(contract)
    except Exception as exc:
        assert "tool_loop_timeout_seconds must be between 1 and 14400" in str(exc)
    else:
        raise AssertionError("unbounded implementation tool loop timeout was accepted")


def test_review_agent_requires_explicit_exact_plan_alignment() -> None:
    contract = load_contract()
    review = contract["agents"]["review"]

    assert review["prompt"]["version"] == "v2"
    prompt = (REPO_ROOT / review["prompt"]["path"]).read_text(encoding="utf-8")
    assert "behaviorally equivalent implementation is still a plan deviation" in prompt
    assert "Passing checks does not excuse a plan deviation" in prompt
    assert "plan_alignment" in prompt

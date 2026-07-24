from __future__ import annotations

import pytest
from pydantic import ValidationError

from harness.developer_pipeline import (
    ImplementationPlan,
    ReviewResult,
)


def valid_plan() -> dict:
    return {
        "developer_plan_markdown": "# Plan\n",
        "files_to_modify": ["src/main.py"],
        "files_to_create": [],
        "files_to_delete": [],
        "file_change_policy": {
            "src/main.py": {
                "expected_change_summary": "Change one behavior",
                "max_changed_lines": 10,
                "max_hunks": 1,
            }
        },
        "test_commands": [["python", "-m", "pytest", "-q"]],
        "documentation_impact": "none",
        "risks": [],
        "assumptions": [],
        "commit_message": "Change one behavior",
    }


def test_plan_requires_policy_for_every_changed_file() -> None:
    data = valid_plan()
    data["files_to_create"] = ["tests/test_main.py"]

    with pytest.raises(ValidationError, match="file_change_policy"):
        ImplementationPlan.model_validate(data)



def test_plan_allows_no_declared_repository_checks() -> None:
    data = valid_plan()
    data["files_to_modify"] = ["README.md"]
    data["file_change_policy"] = {
        "README.md": {
            "expected_change_summary": "Add the requested documentation section",
            "max_changed_lines": 12,
            "max_hunks": 1,
        }
    }
    data["test_commands"] = []

    plan = ImplementationPlan.model_validate(data)

    assert plan.test_commands == []

def test_plan_rejects_shell_operators() -> None:
    data = valid_plan()
    data["test_commands"] = [["python", "-m", "pytest", "&&", "echo", "done"]]

    with pytest.raises(ValidationError, match="shell operators"):
        ImplementationPlan.model_validate(data)


def test_plan_normalizes_long_multiline_commit_message() -> None:
    data = valid_plan()
    data["commit_message"] = (
        "refactor(config): remove one deprecated entry while preserving the remaining "
        "configuration and add focused regression coverage for the declared behavior\n\n"
        "This body must not become part of the commit summary."
    )

    plan = ImplementationPlan.model_validate(data)

    assert len(plan.commit_message) <= 120
    assert "\n" not in plan.commit_message
    assert plan.commit_message == (
        "refactor(config): remove one deprecated entry while preserving the remaining "
        "configuration and add focused regression"
    )


def test_plan_drops_zero_budget_noop_paths_without_expanding_authority() -> None:
    data = valid_plan()
    data["files_to_create"] = ["tests/__init__.py"]
    data["file_change_policy"]["tests/__init__.py"] = {
        "expected_change_summary": "Create an empty package marker file.",
        "max_changed_lines": 0,
        "max_hunks": 1,
    }

    plan = ImplementationPlan.model_validate(data)

    assert plan.files_to_modify == ["src/main.py"]
    assert plan.files_to_create == []
    assert plan.files_to_delete == []
    assert set(plan.file_change_policy) == {"src/main.py"}


def test_plan_does_not_hide_negative_change_budgets() -> None:
    data = valid_plan()
    data["file_change_policy"]["src/main.py"]["max_changed_lines"] = -1

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        ImplementationPlan.model_validate(data)


def test_review_contract_enforces_verdict_changes_consistency() -> None:
    ReviewResult.model_validate(
        {
            "verdict": "LGTM",
            "plan_alignment": "ALIGNED",
            "summary": "good",
            "requested_changes": [],
            "docs_update_needed": False,
            "risk_notes": [],
        }
    )

    with pytest.raises(ValidationError, match="non-empty"):
        ReviewResult.model_validate(
            {
                "verdict": "REQUEST_CHANGES",
                "plan_alignment": "DEVIATION",
                "summary": "needs work",
                "requested_changes": [],
                "docs_update_needed": False,
                "risk_notes": [],
            }
        )


def test_review_contract_rejects_lgtm_with_plan_deviation() -> None:
    with pytest.raises(ValidationError, match="LGTM requires plan_alignment ALIGNED"):
        ReviewResult.model_validate(
            {
                "verdict": "LGTM",
                "plan_alignment": "DEVIATION",
                "summary": "behavior passes but mechanism differs",
                "requested_changes": [],
                "docs_update_needed": False,
                "risk_notes": [],
            }
        )

from __future__ import annotations

from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services/harness/src"))

from harness.main import (  # noqa: E402
    ConnectorMessageRequest,
    handle_connector_entrypoint,
    list_workflows,
)


def configure_repo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAFEPLANE_CONFIG", str(REPO_ROOT / "safeplane.yaml"))
    monkeypatch.setenv("SAFEPLANE_HOME", str(tmp_path / "safeplane-home"))


def test_harness_lists_only_telegram_exposed_operator_workflows(
    tmp_path: Path, monkeypatch
) -> None:
    configure_repo(monkeypatch, tmp_path)

    response = list_workflows(connector="telegram", exposed_only=True)

    assert response["connector"] == "telegram"
    assert response["default_entrypoint"] == "assistant"
    assert response["routing_mode"] == "automatic"
    assert response["automatic_routing"] is True
    assert [item["entrypoint"] for item in response["workflows"]] == [
        "assistant",
        "chat",
        "develop",
    ]


def test_harness_rejects_telegram_access_to_internal_entrypoint(
    tmp_path: Path, monkeypatch
) -> None:
    configure_repo(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        handle_connector_entrypoint(
            "slow",
            ConnectorMessageRequest(connector="telegram", message="1"),
        )

    assert exc_info.value.status_code == 403
    assert "not exposed to connector 'telegram'" in str(exc_info.value.detail)

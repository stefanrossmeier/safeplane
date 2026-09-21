from pathlib import Path

from safeplane_routing_advisor.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_resolves_operator_routes(tmp_path: Path) -> None:
    (tmp_path / "workflows/chat").mkdir(parents=True)
    (tmp_path / "workflows/assistant").mkdir(parents=True)
    (tmp_path / "workflows/developer").mkdir(parents=True)
    (tmp_path / "safeplane.yaml").write_text(
        """
entrypoints:
  chat: {workflow: chat, operator_facing: true}
  assistant: {workflow: assistant, operator_facing: true}
  developer: {workflow: developer, operator_facing: false}
  develop: {workflow: developer, operator_facing: true}
workflows:
  chat: {enabled: true, contract: workflows/chat/workflow.yaml}
  assistant: {enabled: true, contract: workflows/assistant/workflow.yaml}
  developer: {enabled: true, contract: workflows/developer/workflow.yaml}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "workflows/chat/workflow.yaml").write_text(
        """
workflow_id: chat
version: 0.1.0
description: general chat
examples: [Say hello]
mcp: {servers: []}
deterministic_tools: {enabled: []}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "workflows/assistant/workflow.yaml").write_text(
        """
workflow_id: assistant
version: 0.1.0
description: personal assistant
examples: [Plan today]
mcp: {servers: [calendar, notification]}
deterministic_tools: {enabled: [calendar]}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "workflows/developer/workflow.yaml").write_text(
        """
workflow_id: developer
version: 0.9.0
description: repository developer
examples: [Inspect repository]
mcp: {servers: [dev-workspace, dev-check]}
deterministic_tools: {enabled: [developer]}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    catalog = load_catalog(tmp_path, ROOT / "data" / "routing_semantics.v1.yaml")
    assert set(catalog.routes) == {"chat", "assistant", "developer"}
    assert catalog.routes["developer"].operator_entrypoint == "develop"
    assert catalog.routes["assistant"].mcp_servers == ["calendar", "notification"]
    assert "General conversation" in catalog.routes["chat"].criterion_text()

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from harness import main
from harness.remote_write import RemoteWriteResult


def test_execute_run_keeps_run_nonterminal_until_automatic_draft_pr_finishes(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []
    session = {"turns": [], "status": "active"}

    monkeypatch.setattr(main, "safeplane_home", lambda: tmp_path)
    monkeypatch.setattr(main, "trace_dir", lambda _session, _turn: tmp_path / "trace")
    monkeypatch.setattr(main, "mark_running", lambda *_args, **_kwargs: events.append("running"))
    monkeypatch.setattr(main, "write_trace", lambda **_kwargs: None)
    monkeypatch.setattr(
        main,
        "run_agent_runtime",
        lambda _request: SimpleNamespace(
            status="completed",
            final_message="waiting for draft PR publication",
        ),
    )
    monkeypatch.setattr(
        main,
        "mark_completed",
        lambda *_args, **_kwargs: events.append("marked_completed"),
    )
    monkeypatch.setattr(main, "_draft_pr_creation_mode", lambda _home, _run: "automatic")

    result = RemoteWriteResult(
        approval_id="remote_approval_example",
        run_id="run_example",
        branch_name="safeplane/example",
        commit_sha="a" * 40,
        pull_request_number=1,
        pull_request_url="https://github.com/example/repo/pull/1",
        branch_reused=False,
        pull_request_reused=False,
        approval_ref="workspaces/run_example/remote-approvals/example.json",
        evidence_ref="workspaces/run_example/remote-approvals/example.evidence.json",
    )

    def execute_remote_write(**kwargs):
        assert kwargs["run_id"] == "run_example"
        assert kwargs["connector"] == "cli"
        assert kwargs["authorization_source"] == "repository_policy"
        events.append("draft_pr_created")
        return result

    monkeypatch.setattr(main, "execute_remote_write", execute_remote_write)
    monkeypatch.setattr(main, "_developer_contract", lambda: {})
    monkeypatch.setattr(
        main,
        "load_run",
        lambda _home, _run: {
            "connector": "cli",
            "final_message": "Draft pull request created: https://github.com/example/repo/pull/1. Safeplane did not merge it.",
        },
    )
    monkeypatch.setattr(main, "load_session", lambda _session: session)
    monkeypatch.setattr(
        main,
        "append_completed_session_turn",
        lambda **kwargs: session["turns"].append({"final_message": kwargs["final_message"]}),
    )
    monkeypatch.setattr(main, "save_session", lambda _session: None)
    monkeypatch.setattr(main, "session_path", lambda _session: tmp_path / "session.json")
    monkeypatch.setattr(main, "write_output_artifact", lambda **_kwargs: "output.json")

    main.execute_run(
        run_id="run_example",
        session_id="sess_example",
        session_display_id="S-EXAMPLE",
        turn=1,
        workflow_entry=SimpleNamespace(workflow_id="developer"),
        model_gateway_url="http://model-gateway/chat",
        entrypoint_name="develop",
        operator_message="bounded task",
        history_messages=[],
        repository_profile="automatic-profile",
    )

    assert events.index("draft_pr_created") < events.index("marked_completed")
    assert session["turns"][-1]["final_message"].endswith("Safeplane did not merge it.")

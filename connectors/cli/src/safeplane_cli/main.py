from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

from safeplane_connector import (
    HarnessAuthorizationError,
    HarnessClient,
    HarnessProtocolError,
    HarnessRejectedError,
    HarnessUnavailableError,
)

from . import __version__
from . import exit_codes
from .rendering import (
    render_connector_result,
    render_json,
    render_patch_approval,
    render_remote_approval,
    render_run,
    render_runs,
    render_workflows,
)

DEFAULT_HARNESS_URL = "http://harness:8080"


class CliUsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)


def build_parser() -> Parser:
    parser = Parser(prog="safeplane", description="Safeplane one-shot CLI connector")
    parser.add_argument("--version", action="version", version=f"safeplane-cli {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    workflows = sub.add_parser("workflows", help="List workflow entrypoints")
    _add_output_argument(workflows)
    runs = sub.add_parser("runs", help="List run records")
    _add_output_argument(runs)

    status = sub.add_parser("status", help="Inspect one run")
    _add_output_argument(status)
    status.add_argument("run_id")

    patch = sub.add_parser("approve-patch", help="Approve one patch proposal")
    _add_output_argument(patch)
    patch.add_argument("run_id")
    patch.add_argument("proposal_id")

    remote = sub.add_parser("approve-pr", help="Approve or retry draft-PR publication")
    _add_output_argument(remote)
    remote.add_argument("run_id")

    run = sub.add_parser("run", help="Invoke an explicit workflow entrypoint")
    _add_output_argument(run)
    run.add_argument("entrypoint")
    _add_workflow_arguments(run, allow_repo=True)

    for name in ("chat", "assistant", "developer"):
        command = sub.add_parser(name, help=f"Invoke the {name} entrypoint")
        _add_output_argument(command)
        _add_workflow_arguments(command, allow_repo=False)

    develop = sub.add_parser("develop", help="Invoke the developer workflow")
    _add_output_argument(develop)
    _add_workflow_arguments(develop, allow_repo=True)
    return parser


def _add_output_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", choices=("text", "json"), default="text")


def _add_workflow_arguments(parser: argparse.ArgumentParser, *, allow_repo: bool) -> None:
    parser.add_argument("--session", dest="session_ref")
    if allow_repo:
        parser.add_argument("--repo", dest="repository_profile")
    parser.add_argument("message", nargs="+")


def _message(parts: Sequence[str]) -> str:
    message = " ".join(parts)
    if not message:
        raise CliUsageError("workflow commands require a message")
    return message


def _print(value: str) -> None:
    if value:
        print(value)


def execute(args: argparse.Namespace, *, output: str, client: HarnessClient) -> int:
    if args.command == "workflows":
        result = client.connector.list_workflows()
        _print(render_json(result.raw) if output == "json" else render_workflows(result))
        return exit_codes.SUCCESS

    if args.command == "runs":
        result = client.control.list_runs()
        _print(render_json(result.raw) if output == "json" else render_runs(result.runs))
        return exit_codes.SUCCESS

    if args.command == "status":
        result = client.control.get_run(args.run_id)
        _print(render_json(result) if output == "json" else render_run(result))
        return exit_codes.SUCCESS

    if args.command == "approve-patch":
        result = client.control.approve_patch(args.run_id, args.proposal_id)
        _print(render_json(result.raw) if output == "json" else render_patch_approval(result.raw))
        return exit_codes.SUCCESS

    if args.command == "approve-pr":
        result = client.control.approve_remote(args.run_id)
        _print(render_json(result.raw) if output == "json" else render_remote_approval(result.raw))
        return exit_codes.SUCCESS

    entrypoint = args.entrypoint if args.command == "run" else args.command
    repository_profile = getattr(args, "repository_profile", None)
    if repository_profile and entrypoint != "develop":
        raise CliUsageError("--repo is only valid for the develop entrypoint")
    result = client.connector.start_workflow(
        entrypoint,
        _message(args.message),
        session_ref=args.session_ref,
        repository_profile=repository_profile,
    )
    if output == "json":
        _print(render_json(result.raw))
    elif result.status == "completed":
        _print(render_connector_result(result))
    else:
        print(render_json(result.raw), file=sys.stderr)
    return exit_codes.SUCCESS if result.status == "completed" else exit_codes.RUN_UNSUCCESSFUL


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(raw)
        client = HarnessClient(
            os.environ.get("SAFEPLANE_HARNESS_URL", DEFAULT_HARNESS_URL),
            connector_name="cli",
        )
        return execute(args, output=args.output, client=client)
    except CliUsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        parser.print_usage(sys.stderr)
        return exit_codes.USAGE
    except HarnessUnavailableError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exit_codes.HARNESS_UNAVAILABLE
    except HarnessAuthorizationError as exc:
        print(f"Error: {exc.detail}", file=sys.stderr)
        return exit_codes.AUTHORIZATION
    except HarnessRejectedError as exc:
        print(f"Error: {exc.detail}", file=sys.stderr)
        return exit_codes.REJECTED
    except HarnessProtocolError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exit_codes.PROTOCOL


if __name__ == "__main__":
    raise SystemExit(main())

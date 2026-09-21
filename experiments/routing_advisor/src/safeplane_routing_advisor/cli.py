from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .catalog import load_catalog
from .jev import DEFAULT_MODEL, DEFAULT_URL
from .reporting import write_reports
from .runner import load_suite, run_suite


def _default_data_dir() -> Path:
    configured = os.getenv("ROUTING_ADVISOR_DATA_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data"


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--version",
        choices=("v1", "v2"),
        default="v2",
        help="Experiment contract/corpus version. V2 is the current experiment; V1 remains reproducible.",
    )
    parser.add_argument("--semantics", type=Path, help="Override the version-selected semantics YAML.")
    parser.add_argument("--corpus", type=Path, help="Override the version-selected frozen corpus JSON.")


def _resolve_inputs(args: argparse.Namespace) -> tuple[Path, Path]:
    data = _default_data_dir()
    semantics = args.semantics or data / f"routing_semantics.{args.version}.yaml"
    corpus = args.corpus or data / f"corpus.{args.version}.json"
    return semantics, corpus


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Isolated Jev routing-advisor experiment for Safeplane workflows."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser(
        "validate", help="Validate workflow catalog and frozen corpus without network calls."
    )
    _common(validate)

    run = sub.add_parser("run", help="Run the live Jev corpus evaluation and write reports.")
    _common(run)
    run.add_argument("--output-dir", type=Path)
    run.add_argument("--model", default=os.getenv("ROUTING_ADVISOR_JEV_MODEL", DEFAULT_MODEL))
    run.add_argument("--url", default=os.getenv("ROUTING_ADVISOR_OPENROUTER_URL", DEFAULT_URL))
    run.add_argument(
        "--concurrency", type=int, default=int(os.getenv("ROUTING_ADVISOR_CONCURRENCY", "8"))
    )
    run.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.getenv("ROUTING_ADVISOR_TIMEOUT_SECONDS", "30")),
    )
    run.add_argument(
        "--max-retries", type=int, default=int(os.getenv("ROUTING_ADVISOR_MAX_RETRIES", "3"))
    )
    run.add_argument(
        "--fresh",
        action="store_true",
        help="Discard matching checkpoint data and call Jev for every case again.",
    )
    return parser


def _validate(args: argparse.Namespace) -> int:
    semantics, corpus = _resolve_inputs(args)
    catalog = load_catalog(args.repo_root, semantics)
    suite = load_suite(corpus)
    if suite.metadata.corpus_version != args.version:
        raise SystemExit(
            f"selected --version {args.version} but corpus declares {suite.metadata.corpus_version}"
        )
    if f"v{catalog.semantics_version}" != args.version:
        raise SystemExit(
            f"selected --version {args.version} but semantics declare v{catalog.semantics_version}"
        )
    counts: dict[str, int] = {}
    for case in suite.cases:
        key = case.expected_route or case.decision_type
        counts[key] = counts.get(key, 0) + 1
    print(
        f"Validated {len(suite.cases)} frozen {args.version} cases: "
        f"{json.dumps(counts, sort_keys=True)}"
    )
    print(
        f"decision_contract={suite.metadata.decision_contract} semantics=v{catalog.semantics_version} "
        f"calibration={sum(case.split == 'calibration' for case in suite.cases)} "
        f"holdout={sum(case.split == 'holdout' for case in suite.cases)}"
    )
    for name, route in catalog.routes.items():
        print(
            f"{name}: entrypoint={route.operator_entrypoint} workflow={route.workflow_id} "
            f"version={route.version} sha256={route.source_sha256[:12]}"
        )
    return 0


async def _run(args: argparse.Namespace) -> int:
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be at least 1")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is required for a live run")
    semantics, corpus = _resolve_inputs(args)
    catalog = load_catalog(args.repo_root, semantics)
    suite = load_suite(corpus)
    if suite.metadata.corpus_version != args.version or f"v{catalog.semantics_version}" != args.version:
        raise SystemExit("corpus/semantics version does not match --version")

    output_dir = args.output_dir or Path("reports") / args.version
    run = await run_suite(
        suite,
        catalog=catalog,
        api_key=api_key,
        model=args.model,
        url=args.url,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        concurrency=args.concurrency,
        repo_root=args.repo_root.resolve(),
        corpus_path=corpus.resolve(),
        output_dir=output_dir.resolve(),
        fresh=args.fresh,
    )
    stem = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    md_path, json_path, csv_path = write_reports(run, output_dir, stem)
    latest_md, latest_json, latest_csv = write_reports(run, output_dir, "latest")
    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"Updated {latest_md}, {latest_json}, {latest_csv}")
    summary = run["summary"]
    if run["decision_contract"] == "v1":
        print(
            "raw_accuracy={:.2%} decisive_accuracy={:.2%} ambiguous_unclear_recall={:.2%} "
            "dangerous_escalations={} cost=${:.6f}".format(
                summary["raw_accuracy"],
                summary["decisive_accuracy"],
                summary["ambiguous_unclear_recall"],
                summary["dangerous_escalations"],
                run["usage"]["estimated_cost_usd"],
            )
        )
    else:
        candidates = summary["candidate_operating_points"]
        best = candidates[0] if candidates else None
        suffix = (
            " best_holdout_coverage={:.2%} best_holdout_policy_accuracy={:.2%}".format(
                best["holdout_coverage"], best["holdout_policy_decision_accuracy"]
            )
            if best
            else " no_candidate_policy_met_strict_calibration_filter"
        )
        print(
            "single_route_accuracy={:.2%} dangerous_raw_escalations={} cost=${:.6f}{}".format(
                summary["single_route_accuracy"],
                summary["dangerous_escalations_raw_single_route"],
                run["usage"]["estimated_cost_usd"],
                suffix,
            )
        )
    return 0


def main() -> int:
    args = _parser().parse_args()
    if args.command == "validate":
        return _validate(args)
    if args.command == "run":
        return asyncio.run(_run(args))
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

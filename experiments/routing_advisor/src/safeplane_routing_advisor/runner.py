from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .jev import JevClient
from .metrics import summarize
from .models import CaseResult, EvaluationCase, EvaluationSuite, WorkflowCatalog
from .policy import is_dangerous_escalation


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_state(repo_root: Path) -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None, None
    if commit.returncode != 0 or status.returncode != 0:
        return None, None
    return commit.stdout.strip(), bool(status.stdout.strip())


def load_suite(path: Path) -> EvaluationSuite:
    return EvaluationSuite.model_validate_json(path.read_text(encoding="utf-8"))


def _checkpoint_fingerprint(
    *, corpus_sha256: str, catalog: WorkflowCatalog, model: str
) -> dict[str, Any]:
    return {
        "corpus_sha256": corpus_sha256,
        "safeplane_yaml_sha256": catalog.safeplane_yaml_sha256,
        "semantics_sha256": catalog.semantics_sha256,
        "workflow_sha256": {
            name: route.source_sha256 for name, route in catalog.routes.items()
        },
        "configured_model": model,
    }


def _load_checkpoint(
    checkpoint_path: Path,
    meta_path: Path,
    fingerprint: dict[str, Any],
) -> dict[str, CaseResult]:
    if not checkpoint_path.exists() or not meta_path.exists():
        if checkpoint_path.exists() != meta_path.exists():
            checkpoint_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
        return {}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        checkpoint_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        return {}
    if meta != fingerprint:
        checkpoint_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        return {}
    results: dict[str, CaseResult] = {}
    for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = CaseResult.model_validate_json(line)
        if not item.error:
            results[item.case_id] = item
    return results


async def run_suite(
    suite: EvaluationSuite,
    *,
    catalog: WorkflowCatalog,
    api_key: str,
    model: str,
    url: str,
    timeout_seconds: float,
    max_retries: int,
    concurrency: int,
    repo_root: Path,
    corpus_path: Path,
    output_dir: Path,
    fresh: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus_sha = file_sha256(corpus_path)
    checkpoint_path = output_dir / ".checkpoint.jsonl"
    checkpoint_meta_path = output_dir / ".checkpoint.meta.json"
    fingerprint = _checkpoint_fingerprint(
        corpus_sha256=corpus_sha,
        catalog=catalog,
        model=model,
    )
    if fresh:
        checkpoint_path.unlink(missing_ok=True)
        checkpoint_meta_path.unlink(missing_ok=True)
    cached = _load_checkpoint(checkpoint_path, checkpoint_meta_path, fingerprint)
    checkpoint_meta_path.write_text(
        json.dumps(fingerprint, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    semaphore = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()

    async with JevClient(
        api_key,
        model=model,
        url=url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    ) as client:

        async def evaluate(case: EvaluationCase) -> CaseResult:
            if case.case_id in cached:
                return cached[case.case_id]
            async with semaphore:
                started = time.perf_counter()
                try:
                    assessment = await client.assess(case, catalog)
                    result = CaseResult(
                        case_id=case.case_id,
                        request_text=case.request_text,
                        context=case.context,
                        rationale=case.rationale,
                        family=case.family,
                        tags=case.tags,
                        pair_id=case.pair_id,
                        decision_type=case.decision_type,
                        split=case.split,
                        expected_route=case.expected_route,
                        predicted_route=assessment.route,
                        route_probabilities=assessment.route_probabilities,
                        route_confidence=assessment.route_confidence,
                        route_margin=assessment.route_margin,
                        ambiguous_probability=assessment.ambiguous_probability,
                        route_identifiable_probability=assessment.route_identifiable_probability,
                        needs_clarification_probability=assessment.needs_clarification_probability,
                        requires_multiple_workflows_probability=assessment.requires_multiple_workflows_probability,
                        repository_work_probability=assessment.repository_work_probability,
                        missing_repository_profile_probability=assessment.missing_repository_profile_probability,
                        assistant_tool_need_probability=assessment.assistant_tool_need_probability,
                        expected_ambiguous=case.expected_ambiguous,
                        expected_route_identifiable=case.expected_route_identifiable,
                        expected_needs_clarification=case.expected_needs_clarification,
                        expected_requires_multiple_workflows=case.expected_requires_multiple_workflows,
                        expected_repository_work=case.expected_repository_work,
                        expected_missing_repository_profile=case.expected_missing_repository_profile,
                        expected_assistant_tool_need=case.expected_assistant_tool_need,
                        route_correct=(
                            assessment.route == case.expected_route
                            if case.expected_route is not None
                            else None
                        ),
                        dangerous_escalation=(
                            is_dangerous_escalation(case.expected_route, assessment.route)
                            if case.expected_route is not None
                            else False
                        ),
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                        model=assessment.model,
                        provider=assessment.provider,
                        input_tokens=assessment.usage.input_tokens,
                        output_tokens=assessment.usage.output_tokens,
                        estimated_cost_usd=assessment.usage.estimated_cost_usd,
                    )
                except Exception as exc:  # per-case failures are evaluation data
                    result = CaseResult(
                        case_id=case.case_id,
                        request_text=case.request_text,
                        context=case.context,
                        rationale=case.rationale,
                        family=case.family,
                        tags=case.tags,
                        pair_id=case.pair_id,
                        decision_type=case.decision_type,
                        split=case.split,
                        expected_route=case.expected_route,
                        expected_ambiguous=case.expected_ambiguous,
                        expected_route_identifiable=case.expected_route_identifiable,
                        expected_needs_clarification=case.expected_needs_clarification,
                        expected_requires_multiple_workflows=case.expected_requires_multiple_workflows,
                        expected_repository_work=case.expected_repository_work,
                        expected_missing_repository_profile=case.expected_missing_repository_profile,
                        expected_assistant_tool_need=case.expected_assistant_tool_need,
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                async with write_lock:
                    with checkpoint_path.open("a", encoding="utf-8") as handle:
                        handle.write(result.model_dump_json() + "\n")
                return result

        results = list(await asyncio.gather(*(evaluate(case) for case in suite.cases)))

    commit, dirty = git_state(repo_root)
    summary = summarize(results, suite.metadata.decision_contract)
    completed = [item for item in results if not item.error]
    now = datetime.now(UTC)
    return {
        "benchmark": "safeplane-jev-routing-advisor",
        "benchmark_version": suite.metadata.corpus_version,
        "decision_contract": suite.metadata.decision_contract,
        "timestamp_utc": now.isoformat(),
        "methodology": (
            "Live Jev routing evaluation over a frozen Safeplane corpus. "
            "V1 uses a four-way route choice plus ambiguity diagnostics. "
            "V2 uses a three-way route choice and separates route identifiability, execution clarification, "
            "multi-workflow intent, repository intent, missing repository context, and assistant-tool need. "
            "Policy sweeps are descriptive only; this experiment does not alter production routing."
        ),
        "git_commit": commit,
        "git_dirty": dirty,
        "configured_model": model,
        "observed_models": sorted({item.model for item in completed if item.model}),
        "observed_providers": sorted({item.provider for item in completed if item.provider}),
        "corpus": {
            "path": str(corpus_path),
            "sha256": corpus_sha,
            "metadata": suite.metadata.model_dump(),
        },
        "catalog": catalog.model_dump(),
        "summary": summary,
        "usage": {
            "input_tokens": sum(item.input_tokens for item in completed),
            "output_tokens": sum(item.output_tokens for item in completed),
            "estimated_cost_usd": sum(item.estimated_cost_usd for item in completed),
            "median_duration_ms": (
                statistics.median(
                    item.duration_ms for item in completed if item.duration_ms is not None
                )
                if completed
                else None
            ),
        },
        "cases": [item.model_dump() for item in results],
    }

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _num(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _render_v1(run: dict[str, Any]) -> str:
    summary = run["summary"]
    usage = run["usage"]
    calibration = summary["split_metrics"]["calibration"]
    holdout = summary["split_metrics"]["holdout"]
    lines = [
        "# Safeplane Jev Routing Advisor Evaluation",
        "",
        "> This is experiment evidence, not production routing policy. Safeplane production routing is unchanged.",
        "",
        "## Run identity",
        "",
        f"- Timestamp (UTC): `{run['timestamp_utc']}`",
        f"- Git commit: `{run['git_commit'] or 'unknown'}`",
        f"- Git dirty: `{run['git_dirty']}`",
        f"- Configured model: `{run['configured_model']}`",
        f"- Observed model revision(s): `{', '.join(run['observed_models']) or 'none'}`",
        f"- Corpus SHA-256: `{run['corpus']['sha256']}`",
        f"- Cases: `{summary['cases']}` ({summary['completed_cases']} completed, {summary['error_cases']} errors)",
        f"- Calibration / holdout: `{summary['split_counts'].get('calibration', 0)}` / `{summary['split_counts'].get('holdout', 0)}`",
        "",
        "## Core routing result",
        "",
        f"- Raw accuracy: **{_pct(summary['raw_accuracy'])}**",
        f"- Decisive-case accuracy: **{_pct(summary['decisive_accuracy'])}**",
        f"- Ambiguous/unclear recall: **{_pct(summary['ambiguous_unclear_recall'])}**",
        f"- Dangerous authority escalations: **{summary['dangerous_escalations']}**",
        f"- Mean route margin: `{_num(summary['mean_route_margin'])}`",
        f"- Median route margin: `{_num(summary['median_route_margin'])}`",
        "",
        "### Calibration versus untouched holdout",
        "",
        "| Split | Cases | Raw accuracy | Decisive accuracy | Unclear recall | Dangerous escalations |",
        "|---|---:|---:|---:|---:|---:|",
        f"| calibration | {calibration['cases']} | {_pct(calibration['raw_accuracy'])} | {_pct(calibration['decisive_accuracy'])} | {_pct(calibration['ambiguous_unclear_recall'])} | {calibration['dangerous_escalations']} |",
        f"| holdout | {holdout['cases']} | {_pct(holdout['raw_accuracy'])} | {_pct(holdout['decisive_accuracy'])} | {_pct(holdout['ambiguous_unclear_recall'])} | {holdout['dangerous_escalations']} |",
        "",
        "### Per-route precision / recall",
        "",
        "| Route | Support | Precision | Recall |",
        "|---|---:|---:|---:|",
    ]
    for route in ("chat", "assistant", "developer", "unclear"):
        item = summary["per_route"][route]
        lines.append(
            f"| {route} | {item['support']} | {_pct(item['precision'])} | {_pct(item['recall'])} |"
        )

    lines.extend([
        "",
        "### Confusion matrix",
        "",
        "Rows are expected labels; columns are Jev choices.",
        "",
        "| Expected \\ Predicted | chat | assistant | developer | unclear |",
        "|---|---:|---:|---:|---:|",
    ])
    for expected in ("chat", "assistant", "developer", "unclear"):
        row = summary["confusion_matrix"][expected]
        lines.append(
            f"| {expected} | {row['chat']} | {row['assistant']} | {row['developer']} | {row['unclear']} |"
        )

    lines.extend([
        "",
        "### Family-level results",
        "",
        "This table is important for spotting a high aggregate score that hides failure on boundary or adversarial families.",
        "",
        "| Family | Support | Accuracy | Dangerous escalations | Mean margin |",
        "|---|---:|---:|---:|---:|",
    ])
    for family, item in summary["family_metrics"].items():
        lines.append(
            f"| {family} | {item['support']} | {_pct(item['accuracy'])} | {item['dangerous_escalations']} | {_num(item['mean_route_margin'])} |"
        )

    diagnostics = summary["diagnostics"]
    lines.extend([
        "",
        "## Independent diagnostic judgements",
        "",
        "Lower Brier score is better; 0 is perfect.",
        "",
        "| Diagnostic | Brier score |",
        "|---|---:|",
        f"| Ambiguity | {_num(diagnostics['ambiguity_brier'], 4)} |",
        f"| Repository work | {_num(diagnostics['repository_work_brier'], 4)} |",
        f"| Missing repository profile | {_num(diagnostics['missing_repository_profile_brier'], 4)} |",
        f"| Assistant calendar/notification tool need | {_num(diagnostics['assistant_tool_need_brier'], 4)} |",
        "",
        "## Candidate selective-routing operating points",
        "",
        "Candidate rows are selected **only on the calibration split** using a deliberately strict descriptive filter: >=99% accepted decisive accuracy, <=1% ambiguous auto-route rate, zero dangerous escalations, and >=99% developer precision when developer is accepted. The holdout columns are then computed without retuning. These rows are not automatically approved production thresholds.",
        "",
        "| min top p | min margin | max ambiguity p | calibration coverage | calibration accuracy | holdout coverage | holdout accuracy | holdout ambiguous auto-route | holdout escalations | holdout developer precision |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    candidates = summary["candidate_operating_points"]
    if candidates:
        for item in candidates[:10]:
            lines.append(
                "| {min_top_probability:.2f} | {min_margin:.2f} | {max_ambiguity_probability:.2f} | "
                "{calibration_coverage:.2%} | {calibration_accepted_decisive_accuracy:.2%} | "
                "{holdout_coverage:.2%} | {holdout_accepted_decisive_accuracy:.2%} | "
                "{holdout_ambiguous_auto_route_rate:.2%} | {holdout_dangerous_escalations} | "
                "{holdout_developer_precision:.2%} |".format(**item)
            )
    else:
        lines.append("| _none met the strict calibration filter_ | | | | | | | | | |")

    lines.extend([
        "",
        "## Cost and latency",
        "",
        f"- Input tokens: `{usage['input_tokens']}`",
        f"- Output tokens: `{usage['output_tokens']}`",
        f"- Estimated provider cost: **${usage['estimated_cost_usd']:.6f}**",
        f"- Median case duration: `{_num(usage['median_duration_ms'], 1)} ms`",
        "",
        "## Workflow inputs used by the experiment",
        "",
    ])
    for name, route in run["catalog"]["routes"].items():
        lines.extend([
            f"### `{name}`",
            "",
            f"- Operator entrypoint: `{route['operator_entrypoint']}`",
            f"- Workflow: `{route['workflow_id']}` version `{route['version']}`",
            f"- Source: `{route['source_path']}`",
            f"- Source SHA-256: `{route['source_sha256']}`",
            f"- Routing summary: {route['routing_summary']}",
            "",
        ])

    failures = [case for case in run["cases"] if case["error"]]
    misroutes = [
        case for case in run["cases"]
        if not case["error"] and case["expected_route"] != case["predicted_route"]
    ]
    lines.extend([
        "## Errors and misroutes",
        "",
        f"Provider/evaluation errors: `{len(failures)}`. Raw misroutes: `{len(misroutes)}`.",
        "",
    ])
    if failures:
        lines.append("### Provider/evaluation errors")
        lines.append("")
        for case in failures[:25]:
            lines.append(f"- `{case['case_id']}`: {case['error']}")
        lines.append("")
    if misroutes:
        lines.extend([
            "### Misroutes",
            "",
            "| Case | Split | Family | Expected | Predicted | Margin | Ambiguity p | Request |",
            "|---|---|---|---|---|---:|---:|---|",
        ])
        for case in misroutes:
            request = case["request_text"].replace("|", "\\|")
            lines.append(
                f"| {case['case_id']} | {case['split']} | {case['family']} | {case['expected_route']} | "
                f"{case['predicted_route']} | {_num(case['route_margin'])} | "
                f"{_num(case['ambiguous_probability'])} | {request} |"
            )
        lines.append("")

    lines.extend([
        "## Interpretation guardrails",
        "",
        "- A good result supports continuing toward shadow-mode integration; it does not make Jev an authorization boundary.",
        "- Explicit workflow commands should remain deterministic and override semantic advice.",
        "- Production integration should route Jev through Safeplane's model gateway rather than retain this experiment's direct OpenRouter key.",
        "- Inspect matched-pair, route-spoofing, missing-prerequisite, and ambiguous families rather than relying on aggregate accuracy.",
        "- The holdout split reduces threshold overfitting but is still synthetic; a later shadow-mode corpus from real Safeplane traffic is needed before automatic routing.",
        "- Re-run after workflow semantics, Jev model revisions, or corpus policy changes.",
        "",
    ])
    return "\n".join(lines)


def _render_v2(run: dict[str, Any]) -> str:
    summary = run["summary"]
    usage = run["usage"]
    calibration = summary["split_metrics"]["calibration"]
    holdout = summary["split_metrics"]["holdout"]
    lines = [
        "# Safeplane Jev Routing Advisor Evaluation — V2",
        "",
        "> V2 separates workflow selection from execution clarification and multi-workflow composition. This is experiment evidence, not production routing policy.",
        "",
        "## Run identity",
        "",
        f"- Timestamp (UTC): `{run['timestamp_utc']}`",
        f"- Git commit: `{run['git_commit'] or 'unknown'}`",
        f"- Git dirty: `{run['git_dirty']}`",
        f"- Configured model: `{run['configured_model']}`",
        f"- Observed model revision(s): `{', '.join(run['observed_models']) or 'none'}`",
        f"- Corpus version / decision contract: `{run['benchmark_version']}` / `{run['decision_contract']}`",
        f"- Corpus SHA-256: `{run['corpus']['sha256']}`",
        f"- Cases: `{summary['cases']}` ({summary['completed_cases']} completed, {summary['error_cases']} errors)",
        f"- Calibration / fresh holdout: `{summary['split_counts'].get('calibration', 0)}` / `{summary['split_counts'].get('holdout', 0)}`",
        "",
        "## Core route-selection result",
        "",
        f"- Single-workflow route accuracy: **{_pct(summary['single_route_accuracy'])}** over `{summary['single_route_cases']}` cases",
        f"- Raw authority escalations among single-workflow cases: **{summary['dangerous_escalations_raw_single_route']}**",
        f"- Route-unidentifiable cases: `{summary['route_unidentifiable_cases']}`",
        f"- Multi-workflow cases: `{summary['multi_workflow_cases']}`",
        f"- Median route margin: `{_num(summary['median_route_margin'])}`",
        "",
        "### Calibration versus untouched holdout",
        "",
        "| Split | Cases | Single-route cases | Route accuracy | Raw escalations |",
        "|---|---:|---:|---:|---:|",
        f"| calibration | {calibration['cases']} | {calibration['single_route_cases']} | {_pct(calibration['single_route_accuracy'])} | {calibration['dangerous_escalations_raw_single_route']} |",
        f"| holdout | {holdout['cases']} | {holdout['single_route_cases']} | {_pct(holdout['single_route_accuracy'])} | {holdout['dangerous_escalations_raw_single_route']} |",
        "",
        "### Per-route precision / recall",
        "",
        "Precision and recall are measured only on cases where exactly one concrete workflow is expected. V2 abstention-test cases are evaluated separately through the semantic judgements and deterministic policy.",
        "",
        "| Route | Support | Precision | Recall |",
        "|---|---:|---:|---:|",
    ]
    for route in ("chat", "assistant", "developer"):
        item = summary["per_route"][route]
        lines.append(f"| {route} | {item['support']} | {_pct(item['precision'])} | {_pct(item['recall'])} |")

    lines.extend([
        "",
        "### Single-workflow confusion matrix",
        "",
        "Rows are expected routes; columns are Jev's forced three-way route choice. Route-unidentifiable and multi-workflow cases are excluded from this matrix because V2 evaluates their abstention through independent judgements and deterministic policy.",
        "",
        "| Expected \\ Predicted | chat | assistant | developer |",
        "|---|---:|---:|---:|",
    ])
    for expected in ("chat", "assistant", "developer"):
        row = summary["confusion_matrix"][expected]
        lines.append(f"| {expected} | {row['chat']} | {row['assistant']} | {row['developer']} |")

    lines.extend([
        "",
        "## Independent semantic judgements",
        "",
        "Metrics below use a descriptive 0.5 threshold. Brier score measures probability calibration (lower is better; 0 is perfect). Clarification is deliberately not used as a routing-abstention gate.",
        "",
        "| Judgement | Support | Positives | Accuracy | Precision | Recall | Brier |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    labels = {
        "route_identifiable": "Route identifiable",
        "needs_clarification": "Needs clarification before execution",
        "requires_multiple_workflows": "Requires multiple workflows",
        "repository_work": "Repository work",
        "missing_repository_profile": "Missing repository profile",
        "assistant_tool_need": "Assistant calendar/notification action",
    }
    for key, label in labels.items():
        item = summary["diagnostics"][key]
        lines.append(
            f"| {label} | {item['support']} | {item['positives']} | {_pct(item['accuracy'])} | "
            f"{_pct(item['precision'])} | {_pct(item['recall'])} | {_num(item['brier'], 4)} |"
        )

    lines.extend([
        "",
        "## Candidate V2 selective-routing operating points",
        "",
        "Candidates are chosen **only on calibration**. The strict filter requires >=99% accuracy on accepted single-workflow cases, <=1% auto-routing of route-unidentifiable cases, <=1% auto-routing of multi-workflow cases, zero dangerous escalations, and >=99% developer precision. Holdout columns are then calculated without retuning.",
        "",
        "Clarification probability and missing repository-profile probability are intentionally not routing gates: those signals belong to execution readiness after the workflow intent has been identified.",
        "",
        "| min top p | min margin | min identifiable p | max multi p | cal coverage | cal route acc | holdout coverage | holdout route acc | holdout unidentifiable auto-route | holdout multi auto-route | holdout policy accuracy | holdout escalations | holdout dev precision |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    candidates = summary["candidate_operating_points"]
    if candidates:
        for item in candidates[:10]:
            lines.append(
                "| {min_top_probability:.2f} | {min_margin:.2f} | {min_route_identifiable_probability:.2f} | {max_multiple_workflows_probability:.2f} | "
                "{calibration_coverage:.2%} | {calibration_accepted_single_route_accuracy:.2%} | "
                "{holdout_coverage:.2%} | {holdout_accepted_single_route_accuracy:.2%} | "
                "{holdout_route_unidentifiable_auto_route_rate:.2%} | {holdout_multi_workflow_auto_route_rate:.2%} | "
                "{holdout_policy_decision_accuracy:.2%} | {holdout_dangerous_escalations} | {holdout_developer_precision:.2%} |".format(**item)
            )
    else:
        lines.append("| _none met the strict calibration filter_ | | | | | | | | | | | | |")

    lines.extend([
        "",
        "## Family-level results",
        "",
        "| Family | Support | Single-route support | Single-route accuracy | Route-identifiable accuracy | Multi-workflow accuracy | Mean margin |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for family, item in summary["family_metrics"].items():
        lines.append(
            f"| {family} | {item['support']} | {item['single_route_support']} | {_pct(item['single_route_accuracy'])} | "
            f"{_pct(item['route_identifiable_accuracy'])} | {_pct(item['multiple_workflows_accuracy'])} | {_num(item['mean_route_margin'])} |"
        )

    lines.extend([
        "",
        "## Cost and latency",
        "",
        f"- Input tokens: `{usage['input_tokens']}`",
        f"- Output tokens: `{usage['output_tokens']}`",
        f"- Estimated provider cost: **${usage['estimated_cost_usd']:.6f}**",
        f"- Median case duration: `{_num(usage['median_duration_ms'], 1)} ms`",
        "",
        "## Errors and concrete-route misroutes",
        "",
    ])
    failures = [case for case in run["cases"] if case["error"]]
    misroutes = [
        case for case in run["cases"]
        if not case["error"] and case["expected_route"] is not None and case["expected_route"] != case["predicted_route"]
    ]
    lines.append(f"Provider/evaluation errors: `{len(failures)}`. Concrete-route misroutes: `{len(misroutes)}`.")
    lines.append("")
    if failures:
        for case in failures[:25]:
            lines.append(f"- `{case['case_id']}`: {case['error']}")
        lines.append("")
    if misroutes:
        lines.extend([
            "| Case | Split | Family | Expected | Predicted | Margin | Clarification p | Multi p | Request |",
            "|---|---|---|---|---|---:|---:|---:|---|",
        ])
        for case in misroutes:
            request = case["request_text"].replace("|", "\\|")
            lines.append(
                f"| {case['case_id']} | {case['split']} | {case['family']} | {case['expected_route']} | {case['predicted_route']} | "
                f"{_num(case['route_margin'])} | {_num(case['needs_clarification_probability'])} | "
                f"{_num(case['requires_multiple_workflows_probability'])} | {request} |"
            )
        lines.append("")

    lines.extend([
        "## Interpretation guardrails",
        "",
        "- V2's holdout is fresh at the topic level and must not be used to tune prompts, semantics, or thresholds after the first final V2 evaluation.",
        "- A good synthetic result supports shadow-mode integration; it does not make Jev an authorization boundary.",
        "- Explicit workflow commands remain deterministic and override semantic advice.",
        "- Clarification, repository-profile readiness, permissions, approvals, and workflow capabilities remain deterministic harness/workflow concerns.",
        "- Production integration should replace this direct OpenRouter transport with Safeplane's model gateway.",
        "- Final confidence should include repeated frozen V2 runs and then reviewed shadow-mode traffic.",
        "",
    ])
    return "\n".join(lines)


def render_markdown(run: dict[str, Any]) -> str:
    if run.get("decision_contract") == "v2":
        return _render_v2(run)
    return _render_v1(run)


def write_reports(run: dict[str, Any], output_dir: Path, stem: str) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    csv_path = output_dir / f"{stem}.csv"
    json_path.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(run) + "\n", encoding="utf-8")

    fields = [
        "case_id", "split", "family", "decision_type", "expected_route", "predicted_route",
        "route_correct", "dangerous_escalation", "route_confidence", "route_margin",
        "ambiguous_probability", "route_identifiable_probability",
        "needs_clarification_probability", "requires_multiple_workflows_probability",
        "repository_work_probability", "missing_repository_profile_probability",
        "assistant_tool_need_probability", "expected_route_identifiable",
        "expected_needs_clarification", "expected_requires_multiple_workflows",
        "expected_repository_work", "expected_missing_repository_profile",
        "expected_assistant_tool_need", "duration_ms", "input_tokens", "output_tokens",
        "estimated_cost_usd", "error", "request_text",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in run["cases"]:
            writer.writerow({field: case.get(field) for field in fields})
    return md_path, json_path, csv_path

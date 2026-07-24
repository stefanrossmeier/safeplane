# ADR 0018: Run manager is owned by the harness

## Status

Accepted

## Context

Phase 6 introduced explicit run lifecycle tracking.

Before this, Safeplane tracked sessions and turns, but not individual execution attempts.

That was not enough for longer-running workflows, retries, future tool calls, approvals, cancellation, or connector notifications.

A session identifies the conversation.

A turn identifies a user-visible conversation step.

A run identifies one execution attempt for a turn.

The intended model is:

    session
      turn
        run

A later retry will create a new run for the same turn.

## Decision

The harness owns the run manager.

Every connector request creates a run.

Workflow execution is asynchronous internally by default.

The CLI still waits for its own run to complete and prints the result. There is no --no-wait flag in phase 6.

Run records are persisted under:

    SAFEPLANE_HOME/runs/run_<uuid>.json

Run status belongs to the run, not to the session.

Phase 6 uses these statuses:

    queued
    running
    completed
    failed

The schema also reserves later statuses:

    waiting_for_approval
    waiting_for_tool
    cancelling
    cancelled

The CLI output includes run identity and status:

    session: <display-id>
    turn: <number>
    run: run_<uuid>
    status: completed
    trace: <path>

The harness exposes run inspection endpoints:

    GET /runs
    GET /runs/{run_id}

The CLI exposes:

    safeplane runs
    safeplane status <run_id>

Trace paths remain session/turn based:

    SAFEPLANE_HOME/traces/<session_id>/turn_<nnn>

The run id is added as metadata to trace events and output artifacts.

Phase 6 adds a model-free slow workflow for concurrency testing.

The slow workflow exists to prove that one long-running run does not block another session.

## Consequences

Run status is explicit, durable, and inspectable.

The system can distinguish conversation continuity from execution lifecycle.

Future retries can create a new run for the same turn without overwriting failed evidence.

Future cancellation can target a specific run.

Future approvals and tool waits can attach to a specific run.

Future connector notifications can report completion of a specific run.

The CLI remains simple.

Cancellation and crash recovery remain out of scope for phase 6.

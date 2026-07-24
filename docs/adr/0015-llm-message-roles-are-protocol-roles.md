# ADR 0015: LLM message roles are protocol roles, not workflow names

## Status

Accepted

## Context

Phase 3 introduced persisted multi-turn message artifacts.

The artifact contains messages with roles such as:

    system
    user
    assistant

This created possible confusion because Safeplane also plans to have an assistant workflow.

## Decision

Safeplane keeps standard LLM chat message roles.

The role assistant means "previous model response" in the LLM chat protocol.

It does not mean the Safeplane assistant workflow.

Workflow identity is tracked separately with explicit metadata:

    workflow_id
    message_role_schema

Example shape:

    {
      "workflow_id": "chat",
      "message_role_schema": "llm_chat_roles",
      "messages": []
    }

## Consequences

Model-gateway compatibility is preserved.

Trace artifacts remain understandable.

Future workflow names do not conflict with LLM protocol roles.

A Safeplane assistant workflow can still produce messages with role assistant, because that role belongs to the chat-message protocol layer.

# Telegram Connector Setup

The optional Telegram connector runs in its own Docker container and exposes
workflow-registry-backed commands. In the default configuration, the first plain
text message after `/new` asks the harness routing advisor to choose a workflow;
slash commands remain deterministic.

The Telegram connector runs in its own Docker container.

It is not part of the default `make up` stack.

## Architecture

    telegram-connector -> harness -> selected workflow -> model-gateway / MCP services

The connector is intentionally dumb.

It does not own sessions, runs, routing policy, model calls, tools, or workflow
logic. Automatic routing is performed by the harness through the model gateway.

It translates:

    Telegram command -> validated connector request
    Harness workflow result/progress -> Telegram message

## Which Telegram id goes into the allowlist?

Use:

    message.from.id

This is the Telegram user id of the sender.

Do not use only `message.chat.id` for authorization if the goal is to allow one human user.

Safeplane uses the ids like this:

    message.from.id -> authorization: who is allowed to use the bot?
    message.chat.id -> session mapping and reply target: where did the message happen?

In a private 1:1 chat, `from.id` and `chat.id` are usually the same.

In a group, they are different:

    from.id -> the user who sent the message
    chat.id -> the group chat

The recommended setup is a private 1:1 chat with the bot.

## Create a Telegram bot

1. Open Telegram.
2. Start a chat with `@BotFather`.
3. Send `/newbot`.
4. Follow the prompts.
5. Copy the bot token.

Treat the bot token like a password.

## Store the bot token

From the Safeplane repo root:

    make setup
    make secret-set-telegram

Paste the bot token when prompted.

This creates:

    ${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}/telegram_bot_token

Do not put the token into `.env`.

Do not commit the token.

## Get your Telegram user id

Load your bot token into a shell variable without printing it:

    TELEGRAM_BOT_TOKEN="$(cat "${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}/telegram_bot_token")"

Open your bot in Telegram and send:

    /start

Then run:

    curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates"

Look for the message object.

You want the sender id:

    "from": {
      "id": 123456789
    }

That number is your Telegram user id.

For authorization, store this `from.id`.

## Store allowed Telegram user ids

From the Safeplane repo root:

    make secret-set-telegram-users

Paste one or more Telegram user ids.

Allowed formats:

    123456789

or multiple ids:

    123456789,987654321

or one per line:

    123456789
    987654321

This creates:

    ${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}/telegram_allowed_user_ids

If this secret is empty or missing, all Telegram users are rejected.

## Verify secrets without printing them

    ls -l "${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}/telegram_bot_token"
    ls -l "${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}/telegram_allowed_user_ids"

    wc -c "${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}/telegram_bot_token"
    wc -c "${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}/telegram_allowed_user_ids"

## Verify the bot token manually

    curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"

Expected:

    "ok": true

## Disable webhook mode

The connector uses long polling.

If the bot used webhook mode before, remove the webhook:

    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/deleteWebhook" \
      -d "drop_pending_updates=true"

Check:

    curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"

Expected:

    "url": ""

The connector also calls `deleteWebhook` on startup by default, without dropping pending updates.

## Start Safeplane and Telegram

Start the normal local stack:

    make up

Start the Telegram connector:

    make telegram-up

View logs:

    make telegram-logs

Stop only the Telegram connector:

    make telegram-down

## Telegram commands

The harness workflow registry is the source of truth for exposed workflow
commands. Send `/help` for the complete Telegram command reference or
`/workflows` for only the currently exposed workflows. The standard
configuration exposes:

    /chat <message>
    /assistant <message>
    /develop <repository-profile> <task>

The direct commands above are the normal operator interface. An advanced
generic dispatcher is also available for tooling and registry-oriented use:

    /run chat <message>
    /run assistant <message>
    /run develop --repo <repository-profile> <task>

`/run` does not add routing intelligence. It deterministically selects the named
registry entrypoint and forwards the validated arguments. Prefer `/develop`,
`/assistant`, and `/chat` when operating the bot manually.

Connector metadata declares the command, usage, arguments, start mode, and
session-continuation behavior. Internal or disabled entrypoints are omitted from
`/workflows`, and the harness rejects attempts to invoke them through Telegram.

Other commands:

    /start
    /help
    /workflows
    /run <entrypoint> <arguments>
    /new
    /status [run-id]
    /approve_pr [run-id]

Meaning:

    /start, /help
      Show the complete command reference, including workflows, status, session,
      approval, and the advanced generic dispatcher.

    /workflows
      List only registry-exposed workflows and their direct usage.

    /run <entrypoint> <arguments>
      Start one exposed workflow without natural-language routing.

    /chat <message>
      Start or continue the chat workflow for this Telegram chat.

    /assistant <message>
      Start or continue the assistant workflow, including its allowed calendar
      and notification MCP tools. This is always an explicit deterministic route.

    /develop <repository-profile> <task>
      Start the complete fixed developer workflow asynchronously. The connector
      reports completed stage milestones and the final stop or approval-ready
      state.

    /new
      Clear all Telegram-to-workflow session mappings for this chat.

    /status [run-id]
      Show a named run or the latest run mapped to this Telegram chat, including
      developer stage, checks, review verdict, and approval readiness.

    /approve_pr [run-id]
      Explicitly approve the immutable result of an eligible developer run. If
      the run id is omitted, use the latest run mapped to the Telegram chat. The
      harness pushes the deterministic branch and creates or reuses one draft PR.
      Safeplane does not merge it.


## Plain-text automatic routing

With `connectors.telegram.routing_mode: automatic`, a plain-text message after
`/new` is sent to the harness `auto` entrypoint. The harness asks Jev through the
model gateway, applies the fixed routing policy, and resolves only an enabled,
Telegram-exposed registry entrypoint. The connector never interprets model output.

After a route is accepted, later plain-text messages remain bound to that workflow
session until `/new`. This preserves workflow/session continuity and prevents each
follow-up from being reclassified without conversation context. Use `/new` to ask
the advisor to route the next plain-text message again, or use `/chat`, `/assistant`,
or `/develop` at any time for deterministic routing.

If the advisor abstains, the provider is unavailable, or a selected developer task
lacks repository context, Safeplane does not silently choose a more capable route.
The operator must use an explicit command or supply the missing repository profile.

## Session mapping

The connector stores separate Telegram-chat mappings for each continuable
workflow under:

    SAFEPLANE_HOME/connectors/telegram/sessions.json

The outer mapping key uses `message.chat.id`; workflow sessions are keyed by
workflow id. Chat and assistant continuation therefore do not overwrite one
another. The harness still owns the authoritative session and run records.

## Event log

The connector writes local events to:

    SAFEPLANE_HOME/connectors/telegram/events.jsonl

The event log records both:

    telegram_from_user_id
    telegram_chat_id

This makes authorization and session mapping debuggable.

## Manual workflow-command smoke test

1. Start the local stack and Telegram connector:

       make up
       make telegram-up

2. Open the bot and send `/workflows`. Confirm that chat, assistant, and develop
   are listed, while internal workflows are absent.

3. Send `/help` and confirm that all workflow and control commands are listed.

4. Send direct workflow commands:

       /chat Say hello from chat
       /assistant List my calendar entries for today

   The advanced `/run` equivalents may be checked separately, but are not the
   preferred manual interface.

5. Confirm plain text still uses the configured default assistant workflow.

6. Start a bounded developer task with a configured fixture or test profile:

       /develop <repository-profile> <task>

   The advanced generic equivalent is:

       /run develop --repo <repository-profile> <task>

7. Confirm progress messages, then inspect the run:

       /status

8. For a profile that requires explicit remote approval, verify `/approve_pr`
   only after inspecting the immutable run result. Safeplane must return a draft
   PR URL and must not merge it.

9. Inspect local records:

       ./scripts/safeplane runs
       tail -n 20 "${SAFEPLANE_HOME:-$HOME/.safeplane}/connectors/telegram/events.jsonl"
       cat "${SAFEPLANE_HOME:-$HOME/.safeplane}/connectors/telegram/sessions.json"

The automated fake-boundary acceptance is:

    tests/scripts/accept-telegram-workflows

The primary guarded real Telegram acceptance does not start developer services:

    tests/scripts/validate-real-telegram-workflows

It verifies bot authentication and successful long polling, then asks the
operator to prove `/help`, `/assistant`, and `/chat`. On failure it prints the
connector event stream plus Telegram and harness logs.

The developer path is a separate secondary acceptance:

    SAFEPLANE_REAL_TELEGRAM_PROFILE=<profile> \
    SAFEPLANE_REAL_TELEGRAM_TASK='<bounded task>' \
    tests/scripts/validate-real-telegram-developer-workflow

Run the secondary acceptance only after the primary smoke is green. It starts
the developer MCP services, asks for `/develop`, and verifies that checks pass
and review returns `LGTM`.

## Troubleshooting

If the bot says the user is not authorized, check that you stored `message.from.id`, not only `message.chat.id`.

Inspect recent updates:

    curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates"

Look for:

    "from": {
      "id": ...
    }

Then update the allowlist:

    make secret-set-telegram-users

If the bot does not answer, first inspect the connector event stream and look
for `bot_authenticated`, `polling_ready`, `message_rejected`, `polling_failed`,
or `update_handling_failed`:

    tail -n 60 "${SAFEPLANE_HOME:-$HOME/.safeplane}/connectors/telegram/events.jsonl"

Then inspect logs:

    make telegram-logs

A Telegram API conflict such as HTTP 409 usually means another process is using
`getUpdates` with the same bot token. Stop the other poller before retrying.

Check secrets:

    ls -l "${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}/telegram_bot_token"
    ls -l "${SAFEPLANE_SECRET_ROOT:-$HOME/.config/safeplane/secrets}/telegram_allowed_user_ids"

Check connector events:

    tail -f "${SAFEPLANE_HOME:-$HOME/.safeplane}/connectors/telegram/events.jsonl"

If `getUpdates` returns no messages, delete the webhook:

    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/deleteWebhook" \
      -d "drop_pending_updates=true"

## Outbound notification delivery

The Telegram connector owns all Telegram credentials. The scheduler must not read Telegram bot tokens or chat IDs directly.

Notification delivery flow:

    scheduler
    -> internal HTTP request to telegram-connector
    -> telegram-connector reads Telegram secrets
    -> telegram-connector calls Telegram API
    -> scheduler records delivery result

The Telegram connector exposes an internal HTTP endpoint for outbound notifications:

    GET  /health
    POST /notifications/send

The endpoint is intended for internal Compose-network use only.

Expected request shape:

    {
      "notification_id": "notif_sched_...",
      "outbox_id": "notif_outbox_...",
      "message": "Message text"
    }

The connector sends the message to configured Telegram notification chat IDs.

Configuration is owned by the Telegram connector:

    TELEGRAM_BOT_TOKEN_FILE=/run/secrets/telegram_bot_token
    TELEGRAM_ALLOWED_USER_IDS_FILE=/run/secrets/telegram_allowed_user_ids
    TELEGRAM_NOTIFICATION_CHAT_IDS_FILE=/run/secrets/telegram_allowed_user_ids

For a private single-operator setup, TELEGRAM_ALLOWED_USER_IDS_FILE is reused as the default notification target list. This works for private chats where Telegram user ID and chat ID are the same. Later, group/channel delivery can use a dedicated TELEGRAM_NOTIFICATION_CHAT_IDS_FILE.

The scheduler only needs connector routing configuration:

    SAFEPLANE_NOTIFICATION_CONNECTORS=log,telegram
    SAFEPLANE_TELEGRAM_CONNECTOR_URL=http://telegram-connector:8080

Run the real Telegram smoke manually with:

    tests/scripts/validate-real-telegram-notifications

This smoke is intentionally not part of tests/scripts/accept-notification-stack, because it sends a real Telegram message and requires local Telegram secrets.

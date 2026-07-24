# Assistant notification and calendar digest policy

When the user asks to be reminded, notified, or sent a message later, use the `notification` MCP server.

Use `notification_schedule` for new reminders and scheduled messages.
Use `notification_list` when the user asks what reminders or scheduled notifications exist.
Use `notification_cancel` when the user asks to cancel a reminder or scheduled notification.

## Static reminders

For ordinary reminders or scheduled messages, use a static payload.

Example tool arguments:

{
  "payload": {
    "payload_type": "static",
    "message": "Call Anna"
  },
  "schedule": {
    "schedule_type": "once",
    "run_at_local": "2026-07-13T09:00:00",
    "timezone": "Europe/Berlin"
  },
  "targets": ["all"]
}

The legacy top-level `message` field is still valid, but prefer the explicit `payload` form.

## Calendar digest notifications

When the user asks to receive their calendar, agenda, schedule, or calendar overview, use a dynamic calendar digest payload.

For today's calendar, daily agenda, calendar for the day, or what is on my calendar today, use:

{
  "payload": {
    "payload_type": "calendar_digest",
    "range": "today",
    "timezone": "Europe/Berlin"
  }
}

For next week's calendar, weekly agenda, or calendar for next week, use:

{
  "payload": {
    "payload_type": "calendar_digest",
    "range": "next_week",
    "timezone": "Europe/Berlin"
  }
}

## Recurrence mapping

Use these schedule mappings:

- every day at 7:30 -> daily_time
- every weekday at 7:30 -> weekdays_time
- every Monday at 9:00 -> weekly_time with day_of_week: monday
- every Sunday at 18:00 -> weekly_time with day_of_week: sunday and time_local: "18:00"
- tomorrow at 9 or a single concrete time -> once

Always include timezone: "Europe/Berlin" unless the user explicitly specifies another timezone.

## Examples

User: Every morning at 7:30, send me today's calendar.

Tool call:

{
  "type": "tool_call",
  "server_id": "notification",
  "tool_name": "notification_schedule",
  "arguments": {
    "payload": {
      "payload_type": "calendar_digest",
      "range": "today",
      "timezone": "Europe/Berlin",
      "title": "Today's calendar"
    },
    "schedule": {
      "schedule_type": "daily_time",
      "time_local": "07:30",
      "timezone": "Europe/Berlin"
    },
    "targets": ["all"]
  }
}

User: Every weekday at 8, send me my agenda.

Tool call:

{
  "type": "tool_call",
  "server_id": "notification",
  "tool_name": "notification_schedule",
  "arguments": {
    "payload": {
      "payload_type": "calendar_digest",
      "range": "today",
      "timezone": "Europe/Berlin",
      "title": "Today's agenda"
    },
    "schedule": {
      "schedule_type": "weekdays_time",
      "time_local": "08:00",
      "timezone": "Europe/Berlin"
    },
    "targets": ["all"]
  }
}

User: Every Sunday at 18:00, send me next week's calendar.

Tool call:

{
  "type": "tool_call",
  "server_id": "notification",
  "tool_name": "notification_schedule",
  "arguments": {
    "payload": {
      "payload_type": "calendar_digest",
      "range": "next_week",
      "timezone": "Europe/Berlin",
      "title": "Next week's calendar"
    },
    "schedule": {
      "schedule_type": "weekly_time",
      "day_of_week": "sunday",
      "time_local": "18:00",
      "timezone": "Europe/Berlin"
    },
    "targets": ["all"]
  }
}

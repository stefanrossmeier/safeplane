from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator


DEFAULT_NOTIFICATION_TIMEZONE = "Europe/Berlin"
DEFAULT_ONCE_GRACE_SECONDS = 21600
DEFAULT_RECURRING_GRACE_SECONDS = 1800


class NotificationReloadInfo(BaseModel):
    status: Literal["ok", "failed", "not_requested"]
    warning: str | None = None


class NotificationOnceScheduleSpec(BaseModel):
    schedule_type: Literal["once"] = "once"
    run_at_local: str
    timezone: str = DEFAULT_NOTIFICATION_TIMEZONE


class NotificationDailyTimeScheduleSpec(BaseModel):
    schedule_type: Literal["daily_time"] = "daily_time"
    time_local: str = Field(description="Local time in HH:MM format")
    timezone: str = DEFAULT_NOTIFICATION_TIMEZONE


class NotificationWeeklyTimeScheduleSpec(BaseModel):
    schedule_type: Literal["weekly_time"] = "weekly_time"
    day_of_week: Literal[
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    time_local: str = Field(description="Local time in HH:MM format")
    timezone: str = DEFAULT_NOTIFICATION_TIMEZONE


class NotificationWeekdaysTimeScheduleSpec(BaseModel):
    schedule_type: Literal["weekdays_time"] = "weekdays_time"
    time_local: str = Field(description="Local time in HH:MM format")
    timezone: str = DEFAULT_NOTIFICATION_TIMEZONE


NotificationScheduleSpec = Annotated[
    Union[
        NotificationOnceScheduleSpec,
        NotificationDailyTimeScheduleSpec,
        NotificationWeeklyTimeScheduleSpec,
        NotificationWeekdaysTimeScheduleSpec,
    ],
    Field(discriminator="schedule_type"),
]


class NotificationStaticPayload(BaseModel):
    payload_type: Literal["static"] = "static"
    message: str


class NotificationCalendarDigestPayload(BaseModel):
    payload_type: Literal["calendar_digest"] = "calendar_digest"
    range: Literal["today", "next_week"]
    timezone: str = DEFAULT_NOTIFICATION_TIMEZONE
    title: str | None = None


NotificationPayload = Annotated[
    Union[
        NotificationStaticPayload,
        NotificationCalendarDigestPayload,
    ],
    Field(discriminator="payload_type"),
]


class NotificationScheduleToolInput(BaseModel):
    message: str | None = None
    payload: NotificationPayload | None = None
    schedule: NotificationScheduleSpec
    targets: list[str] = Field(default_factory=lambda: ["all"])
    grace_seconds: int | None = None

    @model_validator(mode="after")
    def normalize_payload(self) -> "NotificationScheduleToolInput":
        if self.message is None and self.payload is None:
            raise ValueError("notification_schedule requires message or payload")

        if self.payload is None and self.message is not None:
            self.payload = NotificationStaticPayload(message=self.message)

        if self.message is None and self.payload is not None:
            if self.payload.payload_type == "static":
                self.message = self.payload.message
            elif self.payload.payload_type == "calendar_digest":
                label = "today" if self.payload.range == "today" else "next week"
                self.message = self.payload.title or f"Calendar digest: {label}"

        return self


class NotificationScheduleRecord(BaseModel):
    id: str
    status: Literal["active", "cancelled", "expired"]
    created_at: str
    updated_at: str
    message: str
    payload: NotificationPayload | None = None
    schedule: NotificationScheduleSpec
    targets: list[str]
    grace_seconds: int
    next_run_at_utc: str


class NotificationScheduleToolOutput(BaseModel):
    notification_id: str
    status: Literal["active", "cancelled", "expired"]
    next_run_at_utc: str
    reload: NotificationReloadInfo


class NotificationListToolInput(BaseModel):
    include_cancelled: bool = False


class NotificationListToolOutput(BaseModel):
    notifications: list[NotificationScheduleRecord]


class NotificationCancelToolInput(BaseModel):
    notification_id: str


class NotificationCancelToolOutput(BaseModel):
    notification_id: str
    status: Literal["cancelled", "not_found"]
    reload: NotificationReloadInfo


class NotificationOutboxRecord(BaseModel):
    id: str
    schedule_id: str
    due_at_utc: str
    status: Literal["pending", "sent", "failed", "expired"]
    message: str
    targets: list[str]
    created_at: str
    updated_at: str
    sent_at: str | None = None
    error: str | None = None


class NotificationDeliveryRecord(BaseModel):
    id: str
    outbox_id: str
    schedule_id: str
    connector: str
    status: Literal["pending", "sent", "failed"]
    attempt: int
    started_at: str
    finished_at: str | None = None
    error: str | None = None


NOTIFICATION_TOOL_SCHEMAS = {
    "notification_schedule": {
        "input_model": NotificationScheduleToolInput,
        "output_model": NotificationScheduleToolOutput,
    },
    "notification_list": {
        "input_model": NotificationListToolInput,
        "output_model": NotificationListToolOutput,
    },
    "notification_cancel": {
        "input_model": NotificationCancelToolInput,
        "output_model": NotificationCancelToolOutput,
    },
}

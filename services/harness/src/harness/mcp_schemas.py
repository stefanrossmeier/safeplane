from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Dict, List, Literal, NamedTuple, Optional, Type
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator
from harness.notification_schemas import NOTIFICATION_TOOL_SCHEMAS
from harness.dev_workspace_schemas import DEV_WORKSPACE_TOOL_SCHEMAS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def validate_model(model_type: Type[BaseModel], data: Any) -> BaseModel:
    return model_type.model_validate(data)


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    return model.model_dump()


def parse_aware_iso_datetime(value: str, field_name: str) -> datetime:
    normalized = value.strip()

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    parsed = datetime.fromisoformat(normalized)

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")

    return parsed


class McpBrokerRequest(StrictModel):
    workflow_id: str
    server_id: str
    tool_name: str
    arguments: Dict[str, Any]

    session_id: Optional[str] = None
    turn: Optional[int] = None
    run_id: Optional[str] = None
    connector: Optional[str] = None
    tool_call_id: Optional[str] = None
    agent_id: Optional[str] = None
    approval_id: Optional[str] = None
    approval_token: Optional[str] = None

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not re.fullmatch(r"run_[A-Za-z0-9._-]+", value):
            raise ValueError("run_id contains unsafe characters")
        return value

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise ValueError("agent_id contains unsafe characters")
        return value

    @field_validator("approval_id")
    @classmethod
    def validate_approval_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not re.fullmatch(r"patch_approval_[A-Za-z0-9._-]+", value):
            raise ValueError("approval_id contains unsafe characters")
        return value


class McpBrokerResponse(StrictModel):
    server_id: str
    tool_name: str
    structured_content: Dict[str, Any]
    is_error: bool = False


class CalendarEvent(StrictModel):
    id: str
    title: str
    start: str
    end: str
    timezone: str
    description: str = ""
    status: str
    created_at: str
    updated_at: str


class CalendarListInput(StrictModel):
    range_type: Literal["day", "week"]
    date: str
    timezone: str = "Europe/Berlin"
    include_cancelled: bool = False

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value


class CalendarListOutput(StrictModel):
    events: List[CalendarEvent]


class CalendarCreateInput(StrictModel):
    title: str
    start: str
    end: str
    timezone: str = "Europe/Berlin"
    description: str = ""

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("start")
    @classmethod
    def validate_start(cls, value: str) -> str:
        parse_aware_iso_datetime(value, "start")
        return value

    @field_validator("end")
    @classmethod
    def validate_end(cls, value: str) -> str:
        parse_aware_iso_datetime(value, "end")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "CalendarCreateInput":
        start = parse_aware_iso_datetime(self.start, "start")
        end = parse_aware_iso_datetime(self.end, "end")

        if start >= end:
            raise ValueError("start must be before end")

        return self


class CalendarCreateOutput(StrictModel):
    event: CalendarEvent


class CalendarCancelInput(StrictModel):
    event_id: str

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        if not value.startswith("cal_evt_"):
            raise ValueError("event_id must start with cal_evt_")
        return value


class CalendarCancelOutput(StrictModel):
    event: CalendarEvent


class ToolSchema(NamedTuple):
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]


TOOL_SCHEMAS: Dict[str, ToolSchema] = {
    "calendar_list": ToolSchema(CalendarListInput, CalendarListOutput),
    "calendar_create": ToolSchema(CalendarCreateInput, CalendarCreateOutput),
    "calendar_cancel": ToolSchema(CalendarCancelInput, CalendarCancelOutput),
}


def validate_tool_input(tool_name: str, arguments: Dict[str, Any]) -> BaseModel:
    if tool_name not in TOOL_SCHEMAS:
        raise ValueError(f"Unknown MCP tool: {tool_name}")

    return validate_model(TOOL_SCHEMAS[tool_name].input_model, arguments)


def validate_tool_output(tool_name: str, structured_content: Dict[str, Any]) -> BaseModel:
    if tool_name not in TOOL_SCHEMAS:
        raise ValueError(f"Unknown MCP tool: {tool_name}")

    return validate_model(TOOL_SCHEMAS[tool_name].output_model, structured_content)


def is_pydantic_validation_error(exc: BaseException) -> bool:
    return isinstance(exc, ValidationError)


# Notification and developer-workspace tool schemas extend the original
# calendar schema registry while keeping the broker validation path generic.
EXTENSION_TOOL_SCHEMAS: Dict[str, Dict[str, Type[BaseModel]]] = {
    **NOTIFICATION_TOOL_SCHEMAS,
    **DEV_WORKSPACE_TOOL_SCHEMAS,
}

_original_validate_tool_input = validate_tool_input
_original_validate_tool_output = validate_tool_output


def validate_tool_input(tool_name: str, payload: dict[str, Any]) -> BaseModel:
    extension_schema = EXTENSION_TOOL_SCHEMAS.get(tool_name)
    if extension_schema:
        return extension_schema["input_model"].model_validate(payload)

    return _original_validate_tool_input(tool_name, payload)


def validate_tool_output(tool_name: str, payload: dict[str, Any]) -> BaseModel:
    extension_schema = EXTENSION_TOOL_SCHEMAS.get(tool_name)
    if extension_schema:
        return extension_schema["output_model"].model_validate(payload)

    return _original_validate_tool_output(tool_name, payload)

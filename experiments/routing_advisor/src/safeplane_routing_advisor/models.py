from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ConcreteRoute = Literal["chat", "assistant", "developer"]
Route = Literal["chat", "assistant", "developer", "unclear"]
DecisionType = Literal["decisive", "ambiguous", "route_unidentifiable", "multi_workflow"]
Split = Literal["calibration", "holdout"]


class CorpusMetadata(BaseModel):
    corpus_name: str
    corpus_version: str
    status: Literal["draft", "frozen"]
    frozen_on: str
    description: str
    generation: str
    case_count: int
    split_policy: str
    decision_contract: str = "v1"


class EvaluationCase(BaseModel):
    case_id: str
    request_text: str
    expected_route: Route | None
    decision_type: DecisionType
    split: Split
    family: str
    rationale: str
    tags: list[str] = Field(default_factory=list)
    pair_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    # V1 labels.
    expected_ambiguous: bool = False

    # Shared / V2 labels.
    expected_repository_work: bool | None = False
    expected_missing_repository_profile: bool | None = False
    expected_assistant_tool_need: bool | None = False
    expected_route_identifiable: bool | None = None
    expected_needs_clarification: bool | None = None
    expected_requires_multiple_workflows: bool | None = None

    @model_validator(mode="after")
    def validate_semantics(self) -> "EvaluationCase":
        if self.expected_route == "unclear" and not self.expected_ambiguous:
            raise ValueError("unclear cases must set expected_ambiguous=true")
        if self.decision_type in {"route_unidentifiable", "multi_workflow"} and self.expected_route is not None:
            raise ValueError(f"{self.decision_type} cases must use expected_route=null")
        if self.expected_route is None and self.decision_type not in {"route_unidentifiable", "multi_workflow"}:
            raise ValueError("expected_route=null is reserved for V2 abstention cases")
        return self


class EvaluationSuite(BaseModel):
    metadata: CorpusMetadata
    cases: list[EvaluationCase]

    @model_validator(mode="after")
    def validate_suite(self) -> "EvaluationSuite":
        if len(self.cases) != self.metadata.case_count:
            raise ValueError("metadata.case_count does not match corpus length")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate case_id in corpus")
        texts = [case.request_text.strip().casefold() for case in self.cases]
        if len(texts) != len(set(texts)):
            raise ValueError("duplicate request_text in corpus")

        if self.metadata.decision_contract == "v1":
            for case in self.cases:
                if case.expected_route is None:
                    raise ValueError("V1 cases require an expected route")
                if case.decision_type == "ambiguous" and case.expected_route != "unclear":
                    raise ValueError("V1 ambiguous cases must use expected_route='unclear'")
        elif self.metadata.decision_contract == "v2":
            for case in self.cases:
                if case.expected_route == "unclear":
                    raise ValueError("V2 does not use unclear as a route label")
                if case.expected_route is not None and case.expected_route_identifiable is not True:
                    raise ValueError("V2 concrete routes must set expected_route_identifiable=true")
                if case.decision_type == "route_unidentifiable" and case.expected_route_identifiable is not False:
                    raise ValueError("route_unidentifiable cases must set expected_route_identifiable=false")
                if case.decision_type == "multi_workflow":
                    if case.expected_route_identifiable is not True:
                        raise ValueError("multi_workflow cases must identify the relevant workflow intents")
                    if case.expected_requires_multiple_workflows is not True:
                        raise ValueError("multi_workflow cases must set expected_requires_multiple_workflows=true")
        else:
            raise ValueError(f"unknown decision_contract: {self.metadata.decision_contract}")
        return self


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class JevAssessment(BaseModel):
    model: str
    provider: str | None = None
    route: Route
    route_confidence: float
    route_probabilities: dict[str, float]

    # V1 signal.
    ambiguous_probability: float | None = None

    # V2 signals.
    route_identifiable_probability: float | None = None
    needs_clarification_probability: float | None = None
    requires_multiple_workflows_probability: float | None = None

    # Shared signals.
    repository_work_probability: float
    missing_repository_profile_probability: float
    assistant_tool_need_probability: float
    usage: Usage = Field(default_factory=Usage)
    raw_id: str | None = None

    @field_validator(
        "route_confidence",
        "ambiguous_probability",
        "route_identifiable_probability",
        "needs_clarification_probability",
        "requires_multiple_workflows_probability",
        "repository_work_probability",
        "missing_repository_profile_probability",
        "assistant_tool_need_probability",
    )
    @classmethod
    def validate_probability(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("probability must be between 0 and 1")
        return value

    @field_validator("route_probabilities")
    @classmethod
    def validate_probabilities(cls, value: dict[str, float]) -> dict[str, float]:
        valid_sets = [
            {"chat", "assistant", "developer"},
            {"chat", "assistant", "developer", "unclear"},
        ]
        if set(value) not in valid_sets:
            raise ValueError("route probabilities must contain the V1 or V2 route set")
        if any(prob < 0.0 or prob > 1.0 for prob in value.values()):
            raise ValueError("route probabilities must be between 0 and 1")
        total = sum(value.values())
        if not 0.98 <= total <= 1.02:
            raise ValueError(f"route probabilities must sum to approximately 1, got {total}")
        return value

    @property
    def top_probability(self) -> float:
        return max(self.route_probabilities.values())

    @property
    def second_probability(self) -> float:
        return sorted(self.route_probabilities.values(), reverse=True)[1]

    @property
    def route_margin(self) -> float:
        return self.top_probability - self.second_probability


class CaseResult(BaseModel):
    case_id: str
    request_text: str
    context: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    family: str
    tags: list[str]
    pair_id: str | None
    decision_type: DecisionType
    split: Split
    expected_route: Route | None
    predicted_route: Route | None = None
    route_probabilities: dict[str, float] = Field(default_factory=dict)
    route_confidence: float | None = None
    route_margin: float | None = None

    ambiguous_probability: float | None = None
    route_identifiable_probability: float | None = None
    needs_clarification_probability: float | None = None
    requires_multiple_workflows_probability: float | None = None
    repository_work_probability: float | None = None
    missing_repository_profile_probability: float | None = None
    assistant_tool_need_probability: float | None = None

    expected_ambiguous: bool = False
    expected_route_identifiable: bool | None = None
    expected_needs_clarification: bool | None = None
    expected_requires_multiple_workflows: bool | None = None
    expected_repository_work: bool | None = False
    expected_missing_repository_profile: bool | None = False
    expected_assistant_tool_need: bool | None = False

    route_correct: bool | None = None
    dangerous_escalation: bool | None = None
    duration_ms: float | None = None
    model: str | None = None
    provider: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    error: str | None = None


class WorkflowRoute(BaseModel):
    name: ConcreteRoute
    workflow_id: str
    operator_entrypoint: str
    source_path: str
    source_sha256: str
    version: str
    description: str
    examples: list[str]
    mcp_servers: list[str]
    deterministic_tools: list[str]
    routing_summary: str
    positive_signals: list[str]
    negative_signals: list[str]

    def criterion_text(self) -> str:
        pieces = [
            self.routing_summary,
            f"Workflow description: {self.description}",
            f"Positive signals: {'; '.join(self.positive_signals)}",
            f"Do not use when: {'; '.join(self.negative_signals)}",
        ]
        if self.mcp_servers:
            pieces.append(f"Available MCP servers: {', '.join(self.mcp_servers)}")
        if self.deterministic_tools:
            pieces.append(f"Deterministic tools: {', '.join(self.deterministic_tools)}")
        return " ".join(pieces)


class WorkflowCatalog(BaseModel):
    safeplane_yaml_sha256: str
    semantics_sha256: str
    semantics_version: int = 1
    routes: dict[str, WorkflowRoute]
    route_instructions: str

    # V1.
    unclear_summary: str | None = None
    ambiguity_instructions: str | None = None

    # V2.
    route_identifiable_instructions: str | None = None
    needs_clarification_instructions: str | None = None
    requires_multiple_workflows_instructions: str | None = None

    # Shared.
    repository_work_instructions: str
    missing_repository_profile_instructions: str
    assistant_tool_need_instructions: str

    model_config = ConfigDict(arbitrary_types_allowed=True)

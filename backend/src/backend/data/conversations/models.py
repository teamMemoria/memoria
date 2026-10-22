from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


NonEmptyString = Annotated[str, Field(min_length=1)]
PositiveInteger = Annotated[int, Field(gt=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HarperValleyBankSource(StrictModel):
    dataset: Literal["HarperValleyBank"]
    original_id: NonEmptyString
    licence: NonEmptyString
    url: NonEmptyString
    citation: NonEmptyString


class HarperValleyBankTurn(StrictModel):
    n: PositiveInteger
    speaker: Literal["agent", "customer"]
    text: str
    asr_text: str | None = None
    start_ms: int | None = None
    duration_ms: int | None = None
    dialog_acts: list[str] | None = None

    @field_validator("asr_text", "start_ms", "duration_ms", "dialog_acts", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("must be omitted rather than null")
        return value


class HarperValleyBankSourceFields(StrictModel):
    task_assigned: Annotated[list[NonEmptyString], Field(min_length=1)]
    task_logged_by_agent: list[NonEmptyString]
    labels: dict[str, JsonValue]
    session: NonEmptyString
    agent_survey_response: dict[str, JsonValue] | None = None
    customer_survey_response: dict[str, JsonValue] | None = None

    @field_validator(
        "agent_survey_response", "customer_survey_response", mode="before"
    )
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("must be omitted rather than null")
        return value


class HarperValleyBankConversation(StrictModel):
    id: NonEmptyString
    source: HarperValleyBankSource
    modifications: list[JsonValue]
    channel: Literal["voice"]
    turns: Annotated[list[HarperValleyBankTurn], Field(min_length=1)]
    source_fields: HarperValleyBankSourceFields
    agent_id: NonEmptyString | None = None
    customer_id: NonEmptyString | None = None
    customer_record: dict[str, JsonValue] | None = None

    @field_validator("agent_id", "customer_id", "customer_record", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("must be omitted rather than null")
        return value

    @field_validator("turns")
    @classmethod
    def require_increasing_turn_numbers(
        cls, turns: list[HarperValleyBankTurn]
    ) -> list[HarperValleyBankTurn]:
        if any(current.n <= previous.n for previous, current in zip(turns, turns[1:])):
            raise ValueError("turn numbers must be strictly increasing")
        return turns


class ABCDSource(StrictModel):
    dataset: Literal["ABCD"]
    original_id: NonEmptyString
    licence: NonEmptyString
    url: NonEmptyString
    citation: NonEmptyString


class ABCDTurn(StrictModel):
    n: PositiveInteger
    speaker: Literal["agent", "customer", "system_action"]
    text: str


class ABCDSourceFields(StrictModel):
    flow: NonEmptyString
    subflow: NonEmptyString
    actions_taken: list[NonEmptyString]


class ABCDConversation(StrictModel):
    id: NonEmptyString
    source: ABCDSource
    modifications: list[JsonValue]
    channel: Literal["chat"]
    turns: Annotated[list[ABCDTurn], Field(min_length=1)]
    source_fields: ABCDSourceFields
    customer_id: NonEmptyString | None = None
    customer_record: dict[str, JsonValue] | None = None

    @field_validator("customer_id", "customer_record", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("must be omitted rather than null")
        return value

    @field_validator("turns")
    @classmethod
    def require_increasing_turn_numbers(cls, turns: list[ABCDTurn]) -> list[ABCDTurn]:
        if any(current.n <= previous.n for previous, current in zip(turns, turns[1:])):
            raise ValueError("turn numbers must be strictly increasing")
        return turns


Conversation = HarperValleyBankConversation | ABCDConversation


class _DispatchSource(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    dataset: Literal["HarperValleyBank", "ABCD"]


class _DispatchEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    source: _DispatchSource


def parse_conversation(payload: object) -> Conversation:
    envelope = _DispatchEnvelope.model_validate(payload)
    if envelope.source.dataset == "HarperValleyBank":
        return HarperValleyBankConversation.model_validate(payload)
    return ABCDConversation.model_validate(payload)

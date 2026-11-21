from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Base for every response schema.

    Python code uses snake_case; JSON uses camelCase so responses match the
    frontend types exactly. Unknown fields are rejected so fixtures cannot
    drift from the contract unnoticed.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .router import RoutingPreference


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    routing: RoutingPreference | None = None
    model: str | None = Field(default=None, max_length=255)
    reasoning_effort: Literal["minimal", "low"] | None = None
    message: str = Field(min_length=1, max_length=12000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=3)
    search_enabled: bool = False
    explanation_mode: Literal["standard", "simple"] = "standard"


    @model_validator(mode="after")
    def one_selection_contract(self):
        if self.model and self.routing is not None:
            raise ValueError("Use routing or legacy model selection, not both")
        return self

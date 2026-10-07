"""App Status input models."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field


class Mode(StrEnum):
    COMMON = "common"
    FULL = "full"


class ShowAppStatusInput(BaseModel):
    """Input for the app status endpoint."""

    mode: Annotated[
        str,
        Field(
            title="Response mode",
            description="How detailed will the response be",
            examples=[Mode.COMMON.name, Mode.FULL.name],
        ),
    ]

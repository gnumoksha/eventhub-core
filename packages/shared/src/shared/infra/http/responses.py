from typing import Annotated

from pydantic import BaseModel, Field


class SuccessOutput(BaseModel):
    success: Annotated[
        bool,
        Field(
            description="Whether the response was successful or not",
            examples=[True, False],
        ),
    ]

    message: Annotated[
        str | None,
        Field(
            description="The response message",
            examples=["User created successfully", "User not found"],
        ),
    ]

"""App Status output models."""

from typing import Annotated, Any

from pydantic import BaseModel, Field


class AppOutput(BaseModel):
    """The "app" node part for the app status endpoint."""

    env: Annotated[
        str,
        Field(
            description="The environment where the application is running",
            examples=["development", "staging", "production"],
        ),
    ]

    version: Annotated[
        str,
        Field(
            description="The application version",
            examples=["none", "2024-04-05_101647"],
        ),
    ]


class ShowAppStatusOutput(BaseModel):
    """Output for the app status endpoint."""

    success: Annotated[
        bool,
        Field(
            description="Whether the response was successful or not",
            examples=[True, False],
        ),
    ]

    app: AppOutput

    services: Annotated[
        dict[str, Any] | None,
        Field(
            description="A dictionary with the status of the services",
            examples=[
                {
                    "database": {
                        "success": True,
                        "exception": None,
                        "duration": 0.00043981200724374503,
                    },
                },
                {
                    "cache": {
                        "success": False,
                        "exception": "Some exception message",
                        "duration": 0.1,
                    },
                },
            ],
        ),
    ]

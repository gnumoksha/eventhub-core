from typing import Annotated

from fastapi import Request

from shared.infra.app_status.inputs import ShowAppStatusInput
from shared.infra.di import Depends


class AppStatusInputTransformer:
    """
    Transform the request into a ShowAppStatusInput.
    It is just an example of a transformer.
    """

    def __call__(self, req: Request) -> ShowAppStatusInput:
        return ShowAppStatusInput(
            mode=req.query_params.get("mode", "common"),
        )


def get_app_status_input_transformer() -> AppStatusInputTransformer:
    return AppStatusInputTransformer()


AppStatusInputTransformerDep = Annotated[AppStatusInputTransformer, Depends(get_app_status_input_transformer)]

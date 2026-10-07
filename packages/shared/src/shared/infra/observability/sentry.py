from collections.abc import Callable
from typing import Any

import sentry_sdk
from sentry_sdk.integrations import Integration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from shared.settings import settings


def initialize_sentry(
    *,
    include_http_integrations: bool = False,
    traces_sampler: Callable[[dict[str, Any]], float] | None = None,
) -> None:
    if not settings.is_prod_like():
        return

    integrations: list[Integration] = [
        # from sentry_sdk.integrations.langchain import LangchainIntegration
        # LangchainIntegration(include_prompts=True),
    ]
    if include_http_integrations:
        failed_status_codes = {400, 401, 402, 403, *range(405, 600)}
        integrations.extend(
            [
                FastApiIntegration(failed_request_status_codes=failed_status_codes),
                StarletteIntegration(failed_request_status_codes=failed_status_codes),
            ]
        )

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        release=settings.APP_VERSION,
        send_default_pii=True,
        integrations=integrations,
        enable_logs=True,
        traces_sampler=traces_sampler,
    )

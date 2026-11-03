"""Middleware for setting locale based on request headers."""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from shared.infra.i18n import set_locale
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class LocaleMiddleware(BaseHTTPMiddleware):
    """
    Middleware that sets the locale for each request based on the Accept-Language header.

    The locale is stored in a context variable and will be used by the t() function
    to translate strings for that specific request.
    """

    def __init__(
        self,
        app: ASGIApp,
        supported_locales: list[str],
        default_locale: str,
    ):
        super().__init__(app)
        self.supported_locales = supported_locales
        self.default_locale = default_locale

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """
        Process the request and set the locale based on the Accept-Language header.
        """
        accept_language = request.headers.get("Accept-Language", "")

        locale = __get_best_locale_match(accept_language, self.default_locale, self.supported_locales)

        set_locale(locale)

        return await call_next(request)


def __get_best_locale_match(
    accept_language: str,
    default_locale: str,
    supported_locales: list[str],
) -> str:
    """
    Parse the Accept-Language header and find the best matching supported locale.

    The Accept-Language header format is:
    "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7"

    Args:
        accept_language: The Accept-Language header value
        default_locale: The default locale to use if no match is found
        supported_locales: A list of supported locale codes (e.g., ["en_US", "pt_BR"])
    Returns:
        The best matching locale code, or the default locale if no match
    """

    if not accept_language:
        return default_locale

    locales = __parse_accept_language(accept_language)

    # Try to find exact matches first
    for locale_code, _ in locales:
        # Normalize locale code (e.g., "pt-BR" -> "pt_BR")
        normalized = locale_code.replace("-", "_")

        if normalized in supported_locales:
            return normalized

    # Try to find language-only matches (e.g., "pt" for "pt-BR" or "pt_BR")
    for locale_code, _ in locales:
        language = locale_code.split("-")[0].split("_")[0]

        for supported in supported_locales:
            supported_language = supported.split("_")[0]
            if language.lower() == supported_language.lower():
                return supported

    # No match found, return default
    return default_locale


def __parse_accept_language(accept_language: str) -> list[tuple[str, float]]:
    """Parse the Accept-Language header into a list of (locale, quality) tuples"""

    locales: list[tuple[str, float]] = []
    for part in accept_language.split(","):
        part_stripped = part.strip()
        if not part_stripped:
            continue

        # Split locale and quality value
        if ";" in part_stripped:
            locale_code, quality_str = part_stripped.split(";", 1)
            locale_code = locale_code.strip()
            # Extract quality value (default is 1.0)
            try:
                quality = float(quality_str.split("=")[1].strip())
            except IndexError, ValueError:
                quality = 1.0
        else:
            locale_code = part_stripped.strip()
            quality = 1.0

        locales.append((locale_code, quality))

    # Sort by quality (highest first)
    locales.sort(key=lambda x: x[1], reverse=True)

    return locales

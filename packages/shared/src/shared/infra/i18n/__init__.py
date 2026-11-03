from contextvars import ContextVar
from pathlib import Path

from babel.support import NullTranslations, Translations

# Context variable to store current locale for each request
_current_locale: ContextVar[str] = ContextVar("locale", default="en")

# Cache for loaded translations (using base class to support both Translations and NullTranslations)
_translations_cache: dict[str, NullTranslations] = {}

# Path to locale directory (project root / locales)
_LOCALE_DIR = Path(__file__).parent.parent.parent.parent / "locales"


def get_locale() -> str:
    """Get the current locale from context or environment."""
    return _current_locale.get()


def set_locale(locale: str) -> None:
    """Set the current locale for the current context (request)."""
    _current_locale.set(locale)


def _get_translations(locale: str) -> NullTranslations:
    """Get or load translations for a given locale."""
    if locale not in _translations_cache:
        try:
            translations = Translations.load(dirname=str(_LOCALE_DIR), locales=[locale], domain="messages")
            _translations_cache[locale] = translations
        except FileNotFoundError, OSError:
            # If translations not found, use NullTranslations (returns original text)
            _translations_cache[locale] = NullTranslations()

    return _translations_cache[locale]


def t(txt: str) -> str:
    """
    Translate a text string to the current locale.

    Args:
        txt: The text to translate (should be in English as source language)

    Returns:
        Translated text in the current locale, or original text if translation not found
    """
    locale = get_locale()

    # If locale is English (default), return original text
    if locale == "en":
        return txt

    translations = _get_translations(locale)
    return translations.gettext(txt)

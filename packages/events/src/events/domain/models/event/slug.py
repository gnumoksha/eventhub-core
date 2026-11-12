import re
import unicodedata
from dataclasses import dataclass

from shared.domain.errors import InvalidValue

SLUG_MAX_LENGTH = 120


@dataclass(frozen=True, slots=True)
class Slug:
    value: str

    def __post_init__(self) -> None:
        cleaned = self.value.strip()
        if not cleaned:
            raise InvalidValue("The slug is required")
        if len(cleaned) > SLUG_MAX_LENGTH:
            raise InvalidValue(f"The slug must have at most {SLUG_MAX_LENGTH} characters")
        object.__setattr__(self, "value", cleaned)

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_title(cls, title: str) -> Slug:
        normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^\w\s-]", "", normalized.lower())
        base = re.sub(r"[-\s]+", "-", slug).strip("-")[:100].strip("-") or "event"
        return cls(base)

    def with_suffix(self, suffix: int) -> Slug:
        return Slug(f"{self.value}-{suffix}")


def slugify(text: str) -> str:
    return Slug.from_title(text).value


def resolve_available_slug(base_slug: str, existing_slugs: set[str]) -> str:
    """Finds the lowest available sequential slug when collisions occur."""
    if base_slug not in existing_slugs:
        return base_slug

    n = 2
    while f"{base_slug}-{n}" in existing_slugs:
        n += 1
    return f"{base_slug}-{n}"

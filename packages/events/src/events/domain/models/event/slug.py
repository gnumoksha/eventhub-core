import re
import unicodedata

SLUG_MAX_LENGTH = 120


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", normalized.lower())
    return re.sub(r"[-\s]+", "-", slug).strip("-")

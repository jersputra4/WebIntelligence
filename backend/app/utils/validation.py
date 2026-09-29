"""Input validation helpers."""
from __future__ import annotations

import re

from app.core.errors import ValidationFailed

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,30}$")


def normalize_username(raw: str | None) -> str:
    """Strip whitespace, a leading '@' and validate the handle format."""
    if raw is None or not raw.strip():
        raise ValidationFailed("Username is required", code="USERNAME_REQUIRED")
    username = raw.strip()
    if username.startswith("@"):
        username = username[1:]
    if not USERNAME_RE.fullmatch(username):
        raise ValidationFailed(
            "Username may only contain letters, numbers, '.', '_' or '-' (max 30 characters)"
        )
    return username

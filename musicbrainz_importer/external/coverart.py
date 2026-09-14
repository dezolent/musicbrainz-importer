"""Cover Art Archive URL helpers (public, no auth)."""

from __future__ import annotations

CAA_BASE = "https://coverartarchive.org"


def cover_art_url(release_mbid: str, size: int = 250) -> str:
    return f"{CAA_BASE}/release/{release_mbid}/front-{size}"

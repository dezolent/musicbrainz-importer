"""
MusicBrainz API client and lookup-result processing.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .constants import ENTITY_COLLECTION_KEYS, RATE_LIMIT_SECONDS, WS_BASE
from .models import LookupHit
from .utils import clean_value, mb_entity_url, normalize_text

_RETRY_DELAYS = (5, 15, 30)  # seconds between attempts after the first


class MusicBrainzClient:
    def __init__(self, user_agent: str, enabled: bool = True) -> None:
        self.enabled = enabled
        self._last_call = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json",
        })

    def _throttle(self) -> None:
        if not self.enabled:
            return
        delta = time.monotonic() - self._last_call
        if delta < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - delta)

    def search(self, entity: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []

        url = f"{WS_BASE}/{entity}/"
        params = {"query": query, "fmt": "json", "limit": limit}
        last_error: Exception | None = None

        for attempt, delay in enumerate([0] + list(_RETRY_DELAYS)):
            if delay:
                print(f"  Retrying in {delay}s (attempt {attempt + 1})...", file=sys.stderr)
                time.sleep(delay)
            try:
                self._throttle()
                response = self.session.get(url, params=params, timeout=30)
                self._last_call = time.monotonic()
                response.raise_for_status()
                return response.json().get(ENTITY_COLLECTION_KEYS[entity], [])
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                print(f"  Warning: {entity} lookup timed out ({exc})", file=sys.stderr)
            except requests.exceptions.RequestException as exc:
                # Non-retryable (e.g. 4xx). Warn and return empty.
                print(f"  Warning: {entity} lookup failed ({exc})", file=sys.stderr)
                return []

        print(f"  Skipping {entity} lookup after all retries failed: {last_error}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Lookup result helpers
# ---------------------------------------------------------------------------

def _render_artist_credit(artist_credit: Any) -> str:
    parts: List[str] = []
    for item in artist_credit or []:
        name = clean_value(item.get("name") or item.get("artist", {}).get("name"))
        joinphrase = clean_value(item.get("joinphrase") or item.get("join_phrase"))
        parts.append(name + joinphrase)
    return "".join(parts).strip()


def _item_title(item: Dict[str, Any]) -> str:
    return clean_value(item.get("title") or item.get("name"))


def pick_best_hit(
        entity: str,
        candidates: List[Dict[str, Any]],
        expected_name: str,
        expected_artist: str = "",
) -> Optional[LookupHit]:
    if not candidates:
        return None

    expected_name_norm = normalize_text(expected_name)
    expected_artist_norm = normalize_text(expected_artist)
    ranked: List[Tuple[int, Dict[str, Any]]] = []

    for item in candidates:
        base_score = int(clean_value(item.get("score") or 0) or 0)
        title_norm = normalize_text(_item_title(item))
        bonus = 0

        if title_norm == expected_name_norm and expected_name_norm:
            bonus += 200
        elif expected_name_norm and expected_name_norm in title_norm:
            bonus += 50

        if entity == "artist":
            artist_name = clean_value(item.get("name"))
        else:
            artist_name = _render_artist_credit(item.get("artist-credit", []))
        artist_norm = normalize_text(artist_name)

        if expected_artist_norm and artist_norm == expected_artist_norm:
            bonus += 150
        elif expected_artist_norm and expected_artist_norm in artist_norm:
            bonus += 30

        ranked.append((base_score + bonus, item))

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = ranked[0]
    mbid = clean_value(best.get("id"))
    if not mbid:
        return None

    display_name = _item_title(best) if entity != "artist" else clean_value(best.get("name"))
    extra: Dict[str, Any] = {}
    if entity != "artist":
        artist_credit = _render_artist_credit(best.get("artist-credit", []))
        if artist_credit:
            extra["artist_credit"] = artist_credit

    return LookupHit(
        mbid=mbid,
        name=display_name,
        score=best_score,
        url=mb_entity_url(entity, mbid),
        extra=extra,
    )

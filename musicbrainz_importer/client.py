"""
MusicBrainz web service client (search, browse, lookup) with rate limiting and retry.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from .constants import ENTITY_COLLECTION_KEYS, RATE_LIMIT_SECONDS, WS_BASE
from .models import LookupHit
from .utils import clean_value, mb_entity_url, normalize_text

_RETRY_DELAYS = (5, 15, 30)  # seconds between attempts after the first
_RETRYABLE_STATUSES = {429, 502, 503, 504}
BROWSE_PAGE_SIZE = 100


class MusicBrainzClient:
    def __init__(
            self,
            user_agent: str,
            enabled: bool = True,
            session: Optional[Any] = None,
            sleep: Callable[[float], None] = time.sleep,
            clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = enabled
        self._sleep = sleep
        self._clock = clock
        self._last_call: Optional[float] = None
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json",
        })
        self.request_count = 0
        self.consecutive_failures = 0
        self._pending_delay = 0.0

    # ------------------------------------------------------------------ core

    def _throttle(self) -> None:
        if self._last_call is None:
            return
        delta = self._clock() - self._last_call
        if delta < RATE_LIMIT_SECONDS:
            self._sleep(RATE_LIMIT_SECONDS - delta)

    def _get(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """GET a ws/2 URL as JSON. Retries on 429/5xx/timeouts; returns {} on failure."""
        if not self.enabled:
            return {}
        params = {**params, "fmt": "json"}
        last_error = ""

        for attempt in range(len(_RETRY_DELAYS) + 1):
            if attempt:
                delay = self._pending_delay or _RETRY_DELAYS[attempt - 1]
                print(f"  Retrying in {delay}s (attempt {attempt + 1}): {last_error}", file=sys.stderr)
                self._sleep(delay)
            self._pending_delay = 0.0
            try:
                self._throttle()
                response = self.session.get(url, params=params, timeout=30)
                self._last_call = self._clock()
                self.request_count += 1
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = f"network error ({exc})"
                continue
            except requests.exceptions.RequestException as exc:
                print(f"  Warning: request failed ({exc})", file=sys.stderr)
                return {}

            status = getattr(response, "status_code", 200)
            if status in _RETRYABLE_STATUSES:
                retry_after = clean_value((getattr(response, "headers", {}) or {}).get("Retry-After"))
                self._pending_delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 0.0
                last_error = f"HTTP {status}"
                continue
            if status >= 400:
                print(f"  Warning: HTTP {status} for {url} params={params}", file=sys.stderr)
                return {}
            try:
                payload = response.json() or {}
                self.consecutive_failures = 0
                return payload
            except ValueError as exc:
                print(f"  Warning: invalid JSON from {url} ({exc})", file=sys.stderr)
                return {}

        self.consecutive_failures += 1
        print(f"  Skipping request after all retries failed: {last_error} ({url})", file=sys.stderr)
        return {}

    # ------------------------------------------------------------------ public API

    def search(self, entity: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        payload = self._get(f"{WS_BASE}/{entity}/", {"query": query, "limit": limit})
        return payload.get(ENTITY_COLLECTION_KEYS[entity], [])

    def browse(
            self,
            entity: str,
            params: Dict[str, Any],
            inc: str = "",
            page_size: int = BROWSE_PAGE_SIZE,
    ) -> List[Dict[str, Any]]:
        """Fetch every page of a browse request, e.g. browse("recording", {"artist": mbid})."""
        if not self.enabled:
            return []
        collection_key = ENTITY_COLLECTION_KEYS[entity]
        count_key = f"{entity}-count"
        items: List[Dict[str, Any]] = []
        offset = 0
        while True:
            query = {**params, "limit": page_size, "offset": offset}
            if inc:
                query["inc"] = inc
            payload = self._get(f"{WS_BASE}/{entity}", query)
            page = payload.get(collection_key, [])
            items.extend(page)
            total = int(payload.get(count_key) or 0)
            offset += len(page)
            if not page or offset >= total:
                break
        return items

    def lookup(self, entity: str, mbid: str, inc: str = "") -> Dict[str, Any]:
        params = {"inc": inc} if inc else {}
        return self._get(f"{WS_BASE}/{entity}/{mbid}", params)


# ---------------------------------------------------------------------------
# Lookup result helpers (used by the ws/2 search fallback)
# ---------------------------------------------------------------------------

def render_artist_credit(artist_credit: Any) -> str:
    parts: List[str] = []
    for item in artist_credit or []:
        name = clean_value(item.get("name") or (item.get("artist") or {}).get("name"))
        joinphrase = item.get("joinphrase") or item.get("join_phrase") or ""
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
            artist_name = render_artist_credit(item.get("artist-credit", []))
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
        artist_credit = render_artist_credit(best.get("artist-credit", []))
        if artist_credit:
            extra["artist_credit"] = artist_credit

    return LookupHit(
        mbid=mbid,
        name=display_name,
        score=min(best_score, 100),
        url=mb_entity_url(entity, mbid),
        extra=extra,
        confidence="search",
        method="search",
    )

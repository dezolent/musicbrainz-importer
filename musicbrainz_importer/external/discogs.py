"""Discogs API: list an artist's releases once, then match locally."""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests

from ..matching import normalize_title
from ..utils import clean_value, normalize_text, normalize_upc
from .http import get_json

API_BASE = "https://api.discogs.com"
SITE_BASE = "https://www.discogs.com"


def discogs_release_url(result: Dict[str, Any]) -> str:
    uri = clean_value(result.get("uri"))
    if uri.startswith("http"):
        return uri
    return f"{SITE_BASE}{uri}" if uri else f"{SITE_BASE}/release/{result.get('id')}"


def _identifiers(result: Dict[str, Any]) -> set:
    values = set()
    for raw in result.get("barcode") or []:
        text = clean_value(raw).upper()
        values.add(re.sub(r"[^A-Z0-9]", "", text))
        digits = normalize_upc(text).lstrip("0")
        if digits:
            values.add(digits)
    return values


def _result_title(result: Dict[str, Any]) -> str:
    """Discogs search titles are 'Artist - Title'; return the title part."""
    text = clean_value(result.get("title"))
    return text.rsplit(" - ", 1)[-1] if " - " in text else text


def match_discogs_release(
        results: List[Dict[str, Any]],
        upc: str,
        catalog_number: str,
        isrcs: Iterable[str],
        title: str,
) -> Optional[Dict[str, Any]]:
    wanted_upc = normalize_upc(upc).lstrip("0")
    wanted_isrcs = {re.sub(r"[^A-Z0-9]", "", clean_value(i).upper()) for i in isrcs if clean_value(i)}
    wanted_catno = normalize_text(catalog_number)
    wanted_title = normalize_title(title)

    if wanted_upc:
        for r in results:
            if wanted_upc in _identifiers(r):
                return r
    if wanted_catno:
        for r in results:
            if normalize_text(r.get("catno", "")) == wanted_catno and wanted_catno != normalize_text("none"):
                return r
    if wanted_isrcs:
        for r in results:
            if wanted_isrcs & _identifiers(r):
                return r
    if wanted_title:
        for r in results:
            if normalize_title(_result_title(r)) == wanted_title:
                return r
    return None


class DiscogsClient:
    def __init__(
            self,
            token: str,
            user_agent: str,
            session: Optional[Any] = None,
            sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.token = clean_value(token)
        self.user_agent = user_agent
        self.session = session or requests.Session()
        self._sleep = sleep
        self.request_count = 0
        self._cache: Dict[str, List[Dict[str, Any]]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def _headers(self) -> Dict[str, str]:
        return {"User-Agent": self.user_agent, "Authorization": f"Discogs token={self.token}"}

    def artist_releases(self, artist_name: str) -> List[Dict[str, Any]]:
        if not self.enabled or not clean_value(artist_name):
            return []
        if artist_name in self._cache:
            return self._cache[artist_name]
        items: List[Dict[str, Any]] = []
        page = 1
        while True:
            self.request_count += 1
            payload = get_json(
                self.session, f"{API_BASE}/database/search",
                {"artist": artist_name, "type": "release", "per_page": 100, "page": page},
                headers=self._headers(), sleep=self._sleep, label="Discogs search",
            )
            results = payload.get("results") or []
            items.extend(results)
            pages = int((payload.get("pagination") or {}).get("pages") or 1)
            if not results or page >= pages:
                break
            page += 1
            self._sleep(1.0)  # Discogs allows 60 requests/minute
        self._cache[artist_name] = items
        return items

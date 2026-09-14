"""iTunes Search API (public, no auth): album + tracklist by UPC."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import requests

from ..models import ExternalRelease, ExternalTrack
from ..utils import clean_value
from .http import get_json

LOOKUP_URL = "https://itunes.apple.com/lookup"


def _strip_tracking(url: str) -> str:
    """Drop Apple's `uo=` affiliate parameter but keep the track selector `i=`."""
    parts = urlsplit(clean_value(url))
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "uo"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def parse_itunes_lookup(payload: Dict[str, Any]) -> Optional[ExternalRelease]:
    results = payload.get("results") or []
    collection = next((r for r in results if r.get("wrapperType") == "collection"), None)
    if not collection:
        return None
    tracks = []
    for item in results:
        if item.get("wrapperType") != "track":
            continue
        tracks.append(ExternalTrack(
            source="itunes",
            url=_strip_tracking(item.get("trackViewUrl")),
            title=clean_value(item.get("trackName")),
            artists=[clean_value(item.get("artistName"))] if item.get("artistName") else [],
            duration_ms=item.get("trackTimeMillis"),
        ))
    tracks.sort(key=lambda t: t.title)  # stable, but reorder by trackNumber when present below
    ordered = sorted(
        (r for r in results if r.get("wrapperType") == "track"),
        key=lambda r: int(r.get("trackNumber") or 0),
    )
    by_title = {t.title: t for t in tracks}
    tracks = [by_title[clean_value(r.get("trackName"))] for r in ordered if clean_value(r.get("trackName")) in by_title]
    return ExternalRelease(
        source="itunes",
        url=_strip_tracking(collection.get("collectionViewUrl")),
        title=clean_value(collection.get("collectionName")),
        date=clean_value(collection.get("releaseDate"))[:10],
        track_count=collection.get("trackCount"),
        artists=[clean_value(collection.get("artistName"))] if collection.get("artistName") else [],
        label=clean_value(collection.get("copyright")),
        tracks=tracks,
    )


class ITunesClient:
    def __init__(self, session: Optional[Any] = None, sleep: Callable[[float], None] = time.sleep, country: str = "us") -> None:
        self.session = session or requests.Session()
        self._sleep = sleep
        self.country = country
        self.request_count = 0
        self.enabled = True

    def album_by_upc(self, upc: str) -> Optional[ExternalRelease]:
        if not clean_value(upc):
            return None
        self.request_count += 1
        payload = get_json(self.session, LOOKUP_URL, {"upc": upc, "entity": "song", "country": self.country},
                           sleep=self._sleep, label="iTunes lookup")
        return parse_itunes_lookup(payload)

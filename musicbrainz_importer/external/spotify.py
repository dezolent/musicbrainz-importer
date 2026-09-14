"""Spotify Web API (client-credentials flow): ISRC and UPC lookups."""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from ..matching import normalize_title
from ..models import ExternalRelease, ExternalTrack
from ..utils import clean_value, normalize_text
from .http import get_json

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"


def parse_spotify_track(item: Dict[str, Any]) -> ExternalTrack:
    album = item.get("album") or {}
    return ExternalTrack(
        source="spotify",
        url=clean_value((item.get("external_urls") or {}).get("spotify")),
        title=clean_value(item.get("name")),
        artists=[clean_value(a.get("name")) for a in item.get("artists") or []],
        duration_ms=item.get("duration_ms"),
        isrc=clean_value((item.get("external_ids") or {}).get("isrc")),
        album_url=clean_value((album.get("external_urls") or {}).get("spotify")),
        album_title=clean_value(album.get("name")),
        album_date=clean_value(album.get("release_date")),
    )


def parse_spotify_track_search(payload: Dict[str, Any]) -> List[ExternalTrack]:
    tracks: List[ExternalTrack] = []
    for item in ((payload.get("tracks") or {}).get("items") or []):
        album = item.get("album") or {}
        tracks.append(ExternalTrack(
            source="spotify",
            url=clean_value((item.get("external_urls") or {}).get("spotify")),
            title=clean_value(item.get("name")),
            artists=[clean_value(a.get("name")) for a in item.get("artists") or []],
            duration_ms=item.get("duration_ms"),
            isrc=clean_value((item.get("external_ids") or {}).get("isrc")),
            album_url=clean_value((album.get("external_urls") or {}).get("spotify")),
            album_title=clean_value(album.get("name")),
            album_date=clean_value(album.get("release_date")),
        ))
    return tracks


def parse_spotify_album_search(payload: Dict[str, Any]) -> Optional[ExternalRelease]:
    items = (payload.get("albums") or {}).get("items") or []
    if not items:
        return None
    album = items[0]
    return ExternalRelease(
        source="spotify",
        url=clean_value((album.get("external_urls") or {}).get("spotify")),
        title=clean_value(album.get("name")),
        date=clean_value(album.get("release_date")),
        track_count=album.get("total_tracks"),
        artists=[clean_value(a.get("name")) for a in album.get("artists") or []],
        label="",
        tracks=[],
    )


def _artist_tokens(artist: str) -> List[str]:
    """Individual credited names from a CSV artist string such as "Dezolent & Coptr feat. X"."""
    import re
    parts = re.split(r"\s*(?:,\s*&\s*|,|\s+&\s+|\s+and\s+|\s+(?:feat\.?|ft\.?|featuring)\s+)\s*", artist, flags=re.IGNORECASE)
    return [normalize_text(p) for p in parts if normalize_text(p)]


def select_spotify_track(
        candidates: List[ExternalTrack],
        artist: str,
        title: str,
        duration_ms: Optional[int],
        release_title: str,
) -> Tuple[Optional[ExternalTrack], str]:
    """Pick the Spotify track that really is ours.

    Spotify's ISRC index has collisions, so a result must be credited to one of
    our artists. Among valid candidates prefer the one on the same release,
    then the closest duration. Returns (track, reason_if_rejected).
    """
    if not candidates:
        return None, ""
    wanted = set(_artist_tokens(artist))
    valid = [c for c in candidates if any(normalize_text(a) in wanted or any(w in normalize_text(a) for w in wanted) for a in c.artists)]
    if not valid:
        credited = sorted({a for c in candidates for a in c.artists})
        return None, f"Spotify's result for this ISRC is credited to {', '.join(credited)}, not {artist}"

    wanted_release = normalize_title(release_title)
    same_release = [c for c in valid if wanted_release and normalize_title(c.album_title) == wanted_release]
    pool = same_release or valid
    if duration_ms:
        pool = sorted(pool, key=lambda c: abs((c.duration_ms or 0) - duration_ms))
    return pool[0], ""


class SpotifyClient:
    def __init__(
            self,
            client_id: str,
            client_secret: str,
            session: Optional[Any] = None,
            sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self._sleep = sleep
        self._token = ""
        self._token_expiry = 0.0
        self.request_count = 0

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _headers(self) -> Dict[str, str]:
        if not self._token or time.time() >= self._token_expiry:
            try:
                response = self.session.post(
                    TOKEN_URL,
                    auth=(self.client_id, self.client_secret),
                    data={"grant_type": "client_credentials"},
                    timeout=30,
                )
                payload = response.json()
            except (requests.exceptions.RequestException, ValueError) as exc:
                print(f"  Warning: Spotify token request failed ({exc})", file=sys.stderr)
                return {}
            self._token = clean_value(payload.get("access_token"))
            self._token_expiry = time.time() + int(payload.get("expires_in") or 3600) - 60
            if not self._token:
                print(f"  Warning: Spotify token error: {payload.get('error_description') or payload.get('error')}", file=sys.stderr)
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _search(self, query: str, kind: str) -> Dict[str, Any]:
        headers = self._headers()
        if not headers:
            return {}
        self.request_count += 1
        return get_json(self.session, f"{API_BASE}/search", {"q": query, "type": kind, "limit": 5},
                        headers=headers, sleep=self._sleep, label="Spotify search")

    def tracks_by_isrc(self, isrc: str) -> List[ExternalTrack]:
        if not self.enabled or not clean_value(isrc):
            return []
        return parse_spotify_track_search(self._search(f"isrc:{isrc}", "track"))

    def track_by_id(self, track_id: str) -> Optional[ExternalTrack]:
        if not self.enabled or not clean_value(track_id):
            return None
        headers = self._headers()
        if not headers:
            return None
        self.request_count += 1
        payload = get_json(self.session, f"{API_BASE}/tracks/{track_id}", headers=headers, sleep=self._sleep, label="Spotify track")
        return parse_spotify_track(payload) if payload.get("id") else None

    def album_by_upc(self, upc: str) -> Optional[ExternalRelease]:
        if not self.enabled or not clean_value(upc):
            return None
        return parse_spotify_album_search(self._search(f"upc:{upc}", "album"))

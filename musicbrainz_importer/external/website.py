"""
The artist's own website as a first-party source, read through schema.org JSON-LD.

Any site that publishes MusicRecording / MusicComposition / MusicAlbum objects
(with isrcCode, iswcCode, duration, sameAs links, images) works. Pages are cached
on disk so a re-run does not re-fetch the whole catalog.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

from ..matching import normalize_title
from ..utils import clean_value, normalize_iswc
from .http import get_json  # noqa: F401  (kept for symmetry with other sources)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class SiteTrack:
    url: str
    title: str = ""
    isrc: str = ""
    iswc: str = ""
    duration_ms: Optional[int] = None
    date: str = ""
    cover_url: str = ""
    stream_url: str = ""
    has_lyrics: bool = False
    release_type: str = ""
    track_count: Optional[int] = None
    album_url: str = ""
    links: Dict[str, str] = field(default_factory=dict)  # provider -> url


@dataclass
class SiteAlbum:
    url: str
    title: str = ""
    date: str = ""
    cover_url: str = ""
    release_type: str = ""
    track_count: Optional[int] = None
    track_urls: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure parsing helpers
# ---------------------------------------------------------------------------

_LD_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_HREF_RE = re.compile(r'href="(https?://[^"]+)"', re.I)

PROVIDERS = (
    ("spotify", r"open\.spotify\.com/track/"),
    ("apple", r"music\.apple\.com/.+/(?:song|album)/"),
    ("youtube", r"(?:www\.)?youtube\.com/watch|youtu\.be/"),
    ("soundcloud", r"soundcloud\.com/[^/]+/[^/]+"),
    ("tidal", r"tidal\.com/"),
    ("deezer", r"deezer\.com/.*track/"),
    ("beatport", r"beatport\.com/"),
    ("bandcamp", r"bandcamp\.com/track/"),
    ("amazon", r"amzn\.to/|amazon\.com/"),
    ("pandora", r"pandora\.com/artist/.+/.+/.+"),
    ("audiomack", r"audiomack\.com/[^/]+/song/"),
)
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "uo", "ref", "si"}


def _strip_tracking(url: str) -> str:
    parts = urlsplit(clean_value(url))
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in _TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _graph(html: str) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for block in _LD_RE.findall(html or ""):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                nodes.extend(item.get("@graph") or [item])
    return nodes


def _types(node: Dict[str, Any]) -> set:
    t = node.get("@type")
    return set(t) if isinstance(t, list) else {t}


def _iso_duration_ms(value: str) -> Optional[int]:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", clean_value(value))
    if not m or not any(m.groups()):
        return None
    h, mi, s = (float(x or 0) for x in m.groups())
    return int(round((h * 3600 + mi * 60 + s) * 1000))


def _image_url(node: Any) -> str:
    if isinstance(node, dict):
        return clean_value(node.get("url") or node.get("contentUrl"))
    if isinstance(node, list) and node:
        return _image_url(node[0])
    return clean_value(node)


def _release_type(value: str) -> str:
    text = clean_value(value).rsplit("/", 1)[-1]
    return text.replace("Release", "") if text.endswith("Release") else text


def spotify_track_id(url: str) -> str:
    m = re.search(r"open\.spotify\.com/track/([A-Za-z0-9]+)", clean_value(url))
    return m.group(1) if m else ""


def apple_song_id(url: str) -> str:
    url = clean_value(url)
    m = re.search(r"[?&]i=(\d+)", url) or re.search(r"/song/[^/]+/(\d+)", url)
    return m.group(1) if m else ""


def _classify_links(urls: Iterable[str]) -> Dict[str, str]:
    links: Dict[str, str] = {}
    for raw in urls:
        url = _strip_tracking(raw)
        for provider, pattern in PROVIDERS:
            if provider not in links and re.search(pattern, url, re.I):
                links[provider] = url
                break
    return links


def parse_track_list(html: str) -> List[SiteTrack]:
    tracks: List[SiteTrack] = []
    for node in _graph(html):
        if "ItemList" not in _types(node):
            continue
        for entry in node.get("itemListElement") or []:
            item = entry.get("item") if isinstance(entry, dict) else None
            if not isinstance(item, dict) or "MusicRecording" not in _types(item):
                continue
            tracks.append(SiteTrack(
                url=_strip_tracking(item.get("url")),
                title=clean_value(item.get("name")),
                duration_ms=_iso_duration_ms(item.get("duration", "")),
                date=clean_value(item.get("datePublished"))[:10],
            ))
    return tracks


def parse_track_page(html: str, page_url: str) -> SiteTrack:
    track = SiteTrack(url=page_url)
    same_as: List[str] = []
    for node in _graph(html):
        types = _types(node)
        if "MusicRecording" in types:
            track.title = clean_value(node.get("name")) or track.title
            track.isrc = clean_value(node.get("isrcCode")).upper() or track.isrc
            track.duration_ms = _iso_duration_ms(node.get("duration", "")) or track.duration_ms
            track.date = clean_value(node.get("datePublished"))[:10] or track.date
            track.cover_url = _image_url(node.get("image")) or track.cover_url
            same = node.get("sameAs") or []
            same_as.extend(same if isinstance(same, list) else [same])
        elif "MusicComposition" in types:
            track.iswc = normalize_iswc(node.get("iswcCode", "")) or track.iswc
        elif "MusicAlbum" in types:
            track.cover_url = track.cover_url or _image_url(node.get("image"))
            track.release_type = _release_type(node.get("albumReleaseType", ""))
            try:
                track.track_count = int(node.get("numTracks")) if node.get("numTracks") is not None else None
            except (TypeError, ValueError):
                track.track_count = None
            album_url = clean_value(node.get("url"))
            if album_url and "/albums/" in album_url:
                track.album_url = album_url
    for url in same_as:
        if "/stream/" in clean_value(url):
            track.stream_url = _strip_tracking(url)
    track.links = _classify_links(list(same_as) + _HREF_RE.findall(html or ""))
    track.has_lyrics = bool(re.search(r"data-lyrics|>\s*Lyrics\s*<", html or "", re.I))
    return track


def parse_album_page(html: str, page_url: str) -> SiteAlbum:
    album = SiteAlbum(url=page_url)
    for node in _graph(html):
        if "MusicAlbum" in _types(node):
            album.title = clean_value(node.get("name"))
            album.date = clean_value(node.get("datePublished"))[:10]
            album.cover_url = _image_url(node.get("image"))
            album.release_type = _release_type(node.get("albumReleaseType", ""))
            try:
                album.track_count = int(node.get("numTracks")) if node.get("numTracks") is not None else None
            except (TypeError, ValueError):
                album.track_count = None
            tracks = node.get("track") or []
            tracks = tracks if isinstance(tracks, list) else [tracks]
            album.track_urls = [clean_value(t.get("@id") if isinstance(t, dict) else t).split("#")[0] for t in tracks]
    return album


def match_site_track(tracks: Iterable[SiteTrack], isrc: str, title: str) -> Optional[SiteTrack]:
    wanted_isrc = re.sub(r"[^A-Z0-9]", "", clean_value(isrc).upper())
    tracks = list(tracks)
    if wanted_isrc:
        for t in tracks:
            if t.isrc and t.isrc == wanted_isrc:
                return t
    wanted = normalize_title(title)
    if wanted:
        for t in tracks:
            if normalize_title(t.title) == wanted:
                return t
    return None


def match_site_album(albums: Iterable[SiteAlbum], title: str) -> Optional[SiteAlbum]:
    wanted = normalize_title(title)
    for a in albums:
        if wanted and normalize_title(a.title) == wanted:
            return a
    return None


# ---------------------------------------------------------------------------
# Client with disk cache
# ---------------------------------------------------------------------------

class WebsiteClient:
    def __init__(
            self,
            base_url: str,
            user_agent: str,
            session: Optional[Any] = None,
            cache_dir: Optional[Path] = None,
            cache_ttl_seconds: int = 7 * 24 * 3600,
            sleep: Callable[[float], None] = time.sleep,
            politeness_seconds: float = 0.4,
    ) -> None:
        self.base_url = clean_value(base_url).rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl_seconds
        self._sleep = sleep
        self._politeness = politeness_seconds
        self.request_count = 0
        self.cache_hits = 0

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _cache_path(self, url: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".html")

    def fetch(self, url: str) -> str:
        path = self._cache_path(url)
        if path and path.exists() and time.time() - path.stat().st_mtime < self.cache_ttl:
            self.cache_hits += 1
            return path.read_text(encoding="utf-8")
        try:
            response = self.session.get(url, timeout=30)
            self.request_count += 1
            self._sleep(self._politeness)
        except requests.exceptions.RequestException as exc:
            print(f"  Warning: website fetch failed for {url} ({exc})", file=sys.stderr)
            return ""
        if response.status_code != 200:
            print(f"  Warning: website returned HTTP {response.status_code} for {url}", file=sys.stderr)
            return ""
        text = response.text
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return text

    def _sitemap_urls(self) -> List[str]:
        xml = self.fetch(f"{self.base_url}/sitemap.xml")
        return [clean_value(u) for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)]

    def tracks(self) -> List[SiteTrack]:
        listed = parse_track_list(self.fetch(f"{self.base_url}/tracks"))
        urls = [t.url for t in listed] or [u for u in self._sitemap_urls() if "/tracks/" in u]
        if not urls:
            return []
        print(f"Reading {len(urls)} track pages from {self.base_url}...", file=sys.stderr)
        result: List[SiteTrack] = []
        for url in urls:
            page = self.fetch(url)
            track = parse_track_page(page, url) if page else SiteTrack(url=url)
            listed_match = next((t for t in listed if t.url == url), None)
            if listed_match:
                track.title = track.title or listed_match.title
                track.duration_ms = track.duration_ms or listed_match.duration_ms
                track.date = track.date or listed_match.date
            result.append(track)
        return result

    def albums(self) -> List[SiteAlbum]:
        urls = [u for u in self._sitemap_urls() if "/albums/" in u]
        albums = []
        for url in urls:
            page = self.fetch(url)
            if page:
                albums.append(parse_album_page(page, url))
        return albums

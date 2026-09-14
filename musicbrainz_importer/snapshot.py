"""
Build an ArtistCatalog snapshot from the MusicBrainz browse endpoints.

Three paginated requests (releases, recordings, works keyed by artist MBID)
replace dozens of per-row searches and give exact identifiers to match on.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from .client import MusicBrainzClient, render_artist_credit
from .models import ArtistCatalog, MBRecording, MBRelease, MBTrack, MBWork
from .utils import clean_value, normalize_text

RELEASE_INC = "labels+media+recordings+release-groups+artist-credits"
RECORDING_INC = "isrcs+artist-credits"
WORK_INC = "artist-rels"


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_release(raw: Dict[str, Any]) -> MBRelease:
    labels = []
    for info in raw.get("label-info") or []:
        label = info.get("label") or {}
        labels.append((clean_value(label.get("name")), clean_value(label.get("id")), clean_value(info.get("catalog-number"))))

    tracks: List[MBTrack] = []
    for medium in raw.get("media") or []:
        for track in medium.get("tracks") or []:
            tracks.append(MBTrack(
                position=_int_or_none(track.get("position")) or len(tracks) + 1,
                title=clean_value(track.get("title")),
                recording_mbid=clean_value((track.get("recording") or {}).get("id")),
                length_ms=_int_or_none(track.get("length")),
            ))

    release_group = raw.get("release-group") or {}
    return MBRelease(
        mbid=clean_value(raw.get("id")),
        title=clean_value(raw.get("title")),
        artist_credit=render_artist_credit(raw.get("artist-credit")),
        barcode=clean_value(raw.get("barcode")),
        date=clean_value(raw.get("date")),
        country=clean_value(raw.get("country")),
        status=clean_value(raw.get("status")),
        labels=labels,
        release_group_mbid=clean_value(release_group.get("id")),
        release_group_type=clean_value(release_group.get("primary-type")),
        tracks=tracks,
        has_cover_art=bool((raw.get("cover-art-archive") or {}).get("front")),
    )


def _parse_recording(raw: Dict[str, Any]) -> MBRecording:
    credit = raw.get("artist-credit") or []
    return MBRecording(
        mbid=clean_value(raw.get("id")),
        title=clean_value(raw.get("title")),
        artist_credit=render_artist_credit(credit),
        artist_mbids=[clean_value((c.get("artist") or {}).get("id")) for c in credit if (c.get("artist") or {}).get("id")],
        isrcs=[clean_value(i) for i in raw.get("isrcs") or []],
        length_ms=_int_or_none(raw.get("length")),
        first_release_date=clean_value(raw.get("first-release-date")),
    )


def _parse_work(raw: Dict[str, Any]) -> MBWork:
    writers: List[str] = []
    for rel in raw.get("relations") or []:
        artist = rel.get("artist")
        if artist and clean_value(artist.get("name")):
            name = clean_value(artist.get("name"))
            if name not in writers:
                writers.append(name)
    return MBWork(
        mbid=clean_value(raw.get("id")),
        title=clean_value(raw.get("title")),
        iswcs=[clean_value(i) for i in raw.get("iswcs") or []],
        writers=writers,
    )


def _index_artists(*payloads: List[Dict[str, Any]]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for payload in payloads:
        for raw in payload:
            for credit in raw.get("artist-credit") or []:
                artist = credit.get("artist") or {}
                mbid = clean_value(artist.get("id"))
                for name in (artist.get("name"), credit.get("name")):
                    key = normalize_text(name or "")
                    if key and mbid and key not in index:
                        index[key] = mbid
    return index


def build_catalog(
        artist_mbid: str,
        artist_name: str,
        releases: List[Dict[str, Any]],
        recordings: List[Dict[str, Any]],
        works: List[Dict[str, Any]],
) -> ArtistCatalog:
    return ArtistCatalog(
        artist_mbid=artist_mbid,
        artist_name=artist_name,
        releases=[_parse_release(r) for r in releases],
        recordings=[_parse_recording(r) for r in recordings],
        works=[_parse_work(w) for w in works],
        artist_index=_index_artists(releases, recordings),
    )


def choose_artist(candidates: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    """Pick the search candidate whose name matches exactly (case/punctuation-insensitive)."""
    wanted = normalize_text(name)
    exact = [c for c in candidates if normalize_text(c.get("name", "")) == wanted]
    if not exact:
        return None
    return max(exact, key=lambda c: int(clean_value(c.get("score") or 0) or 0))


def resolve_artist_mbid(mb: MusicBrainzClient, artist_name: str) -> Optional[str]:
    results = mb.search("artist", f'artist:"{artist_name}"', limit=10)
    chosen = choose_artist(results, artist_name)
    return clean_value(chosen.get("id")) if chosen else None


def fetch_artist_catalog(mb: MusicBrainzClient, artist_mbid: str, artist_name: str = "") -> ArtistCatalog:
    if not artist_name:
        artist = mb.lookup("artist", artist_mbid)
        artist_name = clean_value(artist.get("name")) or artist_mbid
    print(f"Fetching MusicBrainz catalog for {artist_name} ({artist_mbid})...", file=sys.stderr)
    releases = mb.browse("release", {"artist": artist_mbid}, inc=RELEASE_INC)
    recordings = mb.browse("recording", {"artist": artist_mbid}, inc=RECORDING_INC)
    works = mb.browse("work", {"artist": artist_mbid}, inc=WORK_INC)
    print(f"  {len(releases)} releases, {len(recordings)} recordings, {len(works)} works", file=sys.stderr)
    return build_catalog(artist_mbid, artist_name, releases, recordings, works)

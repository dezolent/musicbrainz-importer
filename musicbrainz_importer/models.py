from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Lookup results
# ---------------------------------------------------------------------------

@dataclass
class LookupHit:
    """A resolved MusicBrainz entity for one catalog item.

    confidence: "exact" (identifier match), "strong" (normalized title match),
                "fuzzy" (similarity above threshold) or "search" (ws/2 search fallback).
    method:     what produced the match, e.g. "isrc", "barcode", "title", "search".
    """
    mbid: str
    name: str
    score: int
    url: str
    extra: Dict[str, Any] = field(default_factory=dict)
    confidence: str = "search"
    method: str = ""


# ---------------------------------------------------------------------------
# Snapshot of an artist's MusicBrainz catalog (from the browse endpoints)
# ---------------------------------------------------------------------------

@dataclass
class MBTrack:
    position: int
    title: str
    recording_mbid: str
    length_ms: Optional[int]


@dataclass
class MBRecording:
    mbid: str
    title: str
    artist_credit: str
    artist_mbids: List[str]
    isrcs: List[str]
    length_ms: Optional[int]
    first_release_date: str


@dataclass
class MBRelease:
    mbid: str
    title: str
    artist_credit: str
    barcode: str
    date: str
    country: str
    status: str
    labels: List[Tuple[str, str, str]]  # (label name, label mbid, catalog number)
    release_group_mbid: str
    release_group_type: str
    tracks: List[MBTrack]
    has_cover_art: bool


@dataclass
class MBWork:
    mbid: str
    title: str
    iswcs: List[str]
    writers: List[str]


@dataclass
class ArtistCatalog:
    artist_mbid: str
    artist_name: str
    releases: List[MBRelease] = field(default_factory=list)
    recordings: List[MBRecording] = field(default_factory=list)
    works: List[MBWork] = field(default_factory=list)
    artist_index: Dict[str, str] = field(default_factory=dict)  # normalized credited name -> artist mbid


# ---------------------------------------------------------------------------
# Enrichment and review data
# ---------------------------------------------------------------------------

@dataclass
class ExternalLink:
    """A URL that can be seeded as a release-URL relationship."""
    url: str
    link_type_id: Optional[int]
    source: str  # e.g. "csv", "discogs", "spotify", "itunes"
    label: str = ""


@dataclass
class ExternalTrack:
    """A track as seen by a third-party catalog (Spotify, Apple Music, ...)."""
    source: str
    url: str
    title: str
    artists: List[str]
    duration_ms: Optional[int]
    isrc: str = ""
    album_url: str = ""
    album_title: str = ""
    album_date: str = ""


@dataclass
class ExternalRelease:
    """A release as seen by a third-party catalog."""
    source: str
    url: str
    title: str
    date: str
    track_count: Optional[int]
    artists: List[str] = field(default_factory=list)
    label: str = ""
    tracks: List[ExternalTrack] = field(default_factory=list)


@dataclass
class Discrepancy:
    """A difference between the CSV and MusicBrainz (or an internal CSV inconsistency)."""
    field: str
    csv_value: str
    mb_value: str
    severity: str  # "warn" | "info"
    message: str = ""
    source: str = "musicbrainz"  # which system the mb_value came from


# ---------------------------------------------------------------------------
# Plans built from the CSV
# ---------------------------------------------------------------------------

@dataclass
class TrackPlan:
    title: str
    artist: str
    duration_raw: str
    duration_mmss: str
    duration_ms: Optional[int]
    isrc: str
    iswc: str
    writer_composers: List[str]
    source_row_number: int
    existing_recording: Optional[LookupHit] = None
    existing_work: Optional[LookupHit] = None
    external_links: List[ExternalLink] = field(default_factory=list)
    discrepancies: List[Discrepancy] = field(default_factory=list)


@dataclass
class ReleasePlan:
    title: str
    release_artist: str
    release_label: str
    release_date_raw: str
    release_date_iso: str
    year: str
    upc: str
    catalog_number: str
    status: str
    primary_type: str
    medium_format: str
    artist_hit: Optional[LookupHit]
    label_hit: Optional[LookupHit]
    release_hit: Optional[LookupHit]
    release_group_hit: Optional[LookupHit]
    tracks: List[TrackPlan]
    external_links: List[ExternalLink] = field(default_factory=list)
    discrepancies: List[Discrepancy] = field(default_factory=list)
    cover_art_url: str = ""
    credited_artists: Dict[str, str] = field(default_factory=dict)  # normalized name -> mbid, for artist credits
    external_status: Dict[str, str] = field(default_factory=dict)  # source -> "found" | "missing"
    site_url: str = ""        # artist-website page for this release (seeded as "discography entry")
    site_cover_url: str = ""  # cover image on the artist website (fallback thumbnail / CAA upload source)

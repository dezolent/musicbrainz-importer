from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LookupHit:
    mbid: str
    name: str
    score: int
    url: str
    extra: Dict[str, Any] = field(default_factory=dict)


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

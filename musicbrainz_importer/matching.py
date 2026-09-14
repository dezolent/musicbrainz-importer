"""
Local matching of catalog rows against an ArtistCatalog snapshot.

Every function here is pure: it takes the snapshot plus the CSV-derived values
and returns a LookupHit (or None). Identifier matches (ISRC, barcode, ISWC) are
"exact"; normalized-title matches are "strong"; similarity matches are "fuzzy".
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable, Iterable, List, Optional, Sequence, TypeVar

from .models import ArtistCatalog, LookupHit, MBRecording, MBRelease, MBWork
from .utils import clean_value, mb_entity_url, normalize_iswc, normalize_text, normalize_upc

FUZZY_THRESHOLD = 0.85

_FEAT_RE = re.compile(r"[\(\[\-–—]?\s*\b(?:feat|ft|featuring)\.?\s+[^\)\]]*[\)\]]?", re.IGNORECASE)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Title helpers
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    """Collapse a title to a comparable key.

    Strips "feat. X" clauses, then drops every non-alphanumeric character so
    "Gone - Coptr Remix", "Gone (Coptr Remix)" and "gone coptr remix" all agree.
    """
    text = clean_value(title)
    text = _FEAT_RE.sub(" ", text)
    return normalize_text(text)


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _credit_matches(artist_credit: str, artist: str) -> bool:
    wanted = normalize_text(artist)
    return bool(wanted) and wanted in normalize_text(artist_credit)


def _pick_by_title(
        items: Sequence[T],
        title: str,
        get_title: Callable[[T], str],
        prefer: Callable[[T], bool],
) -> tuple[Optional[T], str, float]:
    """Return (item, confidence, similarity) using exact-normalized then fuzzy title matching."""
    wanted = normalize_title(title)
    if not wanted:
        return None, "", 0.0

    exact = [item for item in items if normalize_title(get_title(item)) == wanted]
    if exact:
        preferred = [item for item in exact if prefer(item)]
        return (preferred or exact)[0], "strong", 1.0

    best: Optional[T] = None
    best_ratio = 0.0
    for item in items:
        ratio = title_similarity(get_title(item), title)
        if ratio > best_ratio or (ratio == best_ratio and best is not None and prefer(item) and not prefer(best)):
            best, best_ratio = item, ratio
    if best is not None and best_ratio >= FUZZY_THRESHOLD:
        return best, "fuzzy", best_ratio
    return None, "", best_ratio


def _hit(entity: str, mbid: str, name: str, confidence: str, method: str, similarity: float, extra: dict) -> LookupHit:
    return LookupHit(
        mbid=mbid,
        name=name,
        score=100 if confidence == "exact" else int(round(similarity * 100)),
        url=mb_entity_url(entity, mbid),
        extra=extra,
        confidence=confidence,
        method=method,
    )


# ---------------------------------------------------------------------------
# Recordings
# ---------------------------------------------------------------------------

def _recording_extra(rec: MBRecording) -> dict:
    return {
        "artist_credit": rec.artist_credit,
        "isrcs": list(rec.isrcs),
        "length_ms": rec.length_ms,
        "first_release_date": rec.first_release_date,
    }


def match_recording(
        catalog: ArtistCatalog,
        title: str,
        isrc: str,
        artist: str,
        length_ms: Optional[int] = None,
) -> Optional[LookupHit]:
    wanted_isrc = re.sub(r"[^A-Z0-9]", "", clean_value(isrc).upper())
    if wanted_isrc:
        by_isrc = [rec for rec in catalog.recordings if wanted_isrc in {i.upper() for i in rec.isrcs}]
        if by_isrc:
            rec = by_isrc[0]
            extra = _recording_extra(rec)
            if len(by_isrc) > 1:
                extra["duplicate_mbids"] = [r.mbid for r in by_isrc[1:]]
            return _hit("recording", rec.mbid, rec.title, "exact", "isrc", 1.0, extra)

    def prefer(rec: MBRecording) -> bool:
        if not _credit_matches(rec.artist_credit, artist):
            return False
        if length_ms and rec.length_ms:
            return abs(rec.length_ms - length_ms) <= 3000
        return True

    rec, confidence, ratio = _pick_by_title(catalog.recordings, title, lambda r: r.title, prefer)
    if rec is None:
        return None
    return _hit("recording", rec.mbid, rec.title, confidence, "title", ratio, _recording_extra(rec))


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------

def _barcode_key(value: str) -> str:
    return normalize_upc(value).lstrip("0")


def _release_extra(rel: MBRelease) -> dict:
    return {
        "artist_credit": rel.artist_credit,
        "barcode": rel.barcode,
        "date": rel.date,
        "country": rel.country,
        "status": rel.status,
        "labels": [list(label) for label in rel.labels],
        "release_group_mbid": rel.release_group_mbid,
        "release_group_type": rel.release_group_type,
        "track_count": len(rel.tracks),
        "has_cover_art": rel.has_cover_art,
    }


def match_release(
        catalog: ArtistCatalog,
        title: str,
        upc: str,
        artist: str,
        catalog_number: str,
) -> Optional[LookupHit]:
    wanted_barcode = _barcode_key(upc)
    if wanted_barcode:
        for rel in catalog.releases:
            if rel.barcode and _barcode_key(rel.barcode) == wanted_barcode:
                return _hit("release", rel.mbid, rel.title, "exact", "barcode", 1.0, _release_extra(rel))

    wanted_catno = normalize_text(catalog_number)
    if wanted_catno:
        for rel in catalog.releases:
            if any(normalize_text(catno) == wanted_catno for _, _, catno in rel.labels):
                return _hit("release", rel.mbid, rel.title, "exact", "catalog_number", 1.0, _release_extra(rel))

    rel, confidence, ratio = _pick_by_title(
        catalog.releases, title, lambda r: r.title, lambda r: _credit_matches(r.artist_credit, artist)
    )
    if rel is None:
        return None
    return _hit("release", rel.mbid, rel.title, confidence, "title", ratio, _release_extra(rel))


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

def _work_extra(work: MBWork) -> dict:
    return {"iswcs": list(work.iswcs), "writers": list(work.writers)}


def match_work(
        catalog: ArtistCatalog,
        title: str,
        iswc: str,
        writers: Iterable[str],
) -> Optional[LookupHit]:
    wanted_iswc = normalize_iswc(iswc)
    if wanted_iswc:
        by_iswc = [w for w in catalog.works if wanted_iswc in {normalize_iswc(i) for i in w.iswcs}]
        if by_iswc:
            work = by_iswc[0]
            extra = _work_extra(work)
            if len(by_iswc) > 1:
                extra["duplicate_mbids"] = [w.mbid for w in by_iswc[1:]]
            return _hit("work", work.mbid, work.title, "exact", "iswc", 1.0, extra)

    wanted_writers = {normalize_text(w) for w in writers if clean_value(w)}

    def prefer(work: MBWork) -> bool:
        return bool(wanted_writers & {normalize_text(w) for w in work.writers})

    work, confidence, ratio = _pick_by_title(catalog.works, title, lambda w: w.title, prefer)
    if work is None:
        return None
    return _hit("work", work.mbid, work.title, confidence, "title", ratio, _work_extra(work))

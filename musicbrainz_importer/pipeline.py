"""
Build ReleasePlans from grouped CSV rows: match against the artist catalog snapshot,
fall back to ws/2 search for anything unmatched, then collect discrepancies.
"""

from __future__ import annotations

import sys
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from .client import MusicBrainzClient, pick_best_hit
from .discrepancies import compare_release, compare_track, compare_work, validate_release
from .external.coverart import cover_art_url
from .external.links import build_external_links
from .matching import match_recording, match_release, match_work, normalize_title
from .models import ArtistCatalog, LookupHit, ReleasePlan, TrackPlan
from .utils import build_work_queries, clean_value, mb_entity_url, normalize_text, normalize_upc, parse_duration, parse_release_date


def _collect_writer_composers(row: Dict[str, str]) -> List[str]:
    names = []
    for idx in (1, 2, 3):
        value = clean_value(row.get(f"Writer/Composer {idx}"))
        if value:
            names.append(value)
    return names


def _infer_primary_type(track_count: int, multi_track_primary_type: str = "") -> str:
    return "Single" if track_count == 1 else multi_track_primary_type


def _exact_hit(entity: str, mbid: str, name: str, method: str, extra: Optional[dict] = None) -> LookupHit:
    return LookupHit(mbid=mbid, name=name, score=100, url=mb_entity_url(entity, mbid),
                     extra=extra or {}, confidence="exact", method=method)


def _artist_hit(catalog: Optional[ArtistCatalog], full_artist: str) -> Optional[LookupHit]:
    if catalog and normalize_text(catalog.artist_name) in normalize_text(full_artist):
        return _exact_hit("artist", catalog.artist_mbid, catalog.artist_name, "mbid")
    return None


MAX_CONSECUTIVE_FAILURES = 2


def _same_title(hit: Optional[LookupHit], title: str) -> Optional[LookupHit]:
    """Accept a search hit only when its title matches the CSV title after normalization."""
    if hit and normalize_title(hit.name) == normalize_title(title):
        return hit
    return None


class _SearchFallback:
    """ws/2 search used only for items the snapshot could not resolve.

    Stops issuing requests once MusicBrainz has failed MAX_CONSECUTIVE_FAILURES
    times in a row, so a busy server cannot turn a run into a retry storm.
    """

    def __init__(self, mb: MusicBrainzClient, catalog: Optional[ArtistCatalog], lookup_limit: int, artist_filter: Optional[str]):
        self.mb = mb
        self.arid = catalog.artist_mbid if catalog else ""
        self.artist_name = catalog.artist_name if catalog else (artist_filter or "")
        self.limit = lookup_limit
        self.label_cache: Dict[str, Optional[LookupHit]] = {}
        self.artist_cache: Dict[str, Optional[LookupHit]] = {}
        self._tripped = False

    def _search(self, entity: str, query: str) -> list:
        if self._tripped:
            return []
        if getattr(self.mb, "consecutive_failures", 0) >= MAX_CONSECUTIVE_FAILURES:
            self._tripped = True
            print("  MusicBrainz keeps failing; skipping remaining search lookups for this run.", file=sys.stderr)
            return []
        return self.mb.search(entity, query, limit=self.limit)

    def _artist_clause(self) -> str:
        if self.arid:
            return f" AND arid:{self.arid}"
        if self.artist_name:
            return f' AND artist:"{self.artist_name}"'
        return ""

    def artist(self, name: str) -> Optional[LookupHit]:
        if name not in self.artist_cache:
            results = self._search("artist", f'artist:"{name}"') if name else []
            hit = pick_best_hit("artist", results, expected_name=name)
            self.artist_cache[name] = hit if hit and normalize_text(hit.name) == normalize_text(name) else None
        return self.artist_cache[name]

    def label(self, name: str) -> Optional[LookupHit]:
        if name not in self.label_cache:
            results = self._search("label", f'label:"{name}"') if name else []
            hit = pick_best_hit("label", results, expected_name=name)
            self.label_cache[name] = hit if hit and normalize_text(hit.name) == normalize_text(name) else None
        return self.label_cache[name]

    def release(self, title: str, upc: str, artist: str) -> Optional[LookupHit]:
        results = self._search("release", f"barcode:{upc}") if upc else []
        if results:
            hit = pick_best_hit("release", results, expected_name=title, expected_artist=artist)
            if hit:
                hit.method = "barcode"
                return hit
        if title:
            results = self._search("release", f'release:"{title}"{self._artist_clause()}')
        return _same_title(pick_best_hit("release", results, expected_name=title, expected_artist=artist), title)

    def release_group(self, title: str, artist: str) -> Optional[LookupHit]:
        results = self._search("release-group", f'releasegroup:"{title}"{self._artist_clause()}') if title else []
        return _same_title(pick_best_hit("release-group", results, expected_name=title, expected_artist=artist), title)

    def recording(self, title: str, isrc: str, artist: str) -> Optional[LookupHit]:
        results = self._search("recording", f"isrc:{isrc}") if isrc else []
        if results:
            hit = pick_best_hit("recording", results, expected_name=title, expected_artist=artist)
            if hit:
                hit.method = "isrc"
                return hit
        if title:
            results = self._search("recording", f'recording:"{title}"{self._artist_clause()}')
        return _same_title(pick_best_hit("recording", results, expected_name=title, expected_artist=artist), title)

    def work(self, title: str, writers: List[str], iswc: str) -> Optional[LookupHit]:
        for query in build_work_queries(title=title, writers=writers, iswc=iswc):
            results = self._search("work", query)
            if results:
                hit = pick_best_hit("work", results, expected_name=title)
                if query.startswith("iswc:") and hit:
                    hit.method = "iswc"
                    return hit
                return _same_title(hit, title)
        return None


def build_release_plans(
        grouped_rows: "OrderedDict[Tuple[str, ...], List[Dict[str, str]]]",
        mb: MusicBrainzClient,
        catalog: Optional[ArtistCatalog],
        lookup_limit: int,
        status: str,
        medium_format: str,
        multi_track_primary_type: str,
        artist_filter: Optional[str] = None,
        search_fallback: bool = False,
) -> List[ReleasePlan]:
    """Build plans. With a catalog snapshot the snapshot is authoritative for releases,
    release groups, recordings and works; ws/2 search is only used for labels unless
    search_fallback is True. Without a snapshot, search is the only source."""
    plans: List[ReleasePlan] = []
    fallback = _SearchFallback(mb, catalog, lookup_limit, artist_filter)
    entity_search = catalog is None or search_fallback
    total_tracks = sum(len(rows) for rows in grouped_rows.values())
    track_index = 0

    for release_rows in grouped_rows.values():
        first = release_rows[0]
        release_artist = clean_value(first.get("Release Artist") or first.get("Artist"))
        release_title = clean_value(first.get("Release") or first.get("Title"))
        release_label = clean_value(first.get("Release Label"))
        upc = normalize_upc(first.get("UPC", ""))
        catalog_number = clean_value(first.get("Catalog Number"))
        release_date_iso, _ = parse_release_date(first.get("Release Date", ""))
        print(f"\nRelease: {release_artist} – {release_title}", file=sys.stderr)

        artist_hit = _artist_hit(catalog, release_artist) or fallback.artist(release_artist)

        release_hit = match_release(catalog, release_title, upc, release_artist, catalog_number) if catalog else None
        if release_hit is None and entity_search:
            release_hit = fallback.release(release_title, upc, release_artist)

        release_group_hit: Optional[LookupHit] = None
        if release_hit and release_hit.extra.get("release_group_mbid"):
            release_group_hit = _exact_hit("release-group", release_hit.extra["release_group_mbid"], release_hit.name,
                                           "release", {"primary_type": release_hit.extra.get("release_group_type", "")})
        if release_group_hit is None and entity_search:
            release_group_hit = fallback.release_group(release_title, release_artist)

        label_hit: Optional[LookupHit] = None
        if release_hit:
            for name, mbid, _catno in release_hit.extra.get("labels") or []:
                if mbid and normalize_text(name) == normalize_text(release_label):
                    label_hit = _exact_hit("label", mbid, name, "release")
                    break
        if label_hit is None:
            label_hit = fallback.label(release_label)

        tracks: List[TrackPlan] = []
        for track_row in release_rows:
            title = clean_value(track_row.get("Title"))
            artist = clean_value(track_row.get("Artist") or release_artist)
            duration_mmss, duration_ms = parse_duration(track_row.get("Duration", ""))
            isrc = clean_value(track_row.get("ISRC"))
            iswc = clean_value(track_row.get("ISWC"))
            writers = _collect_writer_composers(track_row)

            recording_hit = match_recording(catalog, title, isrc, artist, duration_ms) if catalog else None
            if recording_hit is None and entity_search:
                recording_hit = fallback.recording(title, isrc, artist)

            work_hit = match_work(catalog, title, iswc, writers) if catalog else None
            if work_hit is None and entity_search:
                work_hit = fallback.work(title, writers, iswc)

            track = TrackPlan(
                title=title, artist=artist,
                duration_raw=clean_value(track_row.get("Duration")), duration_mmss=duration_mmss, duration_ms=duration_ms,
                isrc=isrc, iswc=iswc, writer_composers=writers,
                source_row_number=int(track_row["__row_number__"]),
                existing_recording=recording_hit, existing_work=work_hit,
            )
            if recording_hit:
                track.discrepancies.extend(compare_track(track, recording_hit))
            if work_hit:
                track.discrepancies.extend(compare_work(track, work_hit))
            tracks.append(track)

            track_index += 1
            width = len(str(total_tracks))
            rec_status = f"recording: {'✅ ' + recording_hit.confidence if recording_hit else '❌'}"
            work_status = f"work: {'✅ ' + work_hit.confidence if work_hit else '❌'}"
            print(f"  [{track_index:>{width}}/{total_tracks}] {artist} – {title}  |  {rec_status}  |  {work_status}", file=sys.stderr)

        plan = ReleasePlan(
            title=release_title, release_artist=release_artist, release_label=release_label,
            release_date_raw=clean_value(first.get("Release Date")), release_date_iso=release_date_iso,
            year=clean_value(first.get("Year")), upc=upc, catalog_number=catalog_number,
            status=status, primary_type=_infer_primary_type(len(tracks), multi_track_primary_type),
            medium_format=medium_format,
            artist_hit=artist_hit, label_hit=label_hit, release_hit=release_hit, release_group_hit=release_group_hit,
            tracks=tracks,
        )
        if catalog:
            plan.credited_artists = dict(catalog.artist_index)
        plan.external_links = build_external_links(
            csv_discogs=clean_value(first.get("Discogs")),
            csv_asin=clean_value(first.get("Amazon ASIN")),
        )
        plan.discrepancies.extend(validate_release(plan))
        if release_hit:
            plan.discrepancies.extend(compare_release(plan, release_hit))
            if release_hit.extra.get("has_cover_art"):
                plan.cover_art_url = cover_art_url(release_hit.mbid)
        plans.append(plan)

    return plans

"""
CSV reading, row grouping, and release plan construction.
"""

from __future__ import annotations

import csv
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .client import MusicBrainzClient, pick_best_hit
from .models import ReleasePlan, TrackPlan
from .utils import (
    build_work_queries,
    clean_value,
    normalize_text,
    normalize_upc,
    parse_duration,
    parse_release_date,
)


MB_CSV_COLUMN = "MusicBrainz"


def read_catalog(csv_path: Path, artist_filter: Optional[str] = None) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=2):  # header is row 1
            cleaned = {key: clean_value(value) for key, value in row.items()}
            cleaned["__row_number__"] = str(idx)
            if artist_filter and normalize_text(artist_filter) not in normalize_text(cleaned.get("Artist", "")):
                continue
            rows.append(cleaned)
    return rows


def group_rows_into_releases(
        rows: List[Dict[str, str]],
) -> OrderedDict[Tuple[str, ...], List[Dict[str, str]]]:
    grouped: OrderedDict[Tuple[str, ...], List[Dict[str, str]]] = OrderedDict()
    for row in rows:
        key = (
            clean_value(row.get("Release Artist") or row.get("Artist")),
            clean_value(row.get("Release") or row.get("Title")),
            normalize_upc(row.get("UPC", "")),
            clean_value(row.get("Catalog Number")),
            clean_value(row.get("Release Label")),
            clean_value(row.get("Release Date")),
        )
        grouped.setdefault(key, []).append(row)
    return grouped


def _collect_writer_composers(row: Dict[str, str]) -> List[str]:
    names = []
    for idx in (1, 2, 3):
        value = clean_value(row.get(f"Writer/Composer {idx}"))
        if value:
            names.append(value)
    return names


def _infer_primary_type(track_count: int, multi_track_primary_type: str = "") -> str:
    if track_count == 1:
        return "Single"
    return multi_track_primary_type


def _query_artist(full_artist: str, artist_filter: Optional[str]) -> str:
    """Return the best single-artist name to use in MusicBrainz search queries.

    MusicBrainz Lucene queries don't handle multi-artist strings like
    'Dezolent & Tomentam' well — the & is treated as a query operator and
    the compound name won't match a single artist index entry.

    When the full artist is a collaboration that contains the CLI filter
    artist, use the filter artist alone as the search term instead.
    """
    if artist_filter and normalize_text(artist_filter) in normalize_text(full_artist):
        return artist_filter
    return full_artist


def build_release_plans(
        grouped_rows: OrderedDict[Tuple[str, ...], List[Dict[str, str]]],
        mb: MusicBrainzClient,
        lookup_limit: int,
        status: str,
        medium_format: str,
        multi_track_primary_type: str,
        artist_filter: Optional[str] = None,
) -> List[ReleasePlan]:
    plans: List[ReleasePlan] = []
    artist_cache: Dict[str, Optional[object]] = {}
    label_cache: Dict[str, Optional[object]] = {}

    total_tracks = sum(len(rows) for rows in grouped_rows.values())
    track_index = 0

    for (_, _, _, _, _, _), release_rows in grouped_rows.items():
        first = release_rows[0]
        release_artist = clean_value(first.get("Release Artist") or first.get("Artist"))
        release_title = clean_value(first.get("Release") or first.get("Title"))
        release_label = clean_value(first.get("Release Label"))
        upc = normalize_upc(first.get("UPC", ""))
        catalog_number = clean_value(first.get("Catalog Number"))
        release_date_iso, _ = parse_release_date(first.get("Release Date", ""))
        year = clean_value(first.get("Year"))

        print(f"\nRelease: {release_artist} – {release_title}", file=sys.stderr)

        search_artist = _query_artist(release_artist, artist_filter)

        if release_artist not in artist_cache:
            results = mb.search("artist", f'artist:"{search_artist}"', limit=lookup_limit) if search_artist else []
            artist_cache[release_artist] = pick_best_hit("artist", results, expected_name=release_artist)
        artist_hit = artist_cache[release_artist]

        if release_label not in label_cache:
            results = mb.search("label", f'label:"{release_label}"', limit=lookup_limit) if release_label else []
            label_cache[release_label] = pick_best_hit("label", results, expected_name=release_label)
        label_hit = label_cache[release_label]

        if upc:
            release_results = mb.search("release", f"barcode:{upc}", limit=lookup_limit)
        else:
            q = f'release:"{release_title}"'
            if search_artist:
                q += f' AND artist:"{search_artist}"'
            release_results = mb.search("release", q, limit=lookup_limit)
        release_hit = pick_best_hit("release", release_results, expected_name=release_title, expected_artist=release_artist)

        rg_query = f'releasegroup:"{release_title}"'
        if search_artist:
            rg_query += f' AND artist:"{search_artist}"'
        rg_results = mb.search("release-group", rg_query, limit=lookup_limit)
        release_group_hit = pick_best_hit("release-group", rg_results, expected_name=release_title, expected_artist=release_artist)

        tracks: List[TrackPlan] = []
        for track_row in release_rows:
            title = clean_value(track_row.get("Title"))
            artist = clean_value(track_row.get("Artist") or release_artist)
            duration_mmss, duration_ms = parse_duration(track_row.get("Duration", ""))
            isrc = clean_value(track_row.get("ISRC"))
            iswc = clean_value(track_row.get("ISWC"))
            writers = _collect_writer_composers(track_row)

            search_track_artist = _query_artist(artist, artist_filter)

            if isrc:
                recording_results = mb.search("recording", f"isrc:{isrc}", limit=lookup_limit)
            else:
                q = f'recording:"{title}"'
                if search_track_artist:
                    q += f' AND artist:"{search_track_artist}"'
                recording_results = mb.search("recording", q, limit=lookup_limit)
            recording_hit = pick_best_hit("recording", recording_results, expected_name=title, expected_artist=artist)

            work_results = []
            for work_query in build_work_queries(title=title, writers=writers, iswc=iswc):
                work_results = mb.search("work", work_query, limit=lookup_limit)
                if work_results:
                    break
            work_hit = pick_best_hit("work", work_results, expected_name=title)

            track_index += 1
            rec_status = "recording: ✅" if recording_hit else "recording: ❌"
            work_status = "work: ✅" if work_hit else "work: ❌"
            print(f"  [{track_index:>{len(str(total_tracks))}}/{total_tracks}] {artist} – {title}  |  {rec_status}  |  {work_status}", file=sys.stderr)

            tracks.append(TrackPlan(
                title=title,
                artist=artist,
                duration_raw=clean_value(track_row.get("Duration")),
                duration_mmss=duration_mmss,
                duration_ms=duration_ms,
                isrc=isrc,
                iswc=iswc,
                writer_composers=writers,
                source_row_number=int(track_row["__row_number__"]),
                existing_recording=recording_hit,
                existing_work=work_hit,
            ))

        plans.append(ReleasePlan(
            title=release_title,
            release_artist=release_artist,
            release_label=release_label,
            release_date_raw=clean_value(first.get("Release Date")),
            release_date_iso=release_date_iso,
            year=year,
            upc=upc,
            catalog_number=catalog_number,
            status=status,
            primary_type=_infer_primary_type(len(tracks), multi_track_primary_type=multi_track_primary_type),
            medium_format=medium_format,
            artist_hit=artist_hit,
            label_hit=label_hit,
            release_hit=release_hit,
            release_group_hit=release_group_hit,
            tracks=tracks,
        ))

    return plans


def update_csv_with_mb_urls(csv_path: Path, plans: List[ReleasePlan]) -> int:
    """Write MusicBrainz release URLs back to the source CSV.

    For each release plan that has a confirmed release_hit, every track row
    belonging to that release gets the release URL written to the MusicBrainz
    column. Rows that already have a value in that column are left untouched.
    If the column doesn't exist it is appended.

    Returns the number of rows updated.
    """
    url_by_row: Dict[int, str] = {}
    for plan in plans:
        if not plan.release_hit:
            continue
        for track in plan.tracks:
            url_by_row[track.source_row_number] = plan.release_hit.url

    if not url_by_row:
        return 0

    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames: List[str] = list(reader.fieldnames or [])
        rows: List[Dict[str, str]] = list(reader)

    if MB_CSV_COLUMN not in fieldnames:
        fieldnames.append(MB_CSV_COLUMN)

    updated = 0
    for idx, row in enumerate(rows, start=2):  # row 1 is the header
        row.setdefault(MB_CSV_COLUMN, "")
        if idx in url_by_row and not clean_value(row[MB_CSV_COLUMN]):
            row[MB_CSV_COLUMN] = url_by_row[idx]
            updated += 1

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    return updated

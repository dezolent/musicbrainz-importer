"""
CSV reading, row grouping, and CSV write-back.
"""

from __future__ import annotations

import csv
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import ReleasePlan
from .utils import clean_value, normalize_text, normalize_upc


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

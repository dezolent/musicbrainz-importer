"""
General-purpose helpers for data cleaning, parsing, and URL building.
None of these functions have side effects or depend on external state.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from .constants import MB_BASE


# ---------------------------------------------------------------------------
# String / value cleaning
# ---------------------------------------------------------------------------

def clean_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def normalize_text(text: str) -> str:
    text = clean_value(text).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def normalize_upc(value: str) -> str:
    return re.sub(r"\D", "", clean_value(value))


def normalize_iswc(value: str) -> str:
    """Return compact ISWC like T3294665304 from various input formats."""
    raw = clean_value(value).upper()
    raw = re.sub(r"[^A-Z0-9]", "", raw)
    if raw.startswith("T") and len(raw) == 11 and raw[1:].isdigit():
        return raw
    return raw


def format_iswc_for_mb(value: str) -> str:
    """Return MusicBrainz-style ISWC like T-329.466.530-4 when possible."""
    compact = normalize_iswc(value)
    if compact.startswith("T") and len(compact) == 11 and compact[1:].isdigit():
        digits = compact[1:]
        return f"T-{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9]}"
    return clean_value(value)


def html_escape(value: Any) -> str:
    return html.escape(clean_value(value), quote=True)


def slugify(value: str) -> str:
    value = clean_value(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "item"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_release_date(value: str) -> Tuple[str, Dict[str, str]]:
    raw = clean_value(value)
    if not raw:
        return "", {"year": "", "month": "", "day": ""}

    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d"), {
                "year": f"{dt.year:04d}",
                "month": f"{dt.month:02d}",
                "day": f"{dt.day:02d}",
            }
        except ValueError:
            continue

    return raw, {"year": "", "month": "", "day": ""}


def parse_duration(value: str) -> Tuple[str, Optional[int]]:
    raw = clean_value(value)
    if not raw:
        return "", None

    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})", raw)
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        total_seconds = hours * 3600 + minutes * 60 + seconds
        return f"{total_seconds // 60}:{total_seconds % 60:02d}", total_seconds * 1000

    match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        total_seconds = minutes * 60 + seconds
        return f"{minutes}:{seconds:02d}", total_seconds * 1000

    return raw, None


# ---------------------------------------------------------------------------
# Work query building
# ---------------------------------------------------------------------------

def build_work_queries(title: str, writers: List[str], iswc: str) -> List[str]:
    queries: List[str] = []
    compact_iswc = normalize_iswc(iswc)
    pretty_iswc = format_iswc_for_mb(iswc)

    if pretty_iswc and pretty_iswc != clean_value(iswc):
        queries.append(f'iswc:"{pretty_iswc}"')
        queries.append(f'iswc:{pretty_iswc}')
    if compact_iswc:
        queries.append(f'iswc:"{compact_iswc}"')
        queries.append(f'iswc:{compact_iswc}')

    work_query = f'work:"{title}"'
    if writers:
        work_query += f' AND artist:"{writers[0]}"'
    queries.append(work_query)

    if title:
        queries.append(f'work:"{title}"')

    seen: set = set()
    deduped: List[str] = []
    for query in queries:
        if query and query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped


# ---------------------------------------------------------------------------
# MusicBrainz URL builders
# ---------------------------------------------------------------------------

def mb_entity_url(entity: str, mbid: str) -> str:
    return f"{MB_BASE}/{entity}/{mbid}"


def mb_search_url(query: str, entity_type: str) -> str:
    return f"{MB_BASE}/search?query={quote_plus(query)}&type={quote_plus(entity_type)}&method=indexed"


def mb_create_artist_url(name: str) -> str:
    return f"{MB_BASE}/artist/create?edit-artist.name={quote_plus(name)}"


def mb_create_label_url(name: str) -> str:
    return f"{MB_BASE}/label/create?edit-label.name={quote_plus(name)}"


def mb_create_work_url(name: str) -> str:
    return f"{MB_BASE}/work/create?edit-work.name={quote_plus(name)}"

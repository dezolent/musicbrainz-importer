#!/usr/bin/env python3
"""
Generate a MusicBrainz seeding dashboard from a song catalog CSV.

What this script does:
- Reads a catalog CSV like your uploaded song database.
- Groups rows into releases using release-level fields.
- Looks up likely existing MusicBrainz entities via /ws/2.
- Generates an HTML dashboard with:
    * one-click seeded Add Release forms (official POST seeding flow)
    * search/open links for artist, label, release group, release, recordings, and works
    * name-seeded Add Work / Add Artist / Add Label links for anything missing
- Writes a JSON sidecar with the normalized plan and lookup results.

What it does NOT do:
- It does not directly create releases/works via a write API.
- It does not submit ISRC/barcode XML edits.
- It does not create work relationships automatically.

Usage:
    python mb_seed_from_csv.py "_Song Database.csv" --artist Dezolent
    python mb_seed_from_csv.py "_Song Database.csv" --artist Dezolent --release-country XW --out musicbrainz_seed.html

Notes:
- MusicBrainz asks clients not to exceed 1 request per second to /ws/2.
- Release seeding is supported through POSTing form fields to /release/add.
- Non-release forms such as Add Work / Add Label can be seeded through query parameters.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus

try:
    import requests
except ImportError:  # pragma: no cover
    print("This script requires the 'requests' package. Install it with: pip install requests", file=sys.stderr)
    raise


MB_BASE = "https://musicbrainz.org"
WS_BASE = f"{MB_BASE}/ws/2"
DEFAULT_UA = "dezolent-musicbrainz-importer/0.1 (dezolent@gmail.com"
RATE_LIMIT_SECONDS = 1.1

ENTITY_COLLECTION_KEYS = {
    "artist": "artists",
    "label": "labels",
    "release": "releases",
    "release-group": "release-groups",
    "recording": "recordings",
    "work": "works",
}


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


class MusicBrainzClient:
    def __init__(self, user_agent: str, enabled: bool = True) -> None:
        self.enabled = enabled
        self._last_call = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json",
        })

    def _throttle(self) -> None:
        if not self.enabled:
            return
        delta = time.monotonic() - self._last_call
        if delta < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - delta)

    def search(self, entity: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        self._throttle()
        url = f"{WS_BASE}/{entity}/"
        params = {"query": query, "fmt": "json", "limit": limit}
        response = self.session.get(url, params=params, timeout=30)
        self._last_call = time.monotonic()
        response.raise_for_status()
        payload = response.json()
        return payload.get(ENTITY_COLLECTION_KEYS[entity], [])


# ----------------------------
# Generic helpers
# ----------------------------

def clean_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def normalize_text(text: str) -> str:
    text = clean_value(text).lower()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def normalize_upc(value: str) -> str:
    digits = re.sub(r"\D", "", clean_value(value))
    return digits


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


def build_work_queries(title: str, writers: List[str], iswc: str) -> List[str]:
    queries: List[str] = []
    compact_iswc = normalize_iswc(iswc)
    pretty_iswc = format_iswc_for_mb(iswc)

    # Prefer exact ISWC lookups first. MusicBrainz documents `iswc` as a work search field.
    if pretty_iswc and pretty_iswc != clean_value(iswc):
        queries.append(f'iswc:"{pretty_iswc}"')
        queries.append(f'iswc:{pretty_iswc}')
    if compact_iswc:
        queries.append(f'iswc:"{compact_iswc}"')
        queries.append(f'iswc:{compact_iswc}')

    # Fall back to title + writer.
    work_query = f'work:"{title}"'
    if writers:
        work_query += f' AND artist:"{writers[0]}"'
    queries.append(work_query)

    # Last resort: title only.
    if title:
        queries.append(f'work:"{title}"')

    # De-duplicate while preserving order.
    seen = set()
    deduped: List[str] = []
    for query in queries:
        if query and query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped


def parse_release_date(value: str) -> Tuple[str, Dict[str, str]]:
    raw = clean_value(value)
    if not raw:
        return "", {"year": "", "month": "", "day": ""}

    formats = ["%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d"), {
                "year": f"{dt.year:04d}",
                "month": f"{dt.month:02d}",
                "day": f"{dt.day:02d}",
            }
        except ValueError:
            continue

    # Partial fallback: try to keep user-visible raw value while leaving date pieces blank.
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
        mmss = f"{total_seconds // 60}:{total_seconds % 60:02d}"
        return mmss, total_seconds * 1000

    match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        total_seconds = minutes * 60 + seconds
        return f"{minutes}:{seconds:02d}", total_seconds * 1000

    return raw, None


def html_escape(value: Any) -> str:
    return html.escape(clean_value(value), quote=True)


def slugify(value: str) -> str:
    value = clean_value(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "item"


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


def render_artist_credit(artist_credit: Iterable[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for item in artist_credit or []:
        name = clean_value(item.get("name") or item.get("artist", {}).get("name"))
        joinphrase = clean_value(item.get("joinphrase") or item.get("join_phrase"))
        parts.append(name + joinphrase)
    return "".join(parts).strip()


def item_title(item: Dict[str, Any]) -> str:
    return clean_value(item.get("title") or item.get("name"))


def pick_best_hit(
        entity: str,
        candidates: List[Dict[str, Any]],
        expected_name: str,
        expected_artist: str = "",
) -> Optional[LookupHit]:
    if not candidates:
        return None

    expected_name_norm = normalize_text(expected_name)
    expected_artist_norm = normalize_text(expected_artist)
    ranked: List[Tuple[int, Dict[str, Any]]] = []

    for item in candidates:
        base_score = int(clean_value(item.get("score") or 0) or 0)
        title_norm = normalize_text(item_title(item))
        bonus = 0

        if title_norm == expected_name_norm and expected_name_norm:
            bonus += 200
        elif expected_name_norm and expected_name_norm in title_norm:
            bonus += 50

        if entity == "artist":
            artist_name = clean_value(item.get("name"))
        else:
            artist_name = render_artist_credit(item.get("artist-credit", []))
        artist_norm = normalize_text(artist_name)

        if expected_artist_norm and artist_norm == expected_artist_norm:
            bonus += 150
        elif expected_artist_norm and expected_artist_norm and expected_artist_norm in artist_norm:
            bonus += 30

        ranked.append((base_score + bonus, item))

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = ranked[0]
    mbid = clean_value(best.get("id"))
    if not mbid:
        return None

    display_name = item_title(best) if entity != "artist" else clean_value(best.get("name"))
    extra: Dict[str, Any] = {}
    if entity != "artist":
        artist_credit = render_artist_credit(best.get("artist-credit", []))
        if artist_credit:
            extra["artist_credit"] = artist_credit

    return LookupHit(
        mbid=mbid,
        name=display_name,
        score=best_score,
        url=mb_entity_url(entity, mbid),
        extra=extra,
    )


# ----------------------------
# CSV -> release plan
# ----------------------------

def read_catalog(csv_path: Path, artist_filter: Optional[str] = None) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=2):  # header is row 1
            cleaned = {key: clean_value(value) for key, value in row.items()}
            cleaned["__row_number__"] = str(idx)
            if artist_filter and normalize_text(cleaned.get("Artist", "")) != normalize_text(artist_filter):
                continue
            rows.append(cleaned)
    return rows


def group_rows_into_releases(rows: List[Dict[str, str]]) -> OrderedDict[Tuple[str, ...], List[Dict[str, str]]]:
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


def collect_writer_composers(row: Dict[str, str]) -> List[str]:
    names = []
    for idx in (1, 2, 3):
        value = clean_value(row.get(f"Writer/Composer {idx}"))
        if value:
            names.append(value)
    return names


def infer_primary_type(track_count: int, multi_track_primary_type: str = "") -> str:
    if track_count == 1:
        return "Single"
    return multi_track_primary_type


def build_release_plans(
        grouped_rows: OrderedDict[Tuple[str, ...], List[Dict[str, str]]],
        mb: MusicBrainzClient,
        lookup_limit: int,
        status: str,
        medium_format: str,
        multi_track_primary_type: str,
) -> List[ReleasePlan]:
    plans: List[ReleasePlan] = []

    artist_cache: Dict[str, Optional[LookupHit]] = {}
    label_cache: Dict[str, Optional[LookupHit]] = {}

    for (_release_artist, _release_title, _upc, _catalog_number, _label, _date), release_rows in grouped_rows.items():
        first = release_rows[0]
        release_artist = clean_value(first.get("Release Artist") or first.get("Artist"))
        release_title = clean_value(first.get("Release") or first.get("Title"))
        release_label = clean_value(first.get("Release Label"))
        upc = normalize_upc(first.get("UPC", ""))
        catalog_number = clean_value(first.get("Catalog Number"))
        release_date_iso, _date_parts = parse_release_date(first.get("Release Date", ""))
        year = clean_value(first.get("Year"))

        if release_artist not in artist_cache:
            artist_results = mb.search("artist", f'artist:"{release_artist}"', limit=lookup_limit) if release_artist else []
            artist_cache[release_artist] = pick_best_hit("artist", artist_results, expected_name=release_artist)
        artist_hit = artist_cache[release_artist]

        if release_label not in label_cache:
            label_results = mb.search("label", f'label:"{release_label}"', limit=lookup_limit) if release_label else []
            label_cache[release_label] = pick_best_hit("label", label_results, expected_name=release_label)
        label_hit = label_cache[release_label]

        if upc:
            release_results = mb.search("release", f"barcode:{upc}", limit=lookup_limit)
        else:
            release_query = f'release:"{release_title}"'
            if release_artist:
                release_query += f' AND artist:"{release_artist}"'
            release_results = mb.search("release", release_query, limit=lookup_limit)
        release_hit = pick_best_hit("release", release_results, expected_name=release_title, expected_artist=release_artist)

        rg_query = f'releasegroup:"{release_title}"'
        if release_artist:
            rg_query += f' AND artist:"{release_artist}"'
        release_group_results = mb.search("release-group", rg_query, limit=lookup_limit)
        release_group_hit = pick_best_hit("release-group", release_group_results, expected_name=release_title, expected_artist=release_artist)

        tracks: List[TrackPlan] = []
        for track_row in release_rows:
            title = clean_value(track_row.get("Title"))
            artist = clean_value(track_row.get("Artist") or release_artist)
            duration_mmss, duration_ms = parse_duration(track_row.get("Duration", ""))
            isrc = clean_value(track_row.get("ISRC"))
            iswc = clean_value(track_row.get("ISWC"))
            writers = collect_writer_composers(track_row)

            if isrc:
                recording_results = mb.search("recording", f"isrc:{isrc}", limit=lookup_limit)
            else:
                recording_query = f'recording:"{title}"'
                if artist:
                    recording_query += f' AND artist:"{artist}"'
                recording_results = mb.search("recording", recording_query, limit=lookup_limit)
            recording_hit = pick_best_hit("recording", recording_results, expected_name=title, expected_artist=artist)

            work_results: List[Dict[str, Any]] = []
            for work_query in build_work_queries(title=title, writers=writers, iswc=iswc):
                work_results = mb.search("work", work_query, limit=lookup_limit)
                if work_results:
                    break
            work_hit = pick_best_hit("work", work_results, expected_name=title)

            tracks.append(
                TrackPlan(
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
                )
            )

        plans.append(
            ReleasePlan(
                title=release_title,
                release_artist=release_artist,
                release_label=release_label,
                release_date_raw=clean_value(first.get("Release Date")),
                release_date_iso=release_date_iso,
                year=year,
                upc=upc,
                catalog_number=catalog_number,
                status=status,
                primary_type=infer_primary_type(len(tracks), multi_track_primary_type=multi_track_primary_type),
                medium_format=medium_format,
                artist_hit=artist_hit,
                label_hit=label_hit,
                release_hit=release_hit,
                release_group_hit=release_group_hit,
                tracks=tracks,
            )
        )

    return plans


# ----------------------------
# Release seeding helpers
# ----------------------------

def build_release_form_fields(
        plan: ReleasePlan,
        release_country: str,
        language: str,
        script: str,
        edit_note: str,
) -> List[Tuple[str, str]]:
    release_date_iso, date_parts = parse_release_date(plan.release_date_raw)

    fields: List[Tuple[str, str]] = [
        ("name", plan.title),
        ("status", plan.status),
        ("edit_note", edit_note.strip()),
    ]

    if plan.primary_type:
        fields.append(("type", plan.primary_type))
    if plan.upc:
        fields.append(("barcode", plan.upc))
    if language:
        fields.append(("language", language))
    if script:
        fields.append(("script", script))

    if date_parts["year"]:
        fields.append(("events.0.date.year", date_parts["year"]))
    if date_parts["month"]:
        fields.append(("events.0.date.month", date_parts["month"]))
    if date_parts["day"]:
        fields.append(("events.0.date.day", date_parts["day"]))
    if release_country:
        fields.append(("events.0.country", release_country))

    if plan.label_hit:
        fields.append(("labels.0.mbid", plan.label_hit.mbid))
    elif plan.release_label:
        fields.append(("labels.0.name", plan.release_label))
    if plan.catalog_number:
        fields.append(("labels.0.catalog_number", plan.catalog_number))

    if plan.artist_hit:
        fields.append(("artist_credit.names.0.mbid", plan.artist_hit.mbid))
        fields.append(("artist_credit.names.0.name", plan.release_artist))
    elif plan.release_artist:
        fields.append(("artist_credit.names.0.artist.name", plan.release_artist))
        fields.append(("artist_credit.names.0.name", plan.release_artist))

    fields.append(("mediums.0.format", plan.medium_format))
    for idx, track in enumerate(plan.tracks):
        fields.append((f"mediums.0.track.{idx}.number", str(idx + 1)))
        fields.append((f"mediums.0.track.{idx}.name", track.title))
        if track.duration_mmss:
            fields.append((f"mediums.0.track.{idx}.length", track.duration_mmss))
        # Track artist credit is omitted unless track artist differs from release artist.
        if normalize_text(track.artist) != normalize_text(plan.release_artist):
            fields.append((f"mediums.0.track.{idx}.artist_credit.names.0.artist.name", track.artist))
            fields.append((f"mediums.0.track.{idx}.artist_credit.names.0.name", track.artist))

    return [(name, clean_value(value)) for name, value in fields if clean_value(value)]


def render_hidden_inputs(fields: List[Tuple[str, str]]) -> str:
    return "\n".join(
        f'<input type="hidden" name="{html_escape(name)}" value="{html_escape(value)}">'
        for name, value in fields
    )


# ----------------------------
# Output rendering
# ----------------------------

def render_lookup_badge(hit: Optional[LookupHit], entity_label: str, search_url: str, create_url: str = "") -> str:
    if hit:
        return (
            f'<span class="hit ok">Found {html_escape(entity_label)}: '
            f'<a href="{html_escape(hit.url)}" target="_blank" rel="noreferrer">{html_escape(hit.name)}</a> '
            f'<small>(score {hit.score})</small></span>'
        )
    links = [f'<a href="{html_escape(search_url)}" target="_blank" rel="noreferrer">search</a>']
    if create_url:
        links.append(f'<a href="{html_escape(create_url)}" target="_blank" rel="noreferrer">create</a>')
    return f'<span class="hit warn">No match for {html_escape(entity_label)} ({" | ".join(links)})</span>'


def render_release_section(
        plan: ReleasePlan,
        release_country: str,
        language: str,
        script: str,
        edit_note: str,
) -> str:
    section_id = slugify(f"{plan.release_artist}-{plan.title}-{plan.catalog_number}")

    form_fields = build_release_form_fields(
        plan=plan,
        release_country=release_country,
        language=language,
        script=script,
        edit_note=edit_note,
    )
    hidden_inputs = render_hidden_inputs(form_fields)

    artist_search = mb_search_url(f'artist:"{plan.release_artist}"', "artist")
    label_search = mb_search_url(f'label:"{plan.release_label}"', "label")
    release_search = mb_search_url(f'release:"{plan.title}" AND artist:"{plan.release_artist}"', "release")
    rg_search = mb_search_url(f'releasegroup:"{plan.title}" AND artist:"{plan.release_artist}"', "release-group")

    track_rows: List[str] = []
    for idx, track in enumerate(plan.tracks, start=1):
        recording_search = mb_search_url(f'recording:"{track.title}" AND artist:"{track.artist}"', "recording")
        work_search_queries = build_work_queries(track.title, track.writer_composers, track.iswc)
        work_search = mb_search_url(work_search_queries[0], "work")
        work_create = mb_create_work_url(track.title)

        track_rows.append(
            f"""
            <tr>
              <td>{idx}</td>
              <td>
                <strong>{html_escape(track.title)}</strong><br>
                <small>Artist: {html_escape(track.artist)}</small>
              </td>
              <td>{html_escape(track.duration_mmss or track.duration_raw)}</td>
              <td>{html_escape(track.isrc)}</td>
              <td>{html_escape(track.iswc)}</td>
              <td>{html_escape(', '.join(track.writer_composers))}</td>
              <td>{render_lookup_badge(track.existing_recording, 'recording', recording_search)}</td>
              <td>{render_lookup_badge(track.existing_work, 'work', work_search, work_create)}</td>
              <td>{track.source_row_number}</td>
            </tr>
            """.strip()
        )

    return f"""
    <section id="{html_escape(section_id)}" class="release-card">
      <div class="release-head">
        <div>
          <h2>{html_escape(plan.title)}</h2>
          <div class="meta">
            <span><strong>Release artist:</strong> {html_escape(plan.release_artist)}</span>
            <span><strong>Date:</strong> {html_escape(plan.release_date_iso or plan.release_date_raw)}</span>
            <span><strong>Tracks:</strong> {len(plan.tracks)}</span>
            <span><strong>UPC:</strong> {html_escape(plan.upc)}</span>
            <span><strong>Catalog #:</strong> {html_escape(plan.catalog_number)}</span>
          </div>
        </div>
        <form action="{MB_BASE}/release/add" method="post" enctype="multipart/form-data" target="_blank" class="seed-form">
          {hidden_inputs}
          <button type="submit">Seed release editor</button>
        </form>
      </div>

      <div class="lookup-grid">
        {render_lookup_badge(plan.artist_hit, 'artist', artist_search, mb_create_artist_url(plan.release_artist))}
        {render_lookup_badge(plan.label_hit, 'label', label_search, mb_create_label_url(plan.release_label))}
        {render_lookup_badge(plan.release_group_hit, 'release group', rg_search)}
        {render_lookup_badge(plan.release_hit, 'release', release_search)}
      </div>

      <details>
        <summary>Release seeding fields</summary>
        <pre>{html_escape(json.dumps(form_fields, indent=2))}</pre>
      </details>

      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Track</th>
            <th>Length</th>
            <th>ISRC</th>
            <th>ISWC</th>
            <th>Writer(s)</th>
            <th>Recording</th>
            <th>Work</th>
            <th>CSV row</th>
          </tr>
        </thead>
        <tbody>
          {' '.join(track_rows)}
        </tbody>
      </table>
    </section>
    """.strip()


def render_html_dashboard(
        plans: List[ReleasePlan],
        csv_path: Path,
        release_country: str,
        language: str,
        script: str,
        edit_note: str,
) -> str:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    total_tracks = sum(len(plan.tracks) for plan in plans)
    body = "\n\n".join(
        render_release_section(plan, release_country, language, script, edit_note)
        for plan in plans
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MusicBrainz Seeding Dashboard</title>
  <style>
    body {{ font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 24px; color: #111827; background: #f8fafc; }}
    h1, h2 {{ margin: 0 0 8px; }}
    .top {{ background: #ffffff; padding: 20px; border: 1px solid #e5e7eb; border-radius: 14px; margin-bottom: 24px; }}
    .note {{ color: #374151; line-height: 1.55; }}
    .release-card {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 14px; padding: 18px; margin-bottom: 22px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
    .release-head {{ display: flex; gap: 16px; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; }}
    .meta {{ display: flex; gap: 12px; flex-wrap: wrap; color: #374151; margin-top: 8px; }}
    .seed-form button {{ border: 0; background: #111827; color: white; padding: 12px 16px; border-radius: 10px; cursor: pointer; font-weight: 600; }}
    .seed-form button:hover {{ opacity: .92; }}
    .lookup-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; margin: 16px 0; }}
    .hit {{ display: block; padding: 10px 12px; border-radius: 10px; border: 1px solid #e5e7eb; background: #f9fafb; }}
    .hit.ok {{ background: #ecfdf5; border-color: #a7f3d0; }}
    .hit.warn {{ background: #fffbeb; border-color: #fde68a; }}
    a {{ color: #1d4ed8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    details {{ margin: 14px 0; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #0f172a; color: #e5e7eb; padding: 14px; border-radius: 10px; overflow: auto; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 14px; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 8px; border-top: 1px solid #e5e7eb; }}
    th {{ background: #f8fafc; }}
    code {{ background: #eef2ff; padding: 2px 6px; border-radius: 6px; }}
  </style>
</head>
<body>
  <div class="top">
    <h1>MusicBrainz Seeding Dashboard</h1>
    <p class="note">
      Generated from <code>{html_escape(str(csv_path))}</code> on {html_escape(generated_at)}.<br>
      Releases: <strong>{len(plans)}</strong> &nbsp; Tracks: <strong>{total_tracks}</strong><br>
      Country seed: <strong>{html_escape(release_country or '(blank)')}</strong> &nbsp; Language seed: <strong>{html_escape(language or '(blank)')}</strong> &nbsp; Script seed: <strong>{html_escape(script or '(blank)')}</strong>
    </p>
    <p class="note">
      Use the <strong>Seed release editor</strong> button for each release first. That will create the release and its track list in the official MusicBrainz editor.
      Works still need manual review/creation and relationship linking after the release/recordings exist.
    </p>
  </div>

  {body}
</body>
</html>
"""


def write_json_sidecar(plans: List[ReleasePlan], output_json: Path) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "releases": [asdict(plan) for plan in plans],
    }
    output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ----------------------------
# CLI
# ----------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a MusicBrainz seeding dashboard from a song CSV.")
    parser.add_argument("csv_path", type=Path, help="Path to the catalog CSV")
    parser.add_argument("--artist", help="Only include rows where Artist matches this value exactly (case-insensitive)")
    parser.add_argument("--out", type=Path, default=Path("musicbrainz_seed_dashboard.html"), help="Output HTML file")
    parser.add_argument("--json-out", type=Path, default=Path("musicbrainz_seed_dashboard.json"), help="Output JSON sidecar")
    parser.add_argument("--user-agent", default=DEFAULT_UA, help="MusicBrainz User-Agent header. Replace the default with your app/email.")
    parser.add_argument("--release-country", default="", help="Release event country ISO code to seed, e.g. XW or US")
    parser.add_argument("--language", default="eng", help="ISO 639-3 language code to seed on releases, e.g. eng")
    parser.add_argument("--script", default="Latn", help="ISO 15924 script code to seed on releases, e.g. Latn")
    parser.add_argument("--status", default="official", help="Release status to seed, e.g. official")
    parser.add_argument("--medium-format", default="Digital Media", help="Medium format to seed")
    parser.add_argument("--multi-track-primary-type", default="", help="Primary release-group type for multi-track releases, e.g. Album or EP")
    parser.add_argument("--lookup-limit", type=int, default=5, help="Max lookup hits per entity search")
    parser.add_argument("--no-lookup", action="store_true", help="Skip MusicBrainz /ws/2 lookups and only generate seed forms/links")
    parser.add_argument(
        "--edit-note",
        default=(
            "Seeded from my internal release catalog CSV. "
            "Please verify label/imprint usage, work relationships, release grouping, and any existing duplicate entities before applying."
        ),
        help="Edit note seeded into release editor forms",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.csv_path.exists():
        print(f"CSV not found: {args.csv_path}", file=sys.stderr)
        return 1

    rows = read_catalog(args.csv_path, artist_filter=args.artist)
    if not rows:
        print("No matching rows found in CSV.", file=sys.stderr)
        return 1

    grouped = group_rows_into_releases(rows)
    mb = MusicBrainzClient(user_agent=args.user_agent, enabled=not args.no_lookup)
    plans = build_release_plans(
        grouped_rows=grouped,
        mb=mb,
        lookup_limit=max(1, min(args.lookup_limit, 25)),
        status=args.status,
        medium_format=args.medium_format,
        multi_track_primary_type=args.multi_track_primary_type,
    )

    html_output = render_html_dashboard(
        plans=plans,
        csv_path=args.csv_path,
        release_country=args.release_country,
        language=args.language,
        script=args.script,
        edit_note=args.edit_note,
    )
    args.out.write_text(html_output, encoding="utf-8")
    write_json_sidecar(plans, args.json_out)

    print(f"Wrote HTML dashboard: {args.out}")
    print(f"Wrote JSON sidecar:   {args.json_out}")
    print(f"Releases: {len(plans)}")
    print(f"Tracks:   {sum(len(p.tracks) for p in plans)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

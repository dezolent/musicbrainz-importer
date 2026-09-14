"""
Dashboard payload assembly and HTML rendering.

The dashboard is a single self-contained HTML file: styles and script are
inlined from the `dashboard/` package assets and the data is embedded as JSON.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import LookupHit, ReleasePlan, TrackPlan
from .seeding import build_release_form_fields, split_artist_credit
from .utils import (
    build_work_queries,
    clean_value,
    html_escape,
    mb_create_artist_url,
    mb_create_label_url,
    mb_create_work_url,
    mb_entity_url,
    mb_search_url,
    slugify,
)

_ASSET_DIR = Path(__file__).parent / "dashboard"


def _hit(hit: Optional[LookupHit]) -> Optional[Dict[str, Any]]:
    return asdict(hit) if hit else None


def _release_key(plan: ReleasePlan) -> str:
    return slugify(plan.catalog_number or plan.upc or f"{plan.release_artist}-{plan.title}-{plan.release_date_iso}")


def _is_collaboration(plan: ReleasePlan) -> bool:
    if len(split_artist_credit(plan.release_artist)) > 1:
        return True
    return any(len(split_artist_credit(t.artist)) > 1 for t in plan.tracks)


def _track_entry(track: TrackPlan) -> Dict[str, Any]:
    work_queries = build_work_queries(track.title, track.writer_composers, track.iswc)
    return {
        "title": track.title,
        "artist": track.artist,
        "duration_raw": track.duration_raw,
        "duration_mmss": track.duration_mmss,
        "duration_ms": track.duration_ms,
        "isrc": track.isrc,
        "iswc": track.iswc,
        "writer_composers": list(track.writer_composers),
        "source_row_number": track.source_row_number,
        "recording": _hit(track.existing_recording),
        "work": _hit(track.existing_work),
        "discrepancies": [asdict(d) for d in track.discrepancies],
        "external_links": [asdict(l) for l in track.external_links],
        "search_urls": {
            "recording": mb_search_url(f'isrc:{track.isrc}' if track.isrc else f'recording:"{track.title}" AND artist:"{track.artist}"', "recording"),
            "work": mb_search_url(work_queries[0], "work"),
        },
        "create_urls": {"work": mb_create_work_url(track.title)},
    }


def _release_entry(plan: ReleasePlan, release_country: str, language: str, script: str, edit_note: str) -> Dict[str, Any]:
    tracks = [_track_entry(t) for t in plan.tracks]
    all_discrepancies = list(plan.discrepancies) + [d for t in plan.tracks for d in t.discrepancies]
    warnings = sum(1 for d in all_discrepancies if d.severity == "warn")
    infos = len(all_discrepancies) - warnings
    hits = [plan.artist_hit, plan.label_hit, plan.release_group_hit, plan.release_hit] + \
           [t.existing_recording for t in plan.tracks] + [t.existing_work for t in plan.tracks]
    recordings_matched = sum(1 for t in plan.tracks if t.existing_recording)
    works_matched = sum(1 for t in plan.tracks if t.existing_work)

    return {
        "key": _release_key(plan),
        "title": plan.title,
        "release_artist": plan.release_artist,
        "release_label": plan.release_label,
        "release_date_raw": plan.release_date_raw,
        "release_date_iso": plan.release_date_iso,
        "year": plan.year,
        "upc": plan.upc,
        "catalog_number": plan.catalog_number,
        "status": plan.status,
        "primary_type": plan.primary_type,
        "medium_format": plan.medium_format,
        "cover_art_url": plan.cover_art_url,
        "site_url": plan.site_url,
        "site_cover_url": plan.site_cover_url,
        "hits": {
            "artist": _hit(plan.artist_hit),
            "label": _hit(plan.label_hit),
            "release_group": _hit(plan.release_group_hit),
            "release": _hit(plan.release_hit),
        },
        "tracks": tracks,
        "discrepancies": [asdict(d) for d in plan.discrepancies],
        "external_links": [asdict(l) for l in plan.external_links],
        "external_status": dict(plan.external_status),
        "seed_fields": [list(pair) for pair in build_release_form_fields(plan, release_country, language, script, edit_note)],
        "search_urls": {
            "artist": mb_search_url(f'artist:"{plan.release_artist}"', "artist"),
            "label": mb_search_url(f'label:"{plan.release_label}"', "label"),
            "release": mb_search_url(f'barcode:{plan.upc}' if plan.upc else f'release:"{plan.title}" AND artist:"{plan.release_artist}"', "release"),
            "release_group": mb_search_url(f'releasegroup:"{plan.title}" AND artist:"{plan.release_artist}"', "release-group"),
        },
        "create_urls": {
            "artist": mb_create_artist_url(plan.release_artist),
            "label": mb_create_label_url(plan.release_label),
        },
        "flags": {
            "unmatched_release": plan.release_hit is None,
            "unmatched_release_group": plan.release_group_hit is None,
            "unmatched_label": plan.label_hit is None and bool(plan.release_label),
            "unmatched_artist": plan.artist_hit is None,
            "unmatched_recording": recordings_matched < len(plan.tracks),
            "unmatched_work": works_matched < len(plan.tracks),
            "missing_isrc": any(not t.isrc for t in plan.tracks),
            "missing_upc": not plan.upc,
            "missing_iswc": any(not t.iswc for t in plan.tracks),
            "warnings": warnings > 0,
            "fuzzy": any(h and h.confidence in ("fuzzy", "search") for h in hits),
            "collaboration": _is_collaboration(plan),
        },
        "counts": {
            "tracks": len(plan.tracks),
            "recordings_matched": recordings_matched,
            "works_matched": works_matched,
            "warnings": warnings,
            "infos": infos,
            "links": len(plan.external_links),
        },
    }


def build_dashboard_payload(
        plans: List[ReleasePlan],
        csv_path: Path,
        artist_name: str,
        artist_mbid: str,
        release_country: str,
        language: str,
        script: str,
        edit_note: str,
        sources_used: Optional[List[str]] = None,
        lookups_enabled: bool = True,
) -> Dict[str, Any]:
    releases = [_release_entry(p, release_country, language, script, edit_note) for p in plans]
    tracks = [t for r in releases for t in r["tracks"]]
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_csv": str(csv_path),
        "artist": {
            "name": artist_name,
            "mbid": artist_mbid,
            "url": mb_entity_url("artist", artist_mbid) if artist_mbid else "",
        },
        "params": {
            "release_country": release_country,
            "language": language,
            "script": script,
            "edit_note": edit_note,
            "lookups_enabled": lookups_enabled,
            "sources_used": list(sources_used or []),
        },
        "summary": {
            "releases": len(releases),
            "releases_matched": sum(1 for r in releases if r["hits"]["release"]),
            "tracks": len(tracks),
            "recordings_matched": sum(1 for t in tracks if t["recording"]),
            "works_matched": sum(1 for t in tracks if t["work"]),
            "warnings": sum(r["counts"]["warnings"] for r in releases),
            "infos": sum(r["counts"]["infos"] for r in releases),
            "missing_identifiers": sum(1 for r in releases if r["flags"]["missing_isrc"] or r["flags"]["missing_upc"] or r["flags"]["missing_iswc"]),
            "fuzzy": sum(1 for r in releases if r["flags"]["fuzzy"]),
        },
        "releases": releases,
    }


def _read_asset(name: str) -> str:
    return (_ASSET_DIR / name).read_text(encoding="utf-8")


def render_html_dashboard(payload: Dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    artist = clean_value(payload.get("artist", {}).get("name"))
    title = f"{artist} · MusicBrainz Seeding Dashboard" if artist else "MusicBrainz Seeding Dashboard"
    html = _read_asset("template.html")
    for slot, value in {
        "TITLE": html_escape(title),
        "STYLES": _read_asset("styles.css"),
        "SCRIPT": _read_asset("app.js"),
        "DATA": data_json,
    }.items():
        html = html.replace("{{" + slot + "}}", value)
    return html


def write_json_sidecar(payload: Dict[str, Any], output_path: Path) -> None:
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

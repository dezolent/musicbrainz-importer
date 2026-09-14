"""
Compare CSV-derived plans with matched MusicBrainz entities, and validate the CSV itself.
"""

from __future__ import annotations

import re
from typing import List, Optional

from .models import Discrepancy, LookupHit, ReleasePlan, TrackPlan
from .utils import clean_value, normalize_text, normalize_upc

LENGTH_TOLERANCE_MS = 2000


def _mmss(ms: Optional[int]) -> str:
    if ms is None:
        return ""
    total = int(round(ms / 1000))
    return f"{total // 60}:{total % 60:02d}"


def _barcode_key(value: str) -> str:
    return normalize_upc(value).lstrip("0")


def compare_release(plan: ReleasePlan, hit: LookupHit) -> List[Discrepancy]:
    out: List[Discrepancy] = []
    extra = hit.extra or {}

    mb_date = clean_value(extra.get("date"))
    if plan.release_date_iso and mb_date and plan.release_date_iso != mb_date:
        out.append(Discrepancy("release_date", plan.release_date_iso, mb_date, "warn", "Release date differs"))

    mb_barcode = clean_value(extra.get("barcode"))
    if plan.upc and mb_barcode and _barcode_key(plan.upc) != _barcode_key(mb_barcode):
        out.append(Discrepancy("barcode", plan.upc, mb_barcode, "warn", "Barcode differs"))
    elif plan.upc and not mb_barcode:
        out.append(Discrepancy("barcode", plan.upc, "", "info", "MusicBrainz release has no barcode"))

    labels = extra.get("labels") or []
    mb_label_names = [clean_value(l[0]) for l in labels if l and clean_value(l[0])]
    mb_catnos = [clean_value(l[2]) for l in labels if l and len(l) > 2 and clean_value(l[2])]
    if plan.release_label and mb_label_names and normalize_text(plan.release_label) not in {normalize_text(n) for n in mb_label_names}:
        out.append(Discrepancy("label", plan.release_label, ", ".join(mb_label_names), "warn", "Label differs"))
    if plan.catalog_number:
        if not mb_catnos:
            out.append(Discrepancy("catalog_number", plan.catalog_number, "", "info", "MusicBrainz release has no catalog number"))
        elif normalize_text(plan.catalog_number) not in {normalize_text(c) for c in mb_catnos}:
            out.append(Discrepancy("catalog_number", plan.catalog_number, ", ".join(mb_catnos), "warn", "Catalog number differs"))

    mb_track_count = extra.get("track_count")
    if isinstance(mb_track_count, int) and mb_track_count and mb_track_count != len(plan.tracks):
        out.append(Discrepancy("track_count", str(len(plan.tracks)), str(mb_track_count), "warn", "Track count differs"))

    mb_type = clean_value(extra.get("release_group_type"))
    if plan.primary_type and mb_type and normalize_text(plan.primary_type) != normalize_text(mb_type):
        out.append(Discrepancy("primary_type", plan.primary_type, mb_type, "warn", "Release group type differs"))

    if clean_value(plan.title) != clean_value(hit.name):
        out.append(Discrepancy("title", plan.title, hit.name, "info", "Release title spelled differently"))

    if extra.get("duplicate_mbids"):
        out.append(Discrepancy("duplicates", hit.mbid, ", ".join(extra["duplicate_mbids"]), "warn", "Multiple MusicBrainz releases share this identifier"))
    return out


def compare_track(track: TrackPlan, hit: LookupHit) -> List[Discrepancy]:
    out: List[Discrepancy] = []
    extra = hit.extra or {}

    mb_length = extra.get("length_ms")
    if track.duration_ms and isinstance(mb_length, int) and abs(mb_length - track.duration_ms) > LENGTH_TOLERANCE_MS:
        out.append(Discrepancy("length", _mmss(track.duration_ms), _mmss(mb_length), "warn", "Recording length differs"))

    if clean_value(track.title) != clean_value(hit.name):
        out.append(Discrepancy("title", track.title, hit.name, "info", "Recording title spelled differently"))

    mb_isrcs = [clean_value(i).upper() for i in (extra.get("isrcs") or []) if clean_value(i)]
    if track.isrc and "isrcs" in extra:
        if not mb_isrcs:
            out.append(Discrepancy("isrc", track.isrc, "", "info", "MusicBrainz recording has no ISRC yet"))
        elif track.isrc.upper() not in mb_isrcs:
            out.append(Discrepancy("isrc", track.isrc, ", ".join(mb_isrcs), "warn", "MusicBrainz recording carries a different ISRC"))

    if extra.get("duplicate_mbids"):
        out.append(Discrepancy("duplicates", hit.mbid, ", ".join(extra["duplicate_mbids"]), "warn", "Multiple MusicBrainz entities share this identifier"))
    return out


def compare_work(track: TrackPlan, hit: LookupHit) -> List[Discrepancy]:
    out: List[Discrepancy] = []
    extra = hit.extra or {}
    if clean_value(track.title) != clean_value(hit.name):
        out.append(Discrepancy("work_title", track.title, hit.name, "info", "Work title spelled differently"))
    if extra.get("duplicate_mbids"):
        out.append(Discrepancy("work_duplicates", hit.mbid, ", ".join(extra["duplicate_mbids"]), "warn", "Multiple MusicBrainz works share this ISWC (merge candidates)"))
    if track.iswc and not extra.get("iswcs"):
        out.append(Discrepancy("work_iswc", track.iswc, "", "info", "MusicBrainz work has no ISWC"))
    return out


def validate_release(plan: ReleasePlan) -> List[Discrepancy]:
    """CSV self-consistency: missing identifiers, bad dates, year mismatch. Source is always "csv"."""
    out: List[Discrepancy] = []

    def csv_issue(field: str, csv_value: str, other: str, severity: str, message: str) -> None:
        out.append(Discrepancy(field, csv_value, other, severity, message, source="csv"))

    if not plan.upc:
        csv_issue("upc", "", "", "warn", "Missing UPC")
    if plan.release_date_raw and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", plan.release_date_iso or ""):
        csv_issue("release_date", plan.release_date_raw, "", "warn", "Release date could not be parsed (spreadsheet serial?)")
    if plan.year and plan.release_date_iso[:4].isdigit() and plan.year != plan.release_date_iso[:4]:
        csv_issue("year", plan.year, plan.release_date_iso[:4], "info",
                  f"Year column ({plan.year}) differs from the Release Date year ({plan.release_date_iso[:4]}); fine if Year is the ℗ year")
    for track in plan.tracks:
        if not track.isrc:
            csv_issue("isrc", "", "", "warn", f"Missing ISRC: {track.title}")
        if not track.iswc:
            csv_issue("iswc", "", "", "info", f"Missing ISWC: {track.title}")
        if track.duration_raw and track.duration_ms is None:
            csv_issue("duration", track.duration_raw, "", "warn", f"Duration could not be parsed: {track.title}")
    return out

"""
Release editor seeding: turn a ReleasePlan into the hidden form fields MusicBrainz expects.
See https://musicbrainz.org/doc/Development/Release_Editor_Seeding
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .models import ReleasePlan
from .utils import clean_value, normalize_text, parse_release_date

SEEDABLE_CONFIDENCE = {"exact", "strong"}

_CREDIT_SPLIT_RE = re.compile(
    r"\s*(?:,\s*&\s*|,\s*and\s+|\s+&\s+|\s+and\s+|,\s*|\s+(?:feat\.?|ft\.?|featuring)\s+)\s*",
    re.IGNORECASE,
)


def split_artist_credit(text: str) -> List[Tuple[str, str]]:
    """Split "A & B feat. C" into [("A", " & "), ("B", " feat. "), ("C", "")]."""
    text = clean_value(text)
    if not text:
        return []
    parts: List[Tuple[str, str]] = []
    pos = 0
    for match in _CREDIT_SPLIT_RE.finditer(text):
        name = text[pos:match.start()].strip()
        if not name:
            continue
        sep = match.group(0)
        if re.search(r"feat|ft|featuring", sep, re.IGNORECASE):
            join = " feat. "
        elif "&" in sep or re.search(r"\band\b", sep, re.IGNORECASE):
            join = " & "
        else:
            join = ", "
        parts.append((name, join))
        pos = match.end()
    tail = text[pos:].strip()
    if tail:
        parts.append((tail, ""))
    elif parts:
        parts[-1] = (parts[-1][0], "")
    return parts


def artist_credit_fields(prefix: str, credit_text: str, known: Optional[Dict[str, str]] = None) -> List[Tuple[str, str]]:
    """Seeding fields for an artist credit; known maps normalized names to MBIDs."""
    known = known or {}
    fields: List[Tuple[str, str]] = []
    for idx, (name, join) in enumerate(split_artist_credit(credit_text)):
        mbid = known.get(normalize_text(name))
        if mbid:
            fields.append((f"{prefix}.{idx}.mbid", mbid))
        else:
            fields.append((f"{prefix}.{idx}.artist.name", name))
        fields.append((f"{prefix}.{idx}.name", name))
        if join:
            fields.append((f"{prefix}.{idx}.join_phrase", join))
    return fields


def build_release_form_fields(
        plan: ReleasePlan,
        release_country: str,
        language: str,
        script: str,
        edit_note: str,
) -> List[Tuple[str, str]]:
    _, date_parts = parse_release_date(plan.release_date_raw)

    fields: List[Tuple[str, str]] = [
        ("name", plan.title),
        ("status", plan.status),
        ("edit_note", edit_note.strip()),
    ]

    if plan.release_group_hit and plan.release_group_hit.confidence in SEEDABLE_CONFIDENCE:
        fields.append(("release_group", plan.release_group_hit.mbid))
    elif plan.primary_type:
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

    known = dict(plan.credited_artists)
    if plan.artist_hit:
        known.setdefault(normalize_text(plan.artist_hit.name), plan.artist_hit.mbid)
        if len(split_artist_credit(plan.release_artist)) == 1:
            known[normalize_text(plan.release_artist)] = plan.artist_hit.mbid
    fields.extend(artist_credit_fields("artist_credit.names", plan.release_artist, known))

    fields.append(("mediums.0.format", plan.medium_format))
    for idx, track in enumerate(plan.tracks):
        prefix = f"mediums.0.track.{idx}"
        fields.append((f"{prefix}.number", str(idx + 1)))
        fields.append((f"{prefix}.name", track.title))
        if track.duration_mmss:
            fields.append((f"{prefix}.length", track.duration_mmss))
        if track.existing_recording and track.existing_recording.confidence in SEEDABLE_CONFIDENCE:
            fields.append((f"{prefix}.recording", track.existing_recording.mbid))
        if normalize_text(track.artist) != normalize_text(plan.release_artist):
            fields.extend(artist_credit_fields(f"{prefix}.artist_credit.names", track.artist, known))

    for idx, link in enumerate(plan.external_links):
        fields.append((f"urls.{idx}.url", link.url))
        if link.link_type_id is not None:
            fields.append((f"urls.{idx}.link_type", str(link.link_type_id)))

    cleaned: List[Tuple[str, str]] = []
    for name, value in fields:
        # Join phrases are significant whitespace (" & ", " feat. ") and must not be trimmed.
        text = value if name.endswith(".join_phrase") else clean_value(value)
        if clean_value(text):
            cleaned.append((name, text))
    return cleaned

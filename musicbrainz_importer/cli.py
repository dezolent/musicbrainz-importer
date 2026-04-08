"""
Command-line interface: argument parsing and main entry point.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import build_release_plans, group_rows_into_releases, read_catalog, update_csv_with_mb_urls
from .client import MusicBrainzClient
from .constants import DEFAULT_UA
from .renderer import render_html_dashboard, write_json_sidecar


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a MusicBrainz seeding dashboard from a song catalog CSV."
    )
    parser.add_argument("csv_path", type=Path, help="Path to the catalog CSV")
    parser.add_argument(
        "--artist",
        help="Only include rows where Artist matches this value (case-insensitive)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("dashboard.html"),
        help="Output HTML file",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("dashboard.json"),
        help="Output JSON sidecar",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_UA,
        help="MusicBrainz User-Agent header. Replace the default with your app/email.",
    )
    parser.add_argument(
        "--release-country",
        default="",
        help="Release event country ISO code to seed, e.g. XW or US",
    )
    parser.add_argument(
        "--language",
        default="eng",
        help="ISO 639-3 language code to seed on releases, e.g. eng",
    )
    parser.add_argument(
        "--script",
        default="Latn",
        help="ISO 15924 script code to seed on releases, e.g. Latn",
    )
    parser.add_argument(
        "--status",
        default="official",
        help="Release status to seed, e.g. official",
    )
    parser.add_argument(
        "--medium-format",
        default="Digital Media",
        help="Medium format to seed",
    )
    parser.add_argument(
        "--multi-track-primary-type",
        default="",
        help="Primary release-group type for multi-track releases, e.g. Album or EP",
    )
    parser.add_argument(
        "--lookup-limit",
        type=int,
        default=5,
        help="Max lookup hits per entity search",
    )
    parser.add_argument(
        "--no-lookup",
        action="store_true",
        help="Skip MusicBrainz /ws/2 lookups and only generate seed forms/links",
    )
    parser.add_argument(
        "--edit-note",
        default=(
            "Seeded from my internal release catalog CSV. "
            "Please verify label/imprint usage, work relationships, release grouping, "
            "and any existing duplicate entities before applying."
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

    csv_rows_updated = update_csv_with_mb_urls(args.csv_path, plans)

    print(f"Wrote HTML dashboard: {args.out}")
    print(f"Wrote JSON sidecar:   {args.json_out}")
    print(f"Releases: {len(plans)}")
    print(f"Tracks:   {sum(len(p.tracks) for p in plans)}")
    if csv_rows_updated:
        print(f"CSV rows updated with MusicBrainz URLs: {csv_rows_updated} ({args.csv_path})")
    return 0

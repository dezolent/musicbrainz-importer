"""
Command-line interface: argument parsing and main entry point.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

from .catalog import group_rows_into_releases, read_catalog, update_csv_with_mb_urls
from .client import MusicBrainzClient
from .constants import DEFAULT_UA
from .enrichment import enrich_plans
from .external.discogs import DiscogsClient
from .external.itunes import ITunesClient
from .external.spotify import SpotifyClient
from .external.website import WebsiteClient
from .pipeline import build_release_plans
from .renderer import build_dashboard_payload, render_html_dashboard, write_json_sidecar
from .snapshot import fetch_artist_catalog, resolve_artist_mbid
from .utils import clean_value


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a MusicBrainz seeding dashboard from a song catalog CSV.",
    )
    parser.add_argument("csv_path", type=Path, help="Path to the catalog CSV")
    parser.add_argument("--artist", help="Only include rows where Artist contains this value (case-insensitive)")
    parser.add_argument("--artist-mbid", default=os.environ.get("MUSICBRAINZ_ARTIST_MBID", ""),
                        help="MusicBrainz artist MBID to snapshot. Resolved from --artist when omitted.")
    parser.add_argument("--out", type=Path, default=Path("dashboard.html"), help="Output HTML dashboard")
    parser.add_argument("--json-out", type=Path, default=Path("dashboard.json"), help="Output JSON sidecar")
    parser.add_argument("--user-agent", default=DEFAULT_UA, help="MusicBrainz User-Agent header (AppName/Version (contact))")
    parser.add_argument("--release-country", default="", help="Release event country ISO code to seed, e.g. XW or US")
    parser.add_argument("--language", default="eng", help="ISO 639-3 language code to seed on releases")
    parser.add_argument("--script", default="Latn", help="ISO 15924 script code to seed on releases")
    parser.add_argument("--status", default="official", help="Release status to seed")
    parser.add_argument("--medium-format", default="Digital Media", help="Medium format to seed")
    parser.add_argument("--multi-track-primary-type", default="", help="Release-group type for multi-track releases, e.g. Album or EP")
    parser.add_argument("--lookup-limit", type=int, default=5, help="Max hits per ws/2 search (fallback only)")
    parser.add_argument("--no-lookup", action="store_true", help="Skip every network call; generate seed forms and links only")
    parser.add_argument("--search-fallback", action="store_true",
                        help="Also run ws/2 searches for items the artist snapshot did not contain (slower; off by default)")
    parser.add_argument("--no-external", action="store_true", help="Skip Spotify, Apple Music, Discogs and website enrichment")
    parser.add_argument("--website", default=os.environ.get("ARTIST_WEBSITE", ""),
                        help="Artist website with schema.org MusicRecording data, e.g. https://dezolent.com (env ARTIST_WEBSITE)")
    parser.add_argument("--no-website", action="store_true", help="Skip the artist website even when --website is set")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache"), help="Directory for cached website pages")
    parser.add_argument("--no-csv-writeback", action="store_true", help="Do not write MusicBrainz URLs back into the CSV")
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Path to a .env file with API credentials")
    parser.add_argument(
        "--edit-note",
        default=(
            "Seeded from my internal release catalog CSV. "
            "Please verify label/imprint usage, work relationships, release grouping, "
            "and any existing duplicate entities before applying."
        ),
        help="Edit note pre-filled into the release editor",
    )
    return parser.parse_args(argv)


def _build_external_clients(args: argparse.Namespace):
    if args.no_lookup or args.no_external:
        return None, None, None, None
    spotify = SpotifyClient(os.environ.get("SPOTIFY_CLIENT_ID", ""), os.environ.get("SPOTIFY_CLIENT_SECRET", ""))
    itunes = ITunesClient()
    discogs = DiscogsClient(os.environ.get("DISCOGS_PAT") or os.environ.get("DISCOGS_TOKEN", ""), user_agent=args.user_agent)
    website = None
    if args.website and not args.no_website:
        website = WebsiteClient(args.website, user_agent=args.user_agent, cache_dir=args.cache_dir / "website")
    if not spotify.enabled:
        print("Spotify credentials not found in environment; skipping Spotify.", file=sys.stderr)
    if not discogs.enabled:
        print("Discogs token not found in environment; skipping Discogs.", file=sys.stderr)
    return spotify, itunes, discogs, website


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.env.exists():
        load_dotenv(args.env)
        # Re-read defaults that may come from the env file.
        args.artist_mbid = args.artist_mbid or os.environ.get("MUSICBRAINZ_ARTIST_MBID", "")
        args.website = args.website or os.environ.get("ARTIST_WEBSITE", "")

    if not args.csv_path.exists():
        print(f"CSV not found: {args.csv_path}", file=sys.stderr)
        return 1

    rows = read_catalog(args.csv_path, artist_filter=args.artist)
    if not rows:
        print("No matching rows found in CSV.", file=sys.stderr)
        return 1
    grouped = group_rows_into_releases(rows)

    mb = MusicBrainzClient(user_agent=args.user_agent, enabled=not args.no_lookup)

    catalog = None
    artist_name = clean_value(args.artist) or clean_value(rows[0].get("Release Artist") or rows[0].get("Artist"))
    artist_mbid = clean_value(args.artist_mbid)
    if not args.no_lookup:
        if not artist_mbid:
            artist_mbid = resolve_artist_mbid(mb, artist_name) or ""
            if artist_mbid:
                print(f"Resolved artist '{artist_name}' to {artist_mbid}", file=sys.stderr)
            else:
                print(f"Could not resolve an exact MusicBrainz artist for '{artist_name}'; using search fallback only.", file=sys.stderr)
        if artist_mbid:
            catalog = fetch_artist_catalog(mb, artist_mbid, artist_name=args.artist or "")
            artist_name = catalog.artist_name or artist_name

    plans = build_release_plans(
        grouped_rows=grouped,
        mb=mb,
        catalog=catalog,
        lookup_limit=max(1, min(args.lookup_limit, 25)),
        status=args.status,
        medium_format=args.medium_format,
        multi_track_primary_type=args.multi_track_primary_type,
        artist_filter=args.artist,
        search_fallback=args.search_fallback,
    )

    spotify, itunes, discogs, website = _build_external_clients(args)
    enrich_plans(plans, spotify, itunes, discogs, website)
    sources_used = [name for name, client in (("website", website), ("spotify", spotify), ("itunes", itunes), ("discogs", discogs))
                    if client is not None and client.enabled]

    payload = build_dashboard_payload(
        plans,
        csv_path=args.csv_path,
        artist_name=artist_name,
        artist_mbid=artist_mbid,
        release_country=args.release_country,
        language=args.language,
        script=args.script,
        edit_note=args.edit_note,
        sources_used=sources_used,
        lookups_enabled=not args.no_lookup,
    )
    args.out.write_text(render_html_dashboard(payload), encoding="utf-8")
    write_json_sidecar(payload, args.json_out)

    csv_rows_updated = 0 if args.no_csv_writeback else update_csv_with_mb_urls(args.csv_path, plans)

    summary = payload["summary"]
    print("", file=sys.stderr)
    print(f"Wrote HTML dashboard: {args.out}")
    print(f"Wrote JSON sidecar:   {args.json_out}")
    print(f"Releases:   {summary['releases_matched']}/{summary['releases']} matched")
    print(f"Recordings: {summary['recordings_matched']}/{summary['tracks']} matched")
    print(f"Works:      {summary['works_matched']}/{summary['tracks']} matched")
    print(f"Review:     {summary['warnings']} warnings, {summary['infos']} notes")
    requests_made = [f"MusicBrainz {mb.request_count}"] + [
        f"{name} {client.request_count}" for name, client in (("Spotify", spotify), ("iTunes", itunes), ("Discogs", discogs))
        if client is not None and client.enabled
    ]
    if website is not None and website.enabled:
        requests_made.append(f"website {website.request_count} (+{website.cache_hits} cached)")
    print(f"Requests:   {', '.join(requests_made)}")
    if csv_rows_updated:
        print(f"CSV rows updated with MusicBrainz URLs: {csv_rows_updated} ({args.csv_path})")
    return 0

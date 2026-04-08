#!/usr/bin/env python3
"""
Entry point for the MusicBrainz seeding tool.

Usage:
    python main.py songs.csv --artist Dezolent --release-country XW
    python main.py songs.csv --artist Dezolent --release-country XW --out musicbrainz_seed.html
    python main.py songs.csv --no-lookup --multi-track-primary-type Album
"""

from musicbrainz_importer.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

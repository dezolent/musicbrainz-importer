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
    python mb_seed_from_csv.py "songs.csv" --artist "Dezolent" --user-agent "dezolent-musicbrainz-importer/0.1 (dezolent@gmail.com)" --release-country XW --multi-track-primary-type Album
    python mb_seed_from_csv.py "songs.csv" --artist Dezolent --release-country XW --out musicbrainz_seed.html

Notes:
- MusicBrainz asks clients not to exceed 1 request per second to /ws/2.
- Release seeding is supported through POSTing form fields to /release/add.
- Non-release forms such as Add Work / Add Label can be seeded through query parameters.

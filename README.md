# MusicBrainz Importer

Generate a one-click seeding dashboard for [MusicBrainz](https://musicbrainz.org) from a song catalog CSV. The tool snapshots an artist's existing MusicBrainz catalog, matches every CSV row against it by identifier, compares the two, enriches releases with Spotify, Apple Music and Discogs links, and produces a single self-contained HTML dashboard with pre-filled release editor forms. Release URLs it finds are written back to the CSV.

---

## What it does

1. **Reads** the catalog CSV and groups rows into releases by artist, title, UPC, catalog number, label and date.
2. **Snapshots** the artist's MusicBrainz catalog with three browse requests (releases, recordings, works) keyed by artist MBID. This replaces dozens of fragile per-row searches.
3. **Matches** locally and deterministically:
   - release by **UPC**, recording by **ISRC**, work by **ISWC** → `exact`
   - otherwise normalized title (strips `feat.` clauses; `Gone - Coptr Remix` equals `Gone (Coptr Remix)`) → `strong`
   - otherwise title similarity above 85% → `fuzzy` (shown, never seeded)
4. **Compares** CSV values with MusicBrainz and flags discrepancies: release date, barcode, label, catalog number, track count, release-group type, track length beyond two seconds, spelling differences, duplicate entities sharing one identifier, and CSV self-consistency (missing UPC/ISRC/ISWC, `Year` disagreeing with the release date, unparseable values).
5. **Enriches** each release from the artist's own website (schema.org JSON-LD on every track page: ISRC, ISWC, duration, date, cover art, lyrics, and canonical Spotify/Apple Music/YouTube/SoundCloud/Tidal/Deezer/Beatport/Bandcamp/Amazon links), Spotify (album by UPC; tracks by the website's Spotify ID, or by ISRC with artist validation), the iTunes Search API (album and tracklist by UPC) and Discogs (artist's releases matched by barcode, catalog number or ISRC). Release URLs are seeded as URL relationships with the correct link types (website page → "discography entry"), and every source's dates, lengths, ISRCs and ISWCs are cross-checked against the CSV.
6. **Renders** `dashboard.html`: KPI strip, a chronological coverage matrix, filterable and collapsible release cards, and a `Seed release editor` button per release. Matched recordings are seeded by MBID so seeding never creates duplicate recordings; matched release groups and labels are seeded by MBID; multi-artist credits are split into proper artist credits with join phrases.
7. **Writes** `dashboard.json` (the full payload) and updates the CSV's `MusicBrainz` column for matched releases.

## What it does NOT do

- It never creates or edits MusicBrainz data directly. Seeding only pre-fills the editor; you review and save.
- It does not submit ISRCs or create work relationships (both need an authenticated MusicBrainz edit).

---

## Installation

```bash
git clone https://github.com/youruser/musicbrainz-importer.git
cd musicbrainz-importer
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Requirements:** Python 3.11+, `requests`, `python-dotenv`. `pytest` for the test suite.

### Credentials and defaults (optional)

Copy the keys below into a `.env` file in the repo root. Missing keys simply disable that source. `.env` is git-ignored.

```
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
DISCOGS_PAT=...                      # personal access token
MUSICBRAINZ_ARTIST_MBID=...          # default for --artist-mbid
ARTIST_WEBSITE=https://example.com   # default for --website
```

The iTunes Search API, the Cover Art Archive and the artist website need no credentials.

### Artist website as a source

If the artist's site publishes schema.org structured data (`MusicRecording` with `isrcCode`, `duration`, `sameAs` links; `MusicComposition` with `iswcCode`; `MusicAlbum` with `image`), pass it with `--website`. The tool reads `/tracks` (an `ItemList`) or the sitemap, then every track and album page, caching pages under `.cache/website/` for seven days. The site is treated as the authoritative source for streaming links: Spotify tracks are fetched by the site's Spotify ID instead of searched by ISRC, which avoids Spotify's ISRC collisions.

---

## Usage

```bash
python main.py songs.csv --artist "Dezolent" \
  --artist-mbid a4cc3b9d-6798-46d8-ac69-feb1ac9f8a0b \
  --release-country XW \
  --multi-track-primary-type EP
```

Then open `dashboard.html` in a browser.

### All options

| Flag | Default | Description |
|---|---|---|
| `csv_path` | *(required)* | Path to the catalog CSV |
| `--artist` | *(all rows)* | Only rows whose `Artist` contains this value (case-insensitive). Also names the artist to snapshot. |
| `--artist-mbid` | `$MUSICBRAINZ_ARTIST_MBID` | MusicBrainz artist MBID to snapshot. Resolved from `--artist` by exact-name search when omitted. |
| `--out` | `dashboard.html` | Output dashboard |
| `--json-out` | `dashboard.json` | Output JSON payload |
| `--user-agent` | built-in | MusicBrainz `User-Agent` — **replace with your app name and contact email** |
| `--release-country` | *(blank)* | ISO country code for the release event, e.g. `XW` or `US` |
| `--language` | `eng` | ISO 639-3 language code |
| `--script` | `Latn` | ISO 15924 script code |
| `--status` | `official` | Release status |
| `--medium-format` | `Digital Media` | Medium format |
| `--multi-track-primary-type` | *(blank)* | Release-group type for multi-track releases (`Album`, `EP`). Single-track releases are always `Single`. |
| `--search-fallback` | off | Also run `/ws/2` searches for items the snapshot did not contain. Off by default because the snapshot is authoritative and search results that merely look similar caused wrong matches. |
| `--lookup-limit` | `5` | Max hits per fallback search (capped at 25) |
| `--no-lookup` | off | No network at all. Seed forms and links only. |
| `--no-external` | off | Skip Spotify, Apple Music, Discogs and the website |
| `--website` | `$ARTIST_WEBSITE` | Artist website with schema.org music data |
| `--no-website` | off | Skip the website even when configured |
| `--cache-dir` | `.cache` | Where website pages are cached |
| `--no-csv-writeback` | off | Do not touch the CSV |
| `--env` | `.env` | Credentials file |
| `--edit-note` | built-in | Edit note pre-filled into the release editor |

### Examples

```bash
# Full run: snapshot, match, enrich, dashboard, CSV write-back
python main.py songs.csv --artist Dezolent --release-country XW --multi-track-primary-type EP

# Offline preview of seed forms (no HTTP requests)
python main.py songs.csv --no-lookup

# MusicBrainz only, leave the CSV alone
python main.py songs.csv --artist Dezolent --no-external --no-csv-writeback
```

---

## The dashboard

- **KPI strip** — releases, recordings and works found in MusicBrainz; warnings to review; low-confidence matches; releases you marked done.
- **Coverage matrix** — one row per release in chronological order, one column per thing that must exist (artist, label, release group, release, recordings, works, links, review). Select a cell or title to jump to that release.
- **Toolbar** — full-text search across titles, artists, ISRCs, UPCs and catalog numbers; filter chips (no release, recordings missing, works missing, needs review, low confidence, no UPC/ISRC/ISWC, collaborations, open, done); sort; expand or collapse all.
- **Release cards** — collapsible. Each shows the matched MusicBrainz entities with confidence badges and open/search/create links, the review list (CSV value versus source value, labelled by source), the track table with per-track Website, Lyrics, Spotify, Apple Music and other provider links, external links, and actions: `Seed release editor` (or `Seed anyway` when the release already exists), `Open on MusicBrainz`, `Edit release`, `Cover art` or `Add cover art` when MusicBrainz has none but the website does, `Website`, and the raw seeding fields. Cover thumbnails come from the Cover Art Archive, falling back to the website image.
- **Done** — a per-release checkbox stored in your browser's local storage so progress survives regenerating the dashboard.

Match confidence: `exact` = identifier match (UPC, ISRC, ISWC, or derived from a matched release); `strong` = normalized title match; `fuzzy`/`search` = similar title or search result, shown for review but never seeded.

---

## CSV format

The importer expects at least these columns (extra columns are preserved):

| Column | Used for |
|---|---|
| `Artist` | Track artist; fallback release artist. Collaborations like `Dezolent & Tomentam feat. fendi mars` are split into proper artist credits. |
| `Title` | Track title |
| `Release Artist` | Release-level artist (overrides `Artist` for grouping) |
| `Release` | Release title |
| `Release Label` | Label name |
| `Release Date` | `MM/DD/YY`, `MM/DD/YYYY`, `YYYY-MM-DD`, or a spreadsheet serial number such as `41695` |
| `Year` | Cross-checked against `Release Date` |
| `UPC` | Barcode — exact release match; a leading backtick or missing leading zero is tolerated |
| `Catalog Number` | Release match fallback; seeded into label info |
| `ISRC` | Exact recording match; Spotify lookup |
| `ISWC` | Exact work match (`T3294665304` and `T-329.466.530-4` both work) |
| `Duration` | `M:SS`, `H:MM:SS`, or a spreadsheet fraction-of-day such as `0.1625` (= 3:54) |
| `Writer/Composer 1–3` | Shown per track; used to rank work matches |
| `Discogs`, `Amazon ASIN` | Seeded as URL relationships (Discogs → link type 76, Amazon → 77) |
| `MusicBrainz` | **Written back automatically** with the release URL when a match is found; existing values are never overwritten |

---

## Project structure

```
musicbrainz-importer/
├── main.py                            # Entry point
├── requirements.txt
├── tests/                             # pytest suite (run: python -m pytest)
└── musicbrainz_importer/
    ├── cli.py                         # Argument parsing + main()
    ├── constants.py                   # URLs, rate limit, link-type ids
    ├── models.py                      # Dataclasses: catalog snapshot, plans, hits, discrepancies
    ├── utils.py                       # Cleaning, parsing (incl. spreadsheet quirks), MB URL builders
    ├── client.py                      # MusicBrainzClient: search/browse/lookup, throttle, retry on 429/503
    ├── snapshot.py                    # Browse an artist's releases/recordings/works into an ArtistCatalog
    ├── matching.py                    # Pure identifier/title/fuzzy matching against the snapshot
    ├── discrepancies.py               # CSV vs MusicBrainz comparison and CSV validation
    ├── pipeline.py                    # Orchestrates matching per release, with guarded search fallback
    ├── enrichment.py                  # Applies Spotify / Apple Music / Discogs results to plans
    ├── external/                      # Spotify, iTunes, Discogs, website (JSON-LD) clients and pure parsers
    ├── seeding.py                     # Release editor seeding fields, artist-credit splitting
    ├── catalog.py                     # CSV read, grouping, write-back
    ├── renderer.py                    # Dashboard payload + HTML assembly
    └── dashboard/                     # template.html, styles.css, app.js (inlined at build time)
```

Run the tests:

```bash
python -m pytest
```

---

## API notes

- **MusicBrainz** — 1 request per second (`RATE_LIMIT_SECONDS = 1.1`). HTTP 429/503 and timeouts are retried with 5 → 15 → 30 second back-off, honoring `Retry-After`. If the server keeps failing, the run stops searching rather than retrying forever. A full run for a 20-release catalog needs roughly 5 to 10 MusicBrainz requests. Set a descriptive `User-Agent` per the [API etiquette](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting).
- **Release editor seeding** follows the official [seeding protocol](https://musicbrainz.org/doc/Development/Release_Editor_Seeding). Nothing is submitted automatically.
- **Spotify** uses the client-credentials flow; no user login and no redirect happens. Spotify's ISRC index contains collisions (one ISRC can resolve to another artist's track), so search results are only accepted when credited to one of the CSV's artists, and the website's Spotify ID is preferred when available. A Spotify track whose ISRC differs from the CSV is flagged, which catches typos in the CSV.
- **Discogs** allows 60 requests per minute with a token; the tool lists the artist's releases once and matches locally.
- **iTunes Search API** and **Cover Art Archive** are public.

# MusicBrainz Importer

Generate a one-click seeding dashboard for [MusicBrainz](https://musicbrainz.org) from a song catalog CSV. Looks up existing entities via the MusicBrainz Web Service, produces an HTML dashboard with pre-filled release editor forms, and writes discovered release URLs back to your CSV.

---

## What it does

- **Reads** a catalog CSV and groups rows into releases by artist, title, UPC, catalog number, label, and date
- **Looks up** existing MusicBrainz entities (artists, labels, releases, release groups, recordings, works) via `/ws/2`
- **Generates** an HTML dashboard with:
  - One-click **Seed release editor** buttons (official MusicBrainz POST seeding flow)
  - Search and create links for every entity type
  - Per-track recording and work lookup badges
- **Writes** a JSON sidecar with the full normalized plan and all lookup results
- **Updates** your source CSV with MusicBrainz release URLs for any releases it found (fills in the `MusicBrainz` column, skipping rows that already have a value)

## What it does NOT do

- It does not create or edit any MusicBrainz data directly — it only seeds the editor forms
- It does not submit ISRC or barcode XML edits
- It does not create work relationships automatically

---

## Installation

```bash
git clone https://github.com/youruser/musicbrainz-importer.git
cd musicbrainz-importer
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Requirements:** Python 3.11+, `requests`

---

## Usage

```bash
python main.py songs.csv --artist "Dezolent" \
  --user-agent "my-importer/1.0 (you@example.com)" \
  --release-country XW \
  --multi-track-primary-type Album
```

### All options

| Flag | Default | Description |
|---|---|---|
| `csv_path` | *(required)* | Path to the catalog CSV |
| `--artist` | *(all rows)* | Filter to rows where `Artist` matches this value (case-insensitive) |
| `--out` | `dashboard.html` | Output HTML dashboard file |
| `--json-out` | `dashboard.json` | Output JSON sidecar file |
| `--user-agent` | built-in | MusicBrainz `User-Agent` header — **replace with your app name and contact email** |
| `--release-country` | *(blank)* | ISO country code to seed on release events, e.g. `XW` (worldwide) or `US` |
| `--language` | `eng` | ISO 639-3 language code to seed on releases |
| `--script` | `Latn` | ISO 15924 script code to seed on releases |
| `--status` | `official` | Release status to seed |
| `--medium-format` | `Digital Media` | Medium format to seed |
| `--multi-track-primary-type` | *(blank)* | Release group primary type for multi-track releases, e.g. `Album` or `EP`. Single-track releases are always typed as `Single`. |
| `--lookup-limit` | `5` | Max candidate results per entity search (capped at 25) |
| `--no-lookup` | off | Skip all `/ws/2` lookups — generates seed forms and links only, no HTTP requests |
| `--edit-note` | built-in | Edit note pre-filled into the release editor seeding form |

### Examples

```bash
# Full run with lookups
python main.py songs.csv --artist "Dezolent" --release-country XW --multi-track-primary-type Album

# Generate dashboard without hitting the API (fast, offline)
python main.py songs.csv --no-lookup --out preview.html

# Custom output paths
python main.py songs.csv --out releases.html --json-out releases.json
```

---

## CSV format

The importer expects a CSV with at least these columns (extra columns are preserved):

| Column | Used for |
|---|---|
| `Artist` | Track artist; fallback release artist |
| `Title` | Track title |
| `Release Artist` | Release-level artist (overrides `Artist` for grouping) |
| `Release` | Release title |
| `Release Label` | Label name |
| `Release Date` | Supports `MM/DD/YY`, `MM/DD/YYYY`, and `YYYY-MM-DD` |
| `Year` | Release year (display only) |
| `UPC` | Barcode — used for exact release lookup |
| `Catalog Number` | Seeded into the release editor label info |
| `ISRC` | Used for exact recording lookup |
| `ISWC` | Used for exact work lookup |
| `Duration` | Track length — supports `M:SS` and `H:MM:SS` |
| `Writer/Composer 1–3` | Used to narrow work searches |
| `MusicBrainz` | **Written back automatically** with the release URL when a match is found |

### CSV writeback

After each run, the importer updates your source CSV:
- If a release is matched in MusicBrainz, every track row belonging to that release gets the release URL written to the `MusicBrainz` column
- Rows that already have a value in that column are left untouched
- If the column doesn't exist, it is added automatically

---

## Project structure

```
musicbrainz-importer/
├── main.py                          # Entry point
├── requirements.txt
└── musicbrainz_importer/
    ├── constants.py                 # API base URLs, rate limit, entity keys
    ├── models.py                    # LookupHit, TrackPlan, ReleasePlan dataclasses
    ├── utils.py                     # String cleaning, parsing, MB URL builders
    ├── client.py                    # MusicBrainzClient (with retry) + pick_best_hit
    ├── catalog.py                   # CSV reading, grouping, plan building, CSV writeback
    ├── renderer.py                  # HTML dashboard + JSON sidecar output
    └── cli.py                       # Argument parsing + main()
```

---

## MusicBrainz API notes

- The importer respects MusicBrainz's rate limit of **1 request per second** (`RATE_LIMIT_SECONDS = 1.1`)
- Transient timeouts are retried up to **3 times** with 5 → 15 → 30 second back-off; failed lookups are skipped gracefully rather than crashing
- Set a descriptive `User-Agent` as required by the [MusicBrainz API etiquette](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting): `AppName/Version (contact@example.com)`
- Release seeding uses the official [MusicBrainz seeding protocol](https://musicbrainz.org/doc/Development/Release_Editor_Seeding) — nothing is submitted automatically

MB_BASE = "https://musicbrainz.org"
WS_BASE = f"{MB_BASE}/ws/2"
DEFAULT_UA = "dezolent-musicbrainz-importer/0.1 (dezolent@gmail.com)"
RATE_LIMIT_SECONDS = 1.1

ENTITY_COLLECTION_KEYS = {
    "artist": "artists",
    "label": "labels",
    "release": "releases",
    "release-group": "release-groups",
    "recording": "recordings",
    "work": "works",
}

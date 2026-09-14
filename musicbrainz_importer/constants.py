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

# Release-URL relationship link type IDs (integer ids used by release editor seeding).
# Verified against https://musicbrainz.org/relationships/release-url
LINK_TYPE_PURCHASE_FOR_DOWNLOAD = 74
LINK_TYPE_DOWNLOAD_FOR_FREE = 75
LINK_TYPE_DISCOGS = 76
LINK_TYPE_AMAZON_ASIN = 77
LINK_TYPE_FREE_STREAMING = 85
LINK_TYPE_STREAMING = 980
LINK_TYPE_DISCOGRAPHY_ENTRY = 288

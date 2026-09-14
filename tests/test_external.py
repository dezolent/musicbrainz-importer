"""External enrichment sources: pure parsing and matching helpers."""

from musicbrainz_importer.external.coverart import cover_art_url
from musicbrainz_importer.external.discogs import discogs_release_url, match_discogs_release
from musicbrainz_importer.external.itunes import parse_itunes_lookup
from musicbrainz_importer.external.links import build_external_links
from musicbrainz_importer.external.spotify import parse_spotify_album_search, parse_spotify_track_search
from musicbrainz_importer.models import ExternalRelease, ExternalTrack


# --------------------------------------------------------------------------- Spotify

SPOTIFY_TRACKS = {"tracks": {"items": [{
    "name": "Faded Memories", "duration_ms": 258063,
    "artists": [{"name": "Dezolent"}],
    "external_ids": {"isrc": "USJ3V1232958"},
    "external_urls": {"spotify": "https://open.spotify.com/track/6vZk"},
    "album": {"name": "It's Dezolent", "release_date": "2013-03-05", "external_urls": {"spotify": "https://open.spotify.com/album/55FV"}},
}]}}

SPOTIFY_ALBUMS = {"albums": {"items": [{
    "name": "It's Dezolent", "release_date": "2013-03-05", "total_tracks": 5, "album_type": "single",
    "external_urls": {"spotify": "https://open.spotify.com/album/55FV"},
    "artists": [{"name": "Dezolent"}],
}]}}


def test_parse_spotify_track_search_returns_external_track():
    tracks = parse_spotify_track_search(SPOTIFY_TRACKS)
    assert tracks == [ExternalTrack(
        source="spotify", url="https://open.spotify.com/track/6vZk", title="Faded Memories",
        artists=["Dezolent"], duration_ms=258063, isrc="USJ3V1232958",
        album_url="https://open.spotify.com/album/55FV", album_title="It's Dezolent", album_date="2013-03-05",
    )]


def test_parse_spotify_album_search_returns_external_release():
    rel = parse_spotify_album_search(SPOTIFY_ALBUMS)
    assert rel == ExternalRelease(
        source="spotify", url="https://open.spotify.com/album/55FV", title="It's Dezolent", date="2013-03-05",
        track_count=5, artists=["Dezolent"], label="", tracks=[],
    )


def test_parse_spotify_empty_payloads():
    assert parse_spotify_track_search({}) == []
    assert parse_spotify_album_search({"albums": {"items": []}}) is None


# --------------------------------------------------------------------------- iTunes

ITUNES = {"resultCount": 3, "results": [
    {"wrapperType": "collection", "collectionName": "It's Dezolent - EP", "artistName": "Dezolent", "trackCount": 5,
     "releaseDate": "2013-03-05T08:00:00Z", "collectionViewUrl": "https://music.apple.com/us/album/its-dezolent-ep/615986729?uo=4",
     "copyright": "℗ 2013 NumenSkepsisRecords"},
    {"wrapperType": "track", "kind": "song", "trackName": "Descent", "artistName": "Dezolent", "trackTimeMillis": 200072,
     "trackViewUrl": "https://music.apple.com/us/album/descent/615986729?i=615986736&uo=4", "trackNumber": 1},
    {"wrapperType": "track", "kind": "song", "trackName": "Faded Memories", "artistName": "Dezolent", "trackTimeMillis": 258064,
     "trackViewUrl": "https://music.apple.com/us/album/faded-memories/615986729?i=615986738&uo=4", "trackNumber": 2},
]}


def test_parse_itunes_lookup_builds_release_with_tracks():
    rel = parse_itunes_lookup(ITUNES)
    assert rel.source == "itunes"
    assert rel.url == "https://music.apple.com/us/album/its-dezolent-ep/615986729"
    assert rel.title == "It's Dezolent - EP" and rel.date == "2013-03-05" and rel.track_count == 5
    assert rel.label == "℗ 2013 NumenSkepsisRecords"
    assert [(t.title, t.duration_ms) for t in rel.tracks] == [("Descent", 200072), ("Faded Memories", 258064)]
    assert rel.tracks[0].url == "https://music.apple.com/us/album/descent/615986729?i=615986736"


def test_parse_itunes_lookup_returns_none_without_collection():
    assert parse_itunes_lookup({"resultCount": 0, "results": []}) is None


# --------------------------------------------------------------------------- Discogs

DISCOGS = [
    {"id": 37013988, "title": "Dezolent - Gone (Coptr Remix)", "year": "2026", "catno": "DEZ-26-0001-W", "barcode": ["821317019796"], "uri": "/release/37013988-Dezolent-Gone-Coptr-Remix"},
    {"id": 35303032, "title": "Dezolent  feat.  Mona Moua - Gone", "year": "2014", "catno": "none", "barcode": ["GBKQU1591272", "ASCAP"], "uri": "/release/35303032-Dezolent-feat-Mona-Moua-Gone"},
    {"id": 35322802, "title": "Dezolent  &  Coptr  Feat.  Lillie Price Carter - Lost Love", "year": "2025", "catno": "DEZ-25-0002-W", "barcode": ["199740603098", "QT3F22541854"], "uri": "/release/35322802-Lost-Love"},
]


def test_match_discogs_release_by_barcode():
    assert match_discogs_release(DISCOGS, upc="821317019796", catalog_number="", isrcs=[], title="Whatever")["id"] == 37013988


def test_match_discogs_release_by_isrc_when_barcode_missing():
    assert match_discogs_release(DISCOGS, upc="085494590619", catalog_number="DEZ-14-0002-W", isrcs=["GBKQU1591272"], title="Gone")["id"] == 35303032


def test_match_discogs_release_by_catalog_number():
    assert match_discogs_release(DISCOGS, upc="", catalog_number="dez-25-0002-w", isrcs=[], title="Lost Love")["id"] == 35322802


def test_match_discogs_release_by_title_falls_back_to_artist_dash_title_form():
    assert match_discogs_release(DISCOGS, upc="", catalog_number="", isrcs=[], title="Gone (Coptr Remix)")["id"] == 37013988


def test_match_discogs_release_returns_none_when_nothing_matches():
    assert match_discogs_release(DISCOGS, upc="000", catalog_number="X", isrcs=["NOPE"], title="Sonder") is None


def test_discogs_release_url_is_absolute():
    assert discogs_release_url(DISCOGS[1]) == "https://www.discogs.com/release/35303032-Dezolent-feat-Mona-Moua-Gone"


# --------------------------------------------------------------------------- Cover Art Archive

def test_cover_art_url():
    assert cover_art_url("e14f83cc-08fd") == "https://coverartarchive.org/release/e14f83cc-08fd/front-250"
    assert cover_art_url("e14f83cc-08fd", size=500) == "https://coverartarchive.org/release/e14f83cc-08fd/front-500"


# --------------------------------------------------------------------------- Link assembly

def test_build_external_links_assigns_musicbrainz_link_types_and_dedupes():
    links = build_external_links(
        csv_discogs="https://www.discogs.com/release/35303032-Dezolent-feat-Mona-Moua-Gone",
        csv_asin="B0FSC81QLH",
        discogs_url="https://www.discogs.com/release/35303032-Dezolent-feat-Mona-Moua-Gone",
        spotify_album_url="https://open.spotify.com/album/55FV",
        apple_album_url="https://music.apple.com/us/album/its-dezolent-ep/615986729",
    )
    by_url = {l.url: l for l in links}
    assert len(links) == 4  # discogs deduped
    assert by_url["https://www.discogs.com/release/35303032-Dezolent-feat-Mona-Moua-Gone"].link_type_id == 76
    assert by_url["https://www.amazon.com/dp/B0FSC81QLH"].link_type_id == 77
    assert by_url["https://open.spotify.com/album/55FV"].link_type_id == 85
    assert by_url["https://music.apple.com/us/album/its-dezolent-ep/615986729"].link_type_id == 980


def test_build_external_links_skips_blanks():
    assert build_external_links(csv_discogs="", csv_asin="", discogs_url="", spotify_album_url="", apple_album_url="") == []

"""Artist website (schema.org JSON-LD) as a first-party source."""

import json

from musicbrainz_importer.external.website import (
    match_site_track,
    parse_track_list,
    parse_track_page,
    spotify_track_id,
    apple_song_id,
)


def _ld(graph):
    return '<html><head><script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": graph}) + "</script></head><body></body></html>"


LIST_HTML = _ld([{
    "@type": "ItemList",
    "itemListElement": [
        {"@type": "ListItem", "position": 1, "item": {"@type": "MusicRecording", "name": "Descent", "url": "https://dezolent.com/tracks/descent", "datePublished": "2013-03-05", "duration": "PT3M20S"}},
        {"@type": "ListItem", "position": 2, "item": {"@type": "MusicRecording", "name": "Gone (feat. Mona Moua) [Coptr Remix]", "url": "https://dezolent.com/tracks/gone-coptr-remix", "datePublished": "2026-03-25", "duration": "PT2M51S"}},
    ],
}])

TRACK_HTML = _ld([
    {"@type": "MusicComposition", "@id": "https://dezolent.com/tracks/gone-coptr-remix#composition", "name": "Gone (feat. Mona Moua) [Coptr Remix]", "iswcCode": "T3387417296"},
    {"@type": "MusicAlbum", "@id": "https://dezolent.com/tracks/gone-coptr-remix#album", "name": "Gone (feat. Mona Moua) [Coptr Remix]", "numTracks": 1,
     "albumReleaseType": "https://schema.org/SingleRelease", "datePublished": "2026-03-25",
     "image": {"@type": "ImageObject", "url": "https://dezolent.com/images/covers/gone-coptr-remix.webp"}},
    {"@type": "MusicRecording", "@id": "https://dezolent.com/tracks/gone-coptr-remix#recording", "name": "Gone (feat. Mona Moua) [Coptr Remix]",
     "url": "https://dezolent.com/tracks/gone-coptr-remix", "duration": "PT2M51S", "datePublished": "2026-03-25", "isrcCode": "QT6K52600001",
     "sameAs": ["https://dezolent.com/stream/gone-coptr-remix", "https://www.youtube.com/watch?v=g6uKB4f9gww",
                "https://open.spotify.com/track/4WwUShhdlCySFa04dPTxzy?utm_source=dezolent", "https://soundcloud.com/dezolent/gone-coptr-remix",
                "https://music.apple.com/us/song/gone-feat-mona-moua-coptr-remix/1879354025"]},
]).replace("<body></body>", '<body><a href="https://tidal.com/album/500578339/track/500578340">Tidal</a>'
           '<a href="https://www.deezer.com/us/track/3856046051">Deezer</a><a href="https://www.beatport.com/release/x/5944943">Beatport</a>'
           '<a href="https://amzn.to/4mFtORn">Amazon</a><a href="https://open.spotify.com/artist/1aVSunBLO69oMFT3ZRfwiZ">artist</a>'
           '<div data-lyrics><h2>Lyrics</h2></div></body>')


def test_parse_track_list_returns_page_urls_titles_and_durations():
    items = parse_track_list(LIST_HTML)
    assert [(i.title, i.url, i.duration_ms, i.date) for i in items] == [
        ("Descent", "https://dezolent.com/tracks/descent", 200000, "2013-03-05"),
        ("Gone (feat. Mona Moua) [Coptr Remix]", "https://dezolent.com/tracks/gone-coptr-remix", 171000, "2026-03-25"),
    ]


def test_parse_track_page_extracts_identifiers_media_and_links():
    track = parse_track_page(TRACK_HTML, "https://dezolent.com/tracks/gone-coptr-remix")
    assert track.isrc == "QT6K52600001" and track.iswc == "T3387417296"
    assert track.duration_ms == 171000 and track.date == "2026-03-25"
    assert track.cover_url == "https://dezolent.com/images/covers/gone-coptr-remix.webp"
    assert track.stream_url == "https://dezolent.com/stream/gone-coptr-remix"
    assert track.has_lyrics is True
    assert track.release_type == "Single" and track.track_count == 1
    assert track.links["spotify"] == "https://open.spotify.com/track/4WwUShhdlCySFa04dPTxzy"  # tracking param stripped
    assert track.links["apple"] == "https://music.apple.com/us/song/gone-feat-mona-moua-coptr-remix/1879354025"
    assert track.links["youtube"] == "https://www.youtube.com/watch?v=g6uKB4f9gww"
    assert track.links["soundcloud"] == "https://soundcloud.com/dezolent/gone-coptr-remix"
    assert track.links["tidal"].startswith("https://tidal.com/") and track.links["deezer"].startswith("https://www.deezer.com/")
    assert track.links["beatport"].startswith("https://www.beatport.com/") and track.links["amazon"] == "https://amzn.to/4mFtORn"
    assert "artist" not in track.links  # artist-profile links are not track links


def test_parse_track_page_tolerates_missing_structured_data():
    track = parse_track_page("<html><body>nothing</body></html>", "https://x/tracks/a")
    assert track.isrc == "" and track.links == {} and track.cover_url == ""


def test_provider_id_helpers():
    assert spotify_track_id("https://open.spotify.com/track/4WwUShhdlCySFa04dPTxzy?utm_source=dezolent") == "4WwUShhdlCySFa04dPTxzy"
    assert spotify_track_id("https://open.spotify.com/artist/abc") == ""
    assert apple_song_id("https://music.apple.com/us/song/gone-feat-mona-moua-coptr-remix/1879354025") == "1879354025"
    assert apple_song_id("https://music.apple.com/us/album/x/123?i=456") == "456"


def test_match_site_track_by_isrc_then_normalized_title():
    a = parse_track_page(TRACK_HTML, "https://dezolent.com/tracks/gone-coptr-remix")
    assert match_site_track([a], isrc="QT6K52600001", title="Whatever") is a
    assert match_site_track([a], isrc="ZZZ", title="Gone - Coptr Remix") is a  # "(feat. …)" and brackets normalized away
    assert match_site_track([a], isrc="ZZZ", title="Gone") is None

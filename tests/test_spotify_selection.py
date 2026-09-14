"""Choosing the right Spotify track among ISRC search results (Spotify's ISRC data collides)."""

from musicbrainz_importer.external.spotify import select_spotify_track
from musicbrainz_importer.models import ExternalTrack


def _t(title, artists, duration, album, album_date="2018-09-07", url="https://open.spotify.com/track/x"):
    return ExternalTrack(source="spotify", url=url, title=title, artists=artists, duration_ms=duration,
                         isrc="GBKQU1994609", album_url="https://open.spotify.com/album/a", album_title=album, album_date=album_date)


def test_rejects_track_credited_to_a_different_artist():
    wrong = _t("Stars Appear At Sunset - W!SS Remix", ["Victor Special", "W!SS"], 370435, "Stars Appear At Sunset")
    chosen, reason = select_spotify_track([wrong], artist="Dezolent", title="Last Seven Days", duration_ms=247000, release_title="Last Seven Days")
    assert chosen is None
    assert "Victor Special" in reason


def test_accepts_track_when_any_credited_artist_matches_a_collaborator():
    ok = _t("Gone - Coptr Remix", ["Dezolent", "Mona Moua", "Coptr"], 171000, "Gone (Coptr Remix)")
    chosen, _ = select_spotify_track([ok], artist="Dezolent & Coptr", title="Gone - Coptr Remix", duration_ms=171000, release_title="Gone (Coptr Remix)")
    assert chosen is ok


def test_prefers_candidate_from_the_same_release_when_isrc_appears_on_several_albums():
    single = _t("Gone - Original Mix", ["Dezolent", "Mona Moua"], 255649, "Gone", "2014-09-24", url="https://open.spotify.com/track/single")
    on_ep = _t("Gone", ["Dezolent", "Mona Moua"], 258000, "Desolation", "2024-12-04", url="https://open.spotify.com/track/ep")
    chosen, _ = select_spotify_track([single, on_ep], artist="Dezolent", title="Gone", duration_ms=258000, release_title="Desolation")
    assert chosen is on_ep
    chosen, _ = select_spotify_track([single, on_ep], artist="Dezolent", title="Gone", duration_ms=258000, release_title="Gone")
    assert chosen is single


def test_falls_back_to_closest_duration_when_no_album_matches():
    a = _t("Gone", ["Dezolent"], 250000, "Compilation A", url="https://open.spotify.com/track/a")
    b = _t("Gone", ["Dezolent"], 258100, "Compilation B", url="https://open.spotify.com/track/b")
    chosen, _ = select_spotify_track([a, b], artist="Dezolent", title="Gone", duration_ms=258000, release_title="Gone")
    assert chosen is b


def test_returns_none_for_empty_candidates():
    assert select_spotify_track([], artist="Dezolent", title="X", duration_ms=None, release_title="X") == (None, "")

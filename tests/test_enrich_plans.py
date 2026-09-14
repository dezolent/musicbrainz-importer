"""enrich_plans orchestration with fake clients (no network)."""

from musicbrainz_importer.enrichment import enrich_plans
from musicbrainz_importer.external.website import SiteTrack
from musicbrainz_importer.models import ExternalTrack, ReleasePlan, TrackPlan

ISRC = "GBKQU1591272"
SINGLE = ExternalTrack(source="spotify", url="https://open.spotify.com/track/single", title="Gone - Original Mix", artists=["Dezolent", "Mona Moua"],
                       duration_ms=255649, isrc=ISRC, album_title="Gone", album_date="2014-09-24", album_url="https://open.spotify.com/album/s")
ON_EP = ExternalTrack(source="spotify", url="https://open.spotify.com/track/ep", title="Gone", artists=["Dezolent", "Mona Moua"],
                      duration_ms=258000, isrc=ISRC, album_title="Desolation", album_date="2024-12-04", album_url="https://open.spotify.com/album/e")


class FakeSpotify:
    enabled = True
    request_count = 0

    def __init__(self):
        self.calls = []

    def album_by_upc(self, upc):
        return None

    def track_by_id(self, track_id):
        self.calls.append(("by_id", track_id))
        return SINGLE  # the website links the 2014 single for both releases of "Gone"

    def tracks_by_isrc(self, isrc):
        self.calls.append(("by_isrc", isrc))
        return [SINGLE, ON_EP]


class FakeWebsite:
    enabled = True
    request_count = 0
    cache_hits = 0

    def tracks(self):
        return [SiteTrack(url="https://dezolent.com/tracks/gone", title="Gone", isrc=ISRC, duration_ms=None,
                          links={"spotify": "https://open.spotify.com/track/single"})]

    def albums(self):
        return []


def _plan(release_title, duration_ms):
    track = TrackPlan(title="Gone", artist="Dezolent", duration_raw="", duration_mmss="", duration_ms=duration_ms, isrc=ISRC, iswc="",
                      writer_composers=[], source_row_number=1)
    return ReleasePlan(title=release_title, release_artist="Dezolent", release_label="", release_date_raw="", release_date_iso="", year="",
                       upc="", catalog_number="", status="official", primary_type="", medium_format="Digital Media",
                       artist_hit=None, label_hit=None, release_hit=None, release_group_hit=None, tracks=[track])


def test_site_spotify_link_is_used_directly_when_its_album_matches_the_release():
    plan = _plan("Gone", 256000)
    spotify = FakeSpotify()
    enrich_plans([plan], spotify, None, None, FakeWebsite())
    assert spotify.calls == [("by_id", "single")]
    assert plan.tracks[0].discrepancies == []


def test_site_spotify_link_from_another_release_falls_back_to_isrc_search_for_same_release():
    plan = _plan("Desolation", 258000)
    spotify = FakeSpotify()
    enrich_plans([plan], spotify, None, None, FakeWebsite())
    assert ("by_isrc", ISRC) in spotify.calls
    assert [d.field for d in plan.tracks[0].discrepancies] == []  # 4:18 vs the EP version's 4:18, not the single's 4:16
    urls = [l.url for l in plan.tracks[0].external_links if l.source == "spotify"]
    assert urls == ["https://open.spotify.com/track/ep"]

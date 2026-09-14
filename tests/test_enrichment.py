"""Applying third-party lookups to a plan: links plus cross-source discrepancies."""

from musicbrainz_importer.enrichment import apply_enrichment
from musicbrainz_importer.models import ExternalRelease, ExternalTrack, ReleasePlan, TrackPlan


def _plan(**overrides) -> ReleasePlan:
    base = dict(
        title="It's Dezolent", release_artist="Dezolent", release_label="Dezolent, LLC", release_date_raw="3/5/13",
        release_date_iso="2013-03-05", year="2013", upc="886296197774", catalog_number="DEZ-13-0001-W",
        status="official", primary_type="EP", medium_format="Digital Media",
        artist_hit=None, label_hit=None, release_hit=None, release_group_hit=None,
        tracks=[
            TrackPlan(title="Descent", artist="Dezolent", duration_raw="3:20", duration_mmss="3:20", duration_ms=200000,
                      isrc="USJ3V1232957", iswc="", writer_composers=[], source_row_number=2),
            TrackPlan(title="Faded Memories", artist="Dezolent", duration_raw="4:18", duration_mmss="4:18", duration_ms=258000,
                      isrc="USJ3V1232958", iswc="", writer_composers=[], source_row_number=6),
        ],
    )
    base.update(overrides)
    return ReleasePlan(**base)


SPOTIFY = ExternalRelease(source="spotify", url="https://open.spotify.com/album/55FV", title="It's Dezolent", date="2013-03-05", track_count=5)
ITUNES = ExternalRelease(
    source="itunes", url="https://music.apple.com/us/album/its-dezolent-ep/615986729", title="It's Dezolent - EP",
    date="2013-03-05", track_count=5, label="℗ 2013 NumenSkepsisRecords",
    tracks=[
        ExternalTrack(source="itunes", url="https://music.apple.com/x?i=1", title="Descent", artists=["Dezolent"], duration_ms=200072),
        ExternalTrack(source="itunes", url="https://music.apple.com/x?i=2", title="Faded Memories", artists=["Dezolent"], duration_ms=251000),
    ],
)
DISCOGS = {"id": 1, "title": "Dezolent - It's Dezolent", "uri": "/release/1-Its-Dezolent", "year": "2013"}


def test_apply_enrichment_adds_links_for_each_source():
    plan = _plan()
    apply_enrichment(plan, spotify=SPOTIFY, itunes=ITUNES, discogs=DISCOGS)
    by_source = {l.source: l.url for l in plan.external_links}
    assert by_source["spotify"] == "https://open.spotify.com/album/55FV"
    assert by_source["itunes"] == "https://music.apple.com/us/album/its-dezolent-ep/615986729"
    assert by_source["discogs"] == "https://www.discogs.com/release/1-Its-Dezolent"


def test_apply_enrichment_flags_release_date_disagreement_with_source():
    plan = _plan(release_date_iso="2013-03-06")
    apply_enrichment(plan, spotify=SPOTIFY, itunes=None, discogs=None)
    d = [x for x in plan.discrepancies if x.field == "release_date"]
    assert len(d) == 1 and d[0].source == "spotify" and d[0].mb_value == "2013-03-05"


def test_apply_enrichment_flags_track_length_disagreement_by_title():
    plan = _plan()
    apply_enrichment(plan, spotify=None, itunes=ITUNES, discogs=None)
    assert plan.tracks[0].discrepancies == []
    d = plan.tracks[1].discrepancies
    assert len(d) == 1 and d[0].field == "length" and d[0].source == "itunes" and d[0].mb_value == "4:11"


def test_apply_enrichment_attaches_external_track_urls():
    plan = _plan()
    apply_enrichment(plan, spotify=None, itunes=ITUNES, discogs=None)
    assert plan.tracks[0].external_links[0].url == "https://music.apple.com/x?i=1"
    assert plan.tracks[0].external_links[0].source == "itunes"


def test_apply_enrichment_with_nothing_is_a_noop():
    plan = _plan()
    apply_enrichment(plan, spotify=None, itunes=None, discogs=None)
    assert plan.external_links == [] and plan.discrepancies == []


def test_apply_enrichment_records_which_sources_were_checked():
    plan = _plan()
    apply_enrichment(plan, spotify=None, itunes=ITUNES, discogs=None, checked=("spotify", "itunes"))
    assert plan.external_status == {"spotify": "missing", "itunes": "found"}


# --------------------------------------------------------------------------- website + Spotify validation

from musicbrainz_importer.external.website import SiteAlbum, SiteTrack  # noqa: E402


def _site_track(**kw):
    base = dict(url="https://dezolent.com/tracks/faded-memories", title="Faded Memories", isrc="USJ3V1232958", iswc="T3294828545",
                duration_ms=258000, date="2013-03-05", cover_url="https://dezolent.com/images/covers/its-dezolent-ep.webp",
                stream_url="https://dezolent.com/stream/faded-memories", has_lyrics=True, release_type="EP", track_count=5,
                album_url="https://dezolent.com/albums/its-dezolent-ep",
                links={"spotify": "https://open.spotify.com/track/6vZk", "apple": "https://music.apple.com/us/song/faded-memories/615986738",
                       "youtube": "https://www.youtube.com/watch?v=abc"})
    base.update(kw)
    return SiteTrack(**base)


def test_site_track_links_are_attached_to_the_track_with_labels():
    plan = _plan()
    apply_enrichment(plan, spotify=None, itunes=None, discogs=None, site_tracks=[None, _site_track()])
    labels = {l.label: l.url for l in plan.tracks[1].external_links}
    assert labels["Website"] == "https://dezolent.com/tracks/faded-memories"
    assert labels["Lyrics"] == "https://dezolent.com/tracks/faded-memories#lyrics"
    assert labels["Spotify"] == "https://open.spotify.com/track/6vZk"
    assert labels["Apple Music"].startswith("https://music.apple.com/")
    assert labels["YouTube"] == "https://www.youtube.com/watch?v=abc"
    assert plan.tracks[0].external_links == []


def test_site_isrc_and_iswc_disagreements_are_warnings_from_the_website():
    plan = _plan()
    apply_enrichment(plan, spotify=None, itunes=None, discogs=None, site_tracks=[None, _site_track(isrc="USJ3V1232999", iswc="T0000000000")])
    d = {x.field: x for x in plan.tracks[1].discrepancies}
    assert d["isrc"].source == "website" and d["isrc"].csv_value == "USJ3V1232958" and d["isrc"].mb_value == "USJ3V1232999"
    assert d["iswc"].source == "website" and d["iswc"].severity == "warn"


def test_site_album_becomes_discography_link_and_cover_fallback():
    plan = _plan()
    album = SiteAlbum(url="https://dezolent.com/albums/its-dezolent-ep", title="It's Dezolent", date="2013-03-05",
                      cover_url="https://dezolent.com/images/covers/its-dezolent-ep.webp", release_type="EP", track_count=5)
    apply_enrichment(plan, spotify=None, itunes=None, discogs=None, site_album=album)
    link = [l for l in plan.external_links if l.source == "website"][0]
    assert link.url == "https://dezolent.com/albums/its-dezolent-ep" and link.link_type_id == 288
    assert plan.site_url == "https://dezolent.com/albums/its-dezolent-ep"
    assert plan.site_cover_url == "https://dezolent.com/images/covers/its-dezolent-ep.webp"


def test_single_track_release_uses_the_track_page_as_discography_link():
    plan = _plan(title="Faded Memories", tracks=[_plan().tracks[1]])
    apply_enrichment(plan, spotify=None, itunes=None, discogs=None, site_tracks=[_site_track()])
    link = [l for l in plan.external_links if l.link_type_id == 288][0]
    assert link.url == "https://dezolent.com/tracks/faded-memories"
    assert plan.site_cover_url.endswith("its-dezolent-ep.webp")


def test_spotify_track_isrc_disagreement_is_reported():
    plan = _plan()
    sp = ExternalTrack(source="spotify", url="https://open.spotify.com/track/4rP9", title="Faded Memories", artists=["Dezolent"],
                       duration_ms=258000, isrc="USJ3V1239999")
    apply_enrichment(plan, spotify=None, itunes=None, discogs=None, spotify_tracks={"USJ3V1232958": sp})
    d = [x for x in plan.tracks[1].discrepancies if x.field == "isrc"]
    assert len(d) == 1 and d[0].source == "spotify" and d[0].mb_value == "USJ3V1239999" and d[0].severity == "warn"


def test_spotify_rejection_reason_is_recorded_as_a_warning():
    plan = _plan()
    apply_enrichment(plan, spotify=None, itunes=None, discogs=None,
                     spotify_rejections={"USJ3V1232958": "Spotify's result for this ISRC is credited to Victor Special, not Dezolent"})
    d = [x for x in plan.tracks[1].discrepancies if x.field == "spotify_match"]
    assert len(d) == 1 and d[0].severity == "warn" and "Victor Special" in d[0].message


def test_itunes_track_link_is_not_added_when_site_already_provided_apple_music():
    plan = _plan()
    apply_enrichment(plan, spotify=None, itunes=ITUNES, discogs=None, site_tracks=[None, _site_track()])
    apple = [l for l in plan.tracks[1].external_links if l.label == "Apple Music"]
    assert len(apple) == 1 and apple[0].source == "website"


def test_multi_track_release_without_album_page_links_to_first_track_page():
    plan = _plan()
    first = _site_track(url="https://dezolent.com/tracks/sonder", album_url="", cover_url="https://dezolent.com/images/covers/sonder.webp")
    second = _site_track(url="https://dezolent.com/tracks/sonder-sped-up", album_url="")
    apply_enrichment(plan, spotify=None, itunes=None, discogs=None, site_tracks=[first, second])
    assert plan.site_url == "https://dezolent.com/tracks/sonder"
    assert plan.site_cover_url.endswith("sonder.webp")

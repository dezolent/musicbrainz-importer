"""Release editor seeding fields."""

from musicbrainz_importer.models import ExternalLink, LookupHit, ReleasePlan, TrackPlan
from musicbrainz_importer.seeding import build_release_form_fields


def _hit(mbid, name="x"):
    return LookupHit(mbid=mbid, name=name, score=100, url="u", confidence="exact", method="t")


def _plan(**overrides) -> ReleasePlan:
    base = dict(
        title="Gone", release_artist="Dezolent", release_label="Dezolent, LLC", release_date_raw="9/24/14",
        release_date_iso="2014-09-24", year="2014", upc="085494590619", catalog_number="DEZ-14-0002-W",
        status="official", primary_type="Single", medium_format="Digital Media",
        artist_hit=_hit("artist-mbid", "Dezolent"), label_hit=_hit("label-mbid"), release_hit=None, release_group_hit=None,
        tracks=[TrackPlan(title="Gone", artist="Dezolent", duration_raw="4:18", duration_mmss="4:18", duration_ms=258000,
                          isrc="GBKQU1591272", iswc="", writer_composers=[], source_row_number=9)],
    )
    base.update(overrides)
    return ReleasePlan(**base)


def _fields(plan, **kw):
    defaults = dict(release_country="XW", language="eng", script="Latn", edit_note="note")
    defaults.update(kw)
    return dict(build_release_form_fields(plan, **defaults))


def test_seeds_existing_recording_mbid_for_matched_tracks():
    plan = _plan()
    plan.tracks[0].existing_recording = _hit("rec-mbid", "Gone")
    fields = _fields(plan)
    assert fields["mediums.0.track.0.recording"] == "rec-mbid"


def test_does_not_seed_recording_for_fuzzy_matches():
    plan = _plan()
    plan.tracks[0].existing_recording = LookupHit(mbid="rec", name="Gone", score=88, url="u", confidence="fuzzy", method="title")
    assert "mediums.0.track.0.recording" not in _fields(plan)


def test_seeds_release_group_mbid_instead_of_type_when_known():
    fields = _fields(_plan(release_group_hit=_hit("rg-mbid")))
    assert fields["release_group"] == "rg-mbid"
    assert "type" not in fields


def test_seeds_type_when_release_group_unknown():
    fields = _fields(_plan())
    assert fields["type"] == "Single"
    assert "release_group" not in fields


def test_seeds_url_relationships_with_link_types():
    plan = _plan(external_links=[
        ExternalLink(url="https://www.discogs.com/release/35303032", link_type_id=76, source="discogs"),
        ExternalLink(url="https://open.spotify.com/album/55F", link_type_id=85, source="spotify"),
        ExternalLink(url="https://example.com/no-type", link_type_id=None, source="csv"),
    ])
    fields = _fields(plan)
    assert fields["urls.0.url"] == "https://www.discogs.com/release/35303032" and fields["urls.0.link_type"] == "76"
    assert fields["urls.1.url"] == "https://open.spotify.com/album/55F" and fields["urls.1.link_type"] == "85"
    assert fields["urls.2.url"] == "https://example.com/no-type" and "urls.2.link_type" not in fields


def test_seeds_label_mbid_and_catalog_number():
    fields = _fields(_plan())
    assert fields["labels.0.mbid"] == "label-mbid"
    assert fields["labels.0.catalog_number"] == "DEZ-14-0002-W"
    assert fields["barcode"] == "085494590619"
    assert fields["events.0.date.year"] == "2014" and fields["events.0.country"] == "XW"


def test_seeds_track_artist_credit_only_when_it_differs_from_release_artist():
    plan = _plan()
    plan.tracks[0].artist = "Dezolent & Coptr"
    fields = _fields(plan)
    assert fields["mediums.0.track.0.artist_credit.names.0.mbid"] == "artist-mbid"
    assert fields["mediums.0.track.0.artist_credit.names.0.name"] == "Dezolent"
    assert fields["mediums.0.track.0.artist_credit.names.0.join_phrase"] == " & "
    assert fields["mediums.0.track.0.artist_credit.names.1.artist.name"] == "Coptr"
    plan.tracks[0].artist = "Dezolent"
    assert "mediums.0.track.0.artist_credit.names.0.name" not in _fields(plan)

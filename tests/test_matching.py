"""Tests for the local matching engine that runs against an artist catalog snapshot."""

from musicbrainz_importer.models import ArtistCatalog, MBRecording, MBRelease, MBTrack, MBWork
from musicbrainz_importer.matching import (
    match_recording,
    match_release,
    match_work,
    normalize_title,
    title_similarity,
)


def _catalog(releases=(), recordings=(), works=()) -> ArtistCatalog:
    return ArtistCatalog(
        artist_mbid="a4cc3b9d-6798-46d8-ac69-feb1ac9f8a0b",
        artist_name="Dezolent",
        releases=list(releases),
        recordings=list(recordings),
        works=list(works),
    )


def _recording(mbid, title, credit="Dezolent", isrcs=(), length_ms=None) -> MBRecording:
    return MBRecording(
        mbid=mbid, title=title, artist_credit=credit, artist_mbids=[], isrcs=list(isrcs),
        length_ms=length_ms, first_release_date="",
    )


def _release(mbid, title, credit="Dezolent", barcode="", date="", catno="", label="", rg_type="Single", tracks=()) -> MBRelease:
    return MBRelease(
        mbid=mbid, title=title, artist_credit=credit, barcode=barcode, date=date, country="",
        status="Official", labels=[(label, "", catno)] if label or catno else [],
        release_group_mbid="rg-" + mbid, release_group_type=rg_type,
        tracks=list(tracks), has_cover_art=True,
    )


def _work(mbid, title, iswcs=(), writers=()) -> MBWork:
    return MBWork(mbid=mbid, title=title, iswcs=list(iswcs), writers=list(writers))


# --------------------------------------------------------------------------- title normalization

def test_normalize_title_strips_feat_suffix():
    assert normalize_title("Introspection (feat. Rapzor)") == normalize_title("Introspection")


def test_normalize_title_treats_dash_remix_like_parenthesized_remix():
    assert normalize_title("Gone - Coptr Remix") == normalize_title("Gone (Coptr Remix)")


def test_normalize_title_ignores_parentheses_around_version_words():
    assert normalize_title("Sonder Sped Up") == normalize_title("Sonder (Sped Up)")


def test_title_similarity_is_one_for_identical_and_low_for_different():
    assert title_similarity("Faded Memories", "Faded Memories") == 1.0
    assert title_similarity("Faded Memories", "Never Say Too Much") < 0.5


# --------------------------------------------------------------------------- recordings

def test_match_recording_by_isrc_is_exact_even_when_credit_differs():
    cat = _catalog(recordings=[
        _recording("rec-1", "Gone - Coptr Remix", credit="Dezolent, Mona Moua, & Coptr", isrcs=["QT6K52600001"]),
        _recording("rec-2", "Gone", credit="Dezolent feat. Mona Moua", isrcs=["GBKQU1591272"]),
    ])
    hit = match_recording(cat, title="Gone - Coptr Remix", isrc="QT6K52600001", artist="Dezolent")
    assert hit is not None
    assert hit.mbid == "rec-1"
    assert hit.confidence == "exact"
    assert hit.method == "isrc"
    assert hit.extra["artist_credit"] == "Dezolent, Mona Moua, & Coptr"


def test_match_recording_falls_back_to_title_when_isrc_missing():
    cat = _catalog(recordings=[
        _recording("rec-1", "Gone - Coptr Remix", credit="Dezolent, Mona Moua, & Coptr", isrcs=["QT6K52600001"]),
        _recording("rec-2", "Gone", credit="Dezolent feat. Mona Moua", isrcs=["GBKQU1591272"]),
    ])
    hit = match_recording(cat, title="Gone (Coptr Remix)", isrc="", artist="Dezolent")
    assert hit.mbid == "rec-1"
    assert hit.confidence == "strong"
    assert hit.method == "title"


def test_match_recording_does_not_confuse_base_track_with_remix():
    cat = _catalog(recordings=[
        _recording("rec-1", "Gone - Coptr Remix", isrcs=["QT6K52600001"]),
        _recording("rec-2", "Gone", isrcs=["GBKQU1591272"]),
    ])
    hit = match_recording(cat, title="Gone", isrc="", artist="Dezolent")
    assert hit.mbid == "rec-2"


def test_match_recording_uses_fuzzy_match_and_marks_it():
    cat = _catalog(recordings=[_recording("rec-1", "Never Say Too Much", isrcs=[])])
    hit = match_recording(cat, title="Never Say To Much", isrc="", artist="Dezolent")
    assert hit.mbid == "rec-1"
    assert hit.confidence == "fuzzy"


def test_match_recording_returns_none_when_nothing_is_close():
    cat = _catalog(recordings=[_recording("rec-1", "Never Say Too Much")])
    assert match_recording(cat, title="Faded Memories", isrc="", artist="Dezolent") is None


def test_match_recording_prefers_isrc_over_a_same_titled_recording():
    cat = _catalog(recordings=[
        _recording("rec-old", "Gone", isrcs=["GBKQU1591272"]),
        _recording("rec-new", "Gone", isrcs=["ZZZZZ9999999"]),
    ])
    hit = match_recording(cat, title="Gone", isrc="ZZZZZ9999999", artist="Dezolent")
    assert hit.mbid == "rec-new"


# --------------------------------------------------------------------------- releases

def test_match_release_by_barcode_ignores_leading_zero_differences():
    cat = _catalog(releases=[_release("rel-1", "Spaced Out", barcode="019771773303")])
    hit = match_release(cat, title="Spaced Out", upc="19771773303", artist="Dezolent", catalog_number="")
    assert hit.mbid == "rel-1"
    assert hit.confidence == "exact"
    assert hit.method == "barcode"


def test_match_release_by_catalog_number_when_barcode_absent():
    cat = _catalog(releases=[_release("rel-1", "Fallen Star", catno="DEZ-13-0002-W", label="Dezolent, LLC")])
    hit = match_release(cat, title="Fallen Star", upc="", artist="Dezolent", catalog_number="DEZ-13-0002-W")
    assert hit.mbid == "rel-1"
    assert hit.method == "catalog_number"


def test_match_release_by_title_when_no_identifiers():
    cat = _catalog(releases=[
        _release("rel-1", "Gone (Coptr Remix)", credit="Dezolent & Coptr"),
        _release("rel-2", "Gone", credit="Dezolent"),
    ])
    hit = match_release(cat, title="Gone (Coptr Remix)", upc="", artist="Dezolent", catalog_number="")
    assert hit.mbid == "rel-1"
    assert hit.confidence == "strong"


def test_match_release_exposes_release_group_on_hit():
    cat = _catalog(releases=[_release("rel-1", "Sonder", barcode="199348130811", rg_type="EP")])
    hit = match_release(cat, title="Sonder", upc="199348130811", artist="Dezolent", catalog_number="")
    assert hit.extra["release_group_mbid"] == "rg-rel-1"
    assert hit.extra["release_group_type"] == "EP"


# --------------------------------------------------------------------------- works

def test_match_work_by_iswc_accepts_compact_and_formatted_forms():
    cat = _catalog(works=[_work("w-1", "Faded Memories", iswcs=["T-329.482.854-5"])])
    hit = match_work(cat, title="Faded Memories", iswc="T3294828545", writers=["Joseph Christian Hill"])
    assert hit.mbid == "w-1"
    assert hit.confidence == "exact"
    assert hit.method == "iswc"


def test_match_work_reports_duplicate_works_sharing_the_iswc():
    cat = _catalog(works=[
        _work("w-1", "Spaced Out", iswcs=["T-329.483.166-2"]),
        _work("w-2", "Spaced Out", iswcs=["T-329.483.166-2"]),
    ])
    hit = match_work(cat, title="Spaced Out", iswc="T3294831662", writers=[])
    assert hit.mbid == "w-1"
    assert hit.extra["duplicate_mbids"] == ["w-2"]


def test_match_work_by_title_tolerates_version_parentheses():
    cat = _catalog(works=[_work("w-1", "Sonder (Sped Up)", iswcs=["T-333.562.000-9"])])
    hit = match_work(cat, title="Sonder Sped Up", iswc="", writers=[])
    assert hit.mbid == "w-1"
    assert hit.confidence == "strong"

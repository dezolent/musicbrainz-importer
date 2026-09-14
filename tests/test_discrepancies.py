"""CSV-vs-MusicBrainz discrepancy detection and CSV self-consistency checks."""

from musicbrainz_importer.discrepancies import compare_release, compare_track, validate_release
from musicbrainz_importer.models import LookupHit, ReleasePlan, TrackPlan


def _plan(**overrides) -> ReleasePlan:
    base = dict(
        title="Gone", release_artist="Dezolent", release_label="Dezolent, LLC", release_date_raw="9/24/14",
        release_date_iso="2014-09-24", year="2014", upc="085494590619", catalog_number="DEZ-14-0002-W",
        status="official", primary_type="Single", medium_format="Digital Media",
        artist_hit=None, label_hit=None, release_hit=None, release_group_hit=None, tracks=[],
    )
    base.update(overrides)
    return ReleasePlan(**base)


def _track(**overrides) -> TrackPlan:
    base = dict(
        title="Gone", artist="Dezolent", duration_raw="4:18", duration_mmss="4:18", duration_ms=258000,
        isrc="GBKQU1591272", iswc="T3294665304", writer_composers=["Joseph Christian Hill"], source_row_number=9,
    )
    base.update(overrides)
    return TrackPlan(**base)


def _release_hit(**extra) -> LookupHit:
    base = dict(date="2014-09-24", barcode="085494590619", labels=[["Dezolent, LLC", "0dea", "DEZ-14-0002-W"]],
                artist_credit="Dezolent", track_count=1, release_group_type="Single")
    base.update(extra)
    return LookupHit(mbid="rel", name="Gone", score=100, url="u", extra=base, confidence="exact", method="barcode")


def _fields(discrepancies):
    return {d.field for d in discrepancies}


def test_compare_release_is_empty_when_everything_agrees():
    plan = _plan(tracks=[_track()])
    assert compare_release(plan, _release_hit()) == []


def test_compare_release_flags_date_difference_as_warning():
    result = compare_release(_plan(tracks=[_track()]), _release_hit(date="2014-09-20"))
    assert len(result) == 1
    d = result[0]
    assert d.field == "release_date" and d.csv_value == "2014-09-24" and d.mb_value == "2014-09-20"
    assert d.severity == "warn"


def test_compare_release_ignores_barcode_leading_zero_difference():
    assert compare_release(_plan(upc="85494590619", tracks=[_track()]), _release_hit()) == []


def test_compare_release_flags_missing_catalog_number_on_mb_as_info():
    result = compare_release(_plan(tracks=[_track()]), _release_hit(labels=[["Dezolent, LLC", "0dea", None]]))
    assert _fields(result) == {"catalog_number"}
    assert result[0].severity == "info"


def test_compare_release_flags_label_and_track_count_differences():
    result = compare_release(
        _plan(tracks=[_track(), _track(title="Bonus")]),
        _release_hit(labels=[["Revamped Recordings", "x", "DEZ-14-0002-W"]], track_count=1),
    )
    assert _fields(result) == {"label", "track_count"}


def test_compare_release_flags_primary_type_difference():
    result = compare_release(_plan(primary_type="Album", tracks=[_track()]), _release_hit(release_group_type="EP"))
    assert _fields(result) == {"primary_type"}


def test_compare_track_ignores_length_within_two_seconds():
    hit = LookupHit(mbid="r", name="Gone", score=100, url="u", extra={"length_ms": 259500, "artist_credit": "Dezolent"}, confidence="exact", method="isrc")
    assert compare_track(_track(), hit) == []


def test_compare_track_flags_length_difference_beyond_two_seconds():
    hit = LookupHit(mbid="r", name="Gone", score=100, url="u", extra={"length_ms": 255000, "artist_credit": "Dezolent"}, confidence="exact", method="isrc")
    result = compare_track(_track(), hit)
    assert _fields(result) == {"length"}
    assert result[0].csv_value == "4:18" and result[0].mb_value == "4:15"


def test_compare_track_reports_title_difference_only_for_non_exact_titles():
    hit = LookupHit(mbid="r", name="Gone (Coptr Remix)", score=96, url="u", extra={"length_ms": 258000, "artist_credit": "Dezolent"}, confidence="strong", method="title")
    result = compare_track(_track(title="Gone - Coptr Remix"), hit)
    assert _fields(result) == {"title"} and result[0].severity == "info"


def test_compare_track_flags_duplicate_entities_as_warning():
    hit = LookupHit(mbid="r", name="Gone", score=100, url="u", extra={"length_ms": 258000, "artist_credit": "Dezolent", "duplicate_mbids": ["r2"]}, confidence="exact", method="isrc")
    result = compare_track(_track(), hit)
    assert _fields(result) == {"duplicates"} and result[0].severity == "warn"


def test_validate_release_notes_year_that_disagrees_with_release_date_as_csv_info():
    result = validate_release(_plan(year="2024", tracks=[_track()]))
    assert _fields(result) == {"year"}
    d = result[0]
    assert d.severity == "info" and d.source == "csv"
    assert d.csv_value == "2024" and d.mb_value == "2014"
    assert "Release Date" in d.message


def test_validate_release_findings_all_come_from_the_csv_itself():
    plan = _plan(upc="", release_date_raw="soon", release_date_iso="soon", year="2014", tracks=[_track(isrc="", iswc="")])
    assert {d.source for d in validate_release(plan)} == {"csv"}


def test_validate_release_flags_missing_identifiers():
    plan = _plan(upc="", tracks=[_track(isrc="", iswc="")])
    fields = _fields(validate_release(plan))
    assert fields == {"upc", "isrc", "iswc"}


def test_validate_release_flags_unparseable_release_date():
    plan = _plan(release_date_raw="41695", release_date_iso="41695", year="2014", tracks=[_track()])
    assert "release_date" in _fields(validate_release(plan))


def test_compare_track_flags_musicbrainz_recording_whose_isrcs_do_not_include_the_csv_isrc():
    hit = LookupHit(mbid="r", name="Last Seven Days", score=100, url="u", confidence="strong", method="title",
                    extra={"length_ms": 247742, "artist_credit": "Dezolent", "isrcs": ["GBKQU1994609"]})
    result = compare_track(_track(title="Last Seven Days", isrc="GBKQU1884609", duration_ms=247742), hit)
    d = [x for x in result if x.field == "isrc"]
    assert len(d) == 1 and d[0].severity == "warn" and d[0].source == "musicbrainz"
    assert d[0].csv_value == "GBKQU1884609" and d[0].mb_value == "GBKQU1994609"


def test_compare_track_notes_when_musicbrainz_recording_has_no_isrc_at_all():
    hit = LookupHit(mbid="r", name="Gone", score=100, url="u", confidence="strong", method="title",
                    extra={"length_ms": 258000, "artist_credit": "Dezolent", "isrcs": []})
    result = compare_track(_track(), hit)
    d = [x for x in result if x.field == "isrc"]
    assert len(d) == 1 and d[0].severity == "info" and d[0].mb_value == ""

"""Parsing helpers, including spreadsheet export quirks."""

from musicbrainz_importer.utils import parse_duration, parse_release_date


def test_parse_release_date_handles_us_formats_and_iso():
    assert parse_release_date("3/5/13")[0] == "2013-03-05"
    assert parse_release_date("12/05/2013")[0] == "2013-12-05"
    assert parse_release_date("2014-09-24")[0] == "2014-09-24"


def test_parse_release_date_handles_excel_serial_numbers():
    iso, parts = parse_release_date("41695")
    assert iso == "2014-02-25"
    assert parts == {"year": "2014", "month": "02", "day": "25"}
    assert parse_release_date("45848")[0] == "2025-07-10"


def test_parse_release_date_leaves_garbage_unparsed():
    iso, parts = parse_release_date("soon")
    assert iso == "soon" and parts["year"] == ""


def test_parse_duration_handles_mmss_and_hmmss():
    assert parse_duration("3:20") == ("3:20", 200000)
    assert parse_duration("1:02:03") == ("62:03", 3723000)


def test_parse_duration_handles_excel_fraction_of_day_encoding():
    # Spreadsheets store "3:54" typed as m:ss as 3h54m = 0.1625 of a day.
    assert parse_duration("0.1625") == ("3:54", 234000)
    assert parse_duration("0.148611111") == ("3:34", 214000)


def test_parse_duration_leaves_garbage_unparsed():
    assert parse_duration("long") == ("long", None)

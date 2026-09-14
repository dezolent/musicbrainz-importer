"""Splitting CSV artist strings into MusicBrainz artist credits."""

from musicbrainz_importer.seeding import artist_credit_fields, split_artist_credit


def test_single_artist():
    assert split_artist_credit("Dezolent") == [("Dezolent", "")]


def test_ampersand_collaboration():
    assert split_artist_credit("Dezolent & Tomentam") == [("Dezolent", " & "), ("Tomentam", "")]


def test_three_way_collaboration():
    assert split_artist_credit("Dezolent & Lotis & Dante Levo") == [("Dezolent", " & "), ("Lotis", " & "), ("Dante Levo", "")]


def test_featuring_clause_becomes_join_phrase():
    assert split_artist_credit("Dezolent & Tomentam feat. fendi mars") == [("Dezolent", " & "), ("Tomentam", " feat. "), ("fendi mars", "")]


def test_comma_and_ampersand_list():
    assert split_artist_credit("Dezolent, Mona Moua, & Coptr") == [("Dezolent", ", "), ("Mona Moua", " & "), ("Coptr", "")]


def test_artist_credit_fields_seed_mbid_for_known_artist_and_names_for_others():
    fields = artist_credit_fields("artist_credit.names", "Dezolent & Tomentam", known={"dezolent": "a4cc"})
    assert fields == [
        ("artist_credit.names.0.mbid", "a4cc"),
        ("artist_credit.names.0.name", "Dezolent"),
        ("artist_credit.names.0.join_phrase", " & "),
        ("artist_credit.names.1.artist.name", "Tomentam"),
        ("artist_credit.names.1.name", "Tomentam"),
    ]

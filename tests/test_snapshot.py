"""Turning raw ws/2 browse payloads into an ArtistCatalog."""

from musicbrainz_importer.snapshot import build_catalog, choose_artist

RELEASE = {
    "id": "e14f83cc", "title": "It's Dezolent", "barcode": "886296197774", "date": "2013-03-05",
    "country": "XW", "status": "Official",
    "artist-credit": [{"name": "Dezolent", "joinphrase": "", "artist": {"id": "a4cc", "name": "Dezolent"}}],
    "label-info": [{"catalog-number": "DEZ-13-0001-W", "label": {"id": "0dea", "name": "Dezolent, LLC"}}],
    "release-group": {"id": "f2fd", "primary-type": "EP"},
    "cover-art-archive": {"front": True},
    "media": [{"tracks": [
        {"position": 1, "title": "Descent", "length": 200072, "recording": {"id": "rec-descent"}},
        {"position": 2, "title": "Faded Memories", "length": 258064, "recording": {"id": "rec-faded"}},
    ]}],
}

RECORDING = {
    "id": "rec-remix", "title": "Gone - Coptr Remix", "length": 171000, "first-release-date": "2026-03-25",
    "isrcs": ["QT6K52600001"],
    "artist-credit": [
        {"name": "Dezolent", "joinphrase": ", ", "artist": {"id": "a4cc", "name": "Dezolent"}},
        {"name": "Mona Moua", "joinphrase": ", & ", "artist": {"id": "mm", "name": "Mona Moua"}},
        {"name": "Coptr", "joinphrase": "", "artist": {"id": "cp", "name": "Coptr"}},
    ],
}

WORK = {
    "id": "w-gone", "title": "Gone", "iswcs": ["T-329.466.530-4"],
    "relations": [
        {"type": "composer", "artist": {"name": "Dezolent"}},
        {"type": "lyricist", "artist": {"name": "Mona Moua"}},
        {"type": "publishing", "label": {"name": "Dezolent"}},
    ],
}


def test_build_catalog_parses_release_fields():
    cat = build_catalog("a4cc", "Dezolent", releases=[RELEASE], recordings=[], works=[])
    rel = cat.releases[0]
    assert rel.mbid == "e14f83cc"
    assert rel.barcode == "886296197774"
    assert rel.date == "2013-03-05"
    assert rel.labels == [("Dezolent, LLC", "0dea", "DEZ-13-0001-W")]
    assert rel.release_group_mbid == "f2fd"
    assert rel.release_group_type == "EP"
    assert rel.has_cover_art is True
    assert [(t.position, t.title, t.recording_mbid, t.length_ms) for t in rel.tracks] == [
        (1, "Descent", "rec-descent", 200072),
        (2, "Faded Memories", "rec-faded", 258064),
    ]


def test_build_catalog_renders_multi_artist_credit_with_join_phrases():
    cat = build_catalog("a4cc", "Dezolent", releases=[], recordings=[RECORDING], works=[])
    rec = cat.recordings[0]
    assert rec.artist_credit == "Dezolent, Mona Moua, & Coptr"
    assert rec.artist_mbids == ["a4cc", "mm", "cp"]
    assert rec.isrcs == ["QT6K52600001"]
    assert rec.length_ms == 171000


def test_build_catalog_collects_work_writers_from_artist_relations_only():
    cat = build_catalog("a4cc", "Dezolent", releases=[], recordings=[], works=[WORK])
    work = cat.works[0]
    assert work.iswcs == ["T-329.466.530-4"]
    assert work.writers == ["Dezolent", "Mona Moua"]


def test_build_catalog_tolerates_missing_optional_fields():
    cat = build_catalog("a4cc", "Dezolent", releases=[{"id": "x", "title": "Bare"}], recordings=[{"id": "r", "title": "Bare"}], works=[{"id": "w", "title": "Bare"}])
    assert cat.releases[0].barcode == "" and cat.releases[0].tracks == [] and cat.releases[0].has_cover_art is False
    assert cat.recordings[0].isrcs == [] and cat.recordings[0].length_ms is None
    assert cat.works[0].iswcs == [] and cat.works[0].writers == []


def test_choose_artist_prefers_exact_name_over_higher_score():
    candidates = [
        {"id": "other", "name": "Dezolent Tribute Band", "score": 100},
        {"id": "a4cc", "name": "Dezolent", "score": 98},
    ]
    assert choose_artist(candidates, "Dezolent")["id"] == "a4cc"


def test_choose_artist_returns_none_when_no_name_match():
    assert choose_artist([{"id": "x", "name": "Someone Else", "score": 100}], "Dezolent") is None


def test_build_catalog_indexes_every_credited_artist_mbid_by_name():
    cat = build_catalog("a4cc", "Dezolent", releases=[RELEASE], recordings=[RECORDING], works=[])
    assert cat.artist_index == {"dezolent": "a4cc", "monamoua": "mm", "coptr": "cp"}

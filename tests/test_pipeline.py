"""End-to-end plan building against a catalog snapshot (no network)."""

from collections import OrderedDict

from musicbrainz_importer.client import MusicBrainzClient
from musicbrainz_importer.models import ArtistCatalog, MBRecording, MBRelease, MBTrack, MBWork
from musicbrainz_importer.pipeline import build_release_plans


def _row(**kw):
    base = {
        "Artist": "Dezolent", "Title": "Gone", "ISRC": "GBKQU1591272", "UPC": "`085494590619", "ISWC": "T3294665304",
        "Catalog Number": "DEZ-14-0002-W", "Release Artist": "Dezolent", "Release": "Gone", "Release Label": "Dezolent, LLC",
        "Release Date": "9/24/14", "Year": "2024", "Duration": "4:18", "Writer/Composer 1": "Joseph Christian Hill",
        "Discogs": "https://www.discogs.com/release/35303032-Gone", "Amazon ASIN": "", "__row_number__": "9",
    }
    base.update(kw)
    return base


CATALOG = ArtistCatalog(
    artist_mbid="a4cc", artist_name="Dezolent",
    releases=[MBRelease(
        mbid="rel-gone", title="Gone", artist_credit="Dezolent", barcode="085494590619", date="2014-09-20", country="XW",
        status="Official", labels=[("Dezolent, LLC", "lab-1", "DEZ-14-0002-W")], release_group_mbid="rg-gone",
        release_group_type="Single", tracks=[MBTrack(1, "Gone", "rec-gone", 258000)], has_cover_art=True,
    )],
    recordings=[MBRecording(mbid="rec-gone", title="Gone", artist_credit="Dezolent feat. Mona Moua", artist_mbids=["a4cc"],
                            isrcs=["GBKQU1591272"], length_ms=258000, first_release_date="2014-09-20")],
    works=[MBWork(mbid="w-gone", title="Gone", iswcs=["T-329.466.530-4"], writers=["Dezolent", "Mona Moua"])],
)


def _plans(rows, catalog=CATALOG):
    grouped = OrderedDict()
    for row in rows:
        key = (row["Release Artist"], row["Release"], row["UPC"], row["Catalog Number"], row["Release Label"], row["Release Date"])
        grouped.setdefault(key, []).append(row)
    mb = MusicBrainzClient(user_agent="t/1 (t@example.com)", enabled=False)
    return build_release_plans(
        grouped_rows=grouped, mb=mb, catalog=catalog, lookup_limit=5, status="official",
        medium_format="Digital Media", multi_track_primary_type="EP", artist_filter="Dezolent",
    )


def test_pipeline_matches_release_recording_and_work_from_snapshot():
    plan = _plans([_row()])[0]
    assert plan.release_hit.mbid == "rel-gone" and plan.release_hit.confidence == "exact"
    assert plan.release_group_hit.mbid == "rg-gone" and plan.release_group_hit.confidence == "exact"
    assert plan.artist_hit.mbid == "a4cc"
    assert plan.tracks[0].existing_recording.mbid == "rec-gone"
    assert plan.tracks[0].existing_work.mbid == "w-gone"


def test_pipeline_derives_label_from_matched_release_without_searching():
    plan = _plans([_row()])[0]
    assert plan.label_hit is not None and plan.label_hit.mbid == "lab-1"


def test_pipeline_collects_discrepancies_and_cover_art():
    plan = _plans([_row()])[0]
    fields = {d.field for d in plan.discrepancies}
    assert {"release_date", "year"} <= fields
    assert plan.cover_art_url.endswith("/release/rel-gone/front-250")


def test_pipeline_builds_external_links_from_csv_columns():
    plan = _plans([_row(**{"Amazon ASIN": "B0FSC81QLH"})])[0]
    urls = {l.url for l in plan.external_links}
    assert "https://www.discogs.com/release/35303032-Gone" in urls
    assert "https://www.amazon.com/dp/B0FSC81QLH" in urls


def test_pipeline_leaves_hits_empty_when_nothing_matches_and_lookups_disabled():
    plan = _plans([_row(Title="Unknown Song", ISRC="ZZ", UPC="", ISWC="", Release="Unknown Song", **{"Catalog Number": "X"})])[0]
    assert plan.release_hit is None and plan.tracks[0].existing_recording is None and plan.tracks[0].existing_work is None
    assert {"upc"} <= {d.field for d in plan.discrepancies}


def test_pipeline_single_track_release_is_typed_single_and_multi_uses_flag():
    plans = _plans([
        _row(),
        _row(Title="A", Release="Two", UPC="1", **{"Catalog Number": "C2"}, ISRC="AA", ISWC=""),
        _row(Title="B", Release="Two", UPC="1", **{"Catalog Number": "C2"}, ISRC="BB", ISWC=""),
    ])
    assert plans[0].primary_type == "Single"
    assert plans[1].primary_type == "EP" and len(plans[1].tracks) == 2


class _RecordingClient(MusicBrainzClient):
    """Counts ws/2 searches without touching the network."""

    def __init__(self):
        super().__init__(user_agent="t/1 (t@example.com)", enabled=True)
        self.queries = []

    def search(self, entity, query, limit=5):
        self.queries.append((entity, query))
        if entity == "release":
            return [{"id": "wrong-1", "title": "It's Dezolent", "score": 100, "artist-credit": [{"name": "Dezolent"}]}]
        if entity == "label":
            return [{"id": "lab-1", "name": "Dezolent, LLC", "score": 100}]
        return []


def _plans_with(mb, rows, catalog=CATALOG, search_fallback=False):
    grouped = OrderedDict()
    for row in rows:
        key = (row["Release Artist"], row["Release"], row["UPC"], row["Catalog Number"], row["Release Label"], row["Release Date"])
        grouped.setdefault(key, []).append(row)
    return build_release_plans(
        grouped_rows=grouped, mb=mb, catalog=catalog, lookup_limit=5, status="official",
        medium_format="Digital Media", multi_track_primary_type="EP", artist_filter="Dezolent", search_fallback=search_fallback,
    )


def test_snapshot_is_authoritative_so_unmatched_items_do_not_trigger_entity_searches():
    mb = _RecordingClient()
    plan = _plans_with(mb, [_row(Title="Dezolent", Release="Dezolent", UPC="999", ISRC="NEW1", ISWC="", **{"Catalog Number": "DEZ-26-0002-W"})])[0]
    assert plan.release_hit is None and plan.release_group_hit is None
    assert plan.tracks[0].existing_recording is None and plan.tracks[0].existing_work is None
    searched = {entity for entity, _ in mb.queries}
    assert searched <= {"label"}  # only labels are not covered by the snapshot


def test_search_fallback_when_enabled_rejects_hits_whose_title_differs():
    mb = _RecordingClient()
    plan = _plans_with(mb, [_row(Title="Dezolent", Release="Dezolent", UPC="", ISRC="NEW1", ISWC="", **{"Catalog Number": "DEZ-26-0002-W"})],
                       search_fallback=True)[0]
    assert plan.release_hit is None  # "It's Dezolent" is not "Dezolent"
    assert any(entity == "release" for entity, _ in mb.queries)


def test_search_fallback_is_used_when_no_snapshot_exists():
    mb = _RecordingClient()
    plan = _plans_with(mb, [_row(Release="It's Dezolent", Title="It's Dezolent")], catalog=None)[0]
    assert plan.release_hit is not None and plan.release_hit.mbid == "wrong-1" and plan.release_hit.confidence == "search"


def test_pipeline_stops_searching_after_repeated_musicbrainz_failures():
    class FailingClient(_RecordingClient):
        def search(self, entity, query, limit=5):
            self.queries.append((entity, query))
            self.consecutive_failures = 3
            return []
    mb = FailingClient()
    rows = [_row(Title=f"T{i}", Release=f"R{i}", UPC=str(i), ISRC=f"I{i}", ISWC="", **{"Catalog Number": f"C{i}", "Release Label": f"Label {i}"}) for i in range(5)]
    _plans_with(mb, rows, catalog=None)
    assert len(mb.queries) <= 2

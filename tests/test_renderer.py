"""Dashboard payload and HTML rendering."""

import json
from pathlib import Path

from musicbrainz_importer.models import Discrepancy, LookupHit, ReleasePlan, TrackPlan
from musicbrainz_importer.renderer import build_dashboard_payload, render_html_dashboard


def _plan(title="Gone", release_hit=True, rec_hit=True, work_hit=False, discrepancies=()):
    hit = LookupHit(mbid="rel-1", name=title, score=100, url="https://musicbrainz.org/release/rel-1", confidence="exact", method="barcode",
                    extra={"release_group_mbid": "rg-1"})
    track = TrackPlan(title=title, artist="Dezolent & Coptr", duration_raw="4:18", duration_mmss="4:18", duration_ms=258000,
                      isrc="GBKQU1591272", iswc="", writer_composers=["Joseph Christian Hill"], source_row_number=9,
                      existing_recording=LookupHit("rec-1", title, 100, "u", confidence="exact", method="isrc") if rec_hit else None,
                      existing_work=LookupHit("w-1", title, 100, "u", confidence="strong", method="title") if work_hit else None)
    plan = ReleasePlan(
        title=title, release_artist="Dezolent", release_label="Dezolent, LLC", release_date_raw="9/24/14", release_date_iso="2014-09-24",
        year="2014", upc="085494590619", catalog_number="DEZ-14-0002-W", status="official", primary_type="Single",
        medium_format="Digital Media", artist_hit=None, label_hit=None, release_hit=hit if release_hit else None,
        release_group_hit=None, tracks=[track],
    )
    plan.discrepancies.extend(discrepancies)
    return plan


def _payload(plans):
    return build_dashboard_payload(
        plans, csv_path=Path("songs.csv"), artist_name="Dezolent", artist_mbid="a4cc",
        release_country="XW", language="eng", script="Latn", edit_note="note", sources_used=["spotify"],
    )


def test_payload_has_summary_counts():
    payload = _payload([_plan(), _plan(title="Other", release_hit=False, rec_hit=False, discrepancies=[Discrepancy("upc", "", "", "warn")])])
    s = payload["summary"]
    assert s["releases"] == 2 and s["releases_matched"] == 1
    assert s["tracks"] == 2 and s["recordings_matched"] == 1 and s["works_matched"] == 0
    assert s["warnings"] == 1
    assert payload["artist"] == {"name": "Dezolent", "mbid": "a4cc", "url": "https://musicbrainz.org/artist/a4cc"}


def test_payload_release_entries_carry_seed_fields_flags_and_links():
    release = _payload([_plan(work_hit=True)])["releases"][0]
    assert release["key"]  # stable id for local "done" state
    assert ("name", "Gone") in [tuple(f) for f in release["seed_fields"]]
    assert release["flags"]["collaboration"] is True
    assert release["flags"]["missing_iswc"] is True and release["flags"]["missing_isrc"] is False
    assert release["flags"]["unmatched_work"] is False and release["flags"]["fuzzy"] is False
    assert release["search_urls"]["release"].startswith("https://musicbrainz.org/search?")
    assert release["tracks"][0]["search_urls"]["recording"].startswith("https://musicbrainz.org/search?")
    assert release["tracks"][0]["create_urls"]["work"].startswith("https://musicbrainz.org/work/create")


def test_payload_carries_website_fields():
    plan = _plan()
    plan.site_url = "https://dezolent.com/tracks/gone"
    plan.site_cover_url = "https://dezolent.com/images/covers/gone.webp"
    release = _payload([plan])["releases"][0]
    assert release["site_url"] == "https://dezolent.com/tracks/gone"
    assert release["site_cover_url"].endswith("gone.webp")


def test_payload_is_json_serialisable():
    json.dumps(_payload([_plan()]))


def test_html_embeds_payload_and_assets_inline():
    html = render_html_dashboard(_payload([_plan()]))
    assert html.startswith("<!doctype html>")
    assert '<script id="dashboard-data" type="application/json">' in html
    for slot in ("TITLE", "STYLES", "SCRIPT", "DATA"):
        assert "{{" + slot + "}}" not in html  # every template slot filled
    assert "<link rel=\"stylesheet\" href=" not in html  # CSS is inlined
    assert "</script>" in html and "GBKQU1591272" in html


def test_html_escapes_script_terminator_inside_json():
    plan = _plan(title="Sneaky </script><b>x")
    html = render_html_dashboard(_payload([plan]))
    assert "</script><b>x" not in html

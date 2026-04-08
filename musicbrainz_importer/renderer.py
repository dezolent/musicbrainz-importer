"""
HTML dashboard and JSON sidecar rendering.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .constants import MB_BASE
from .models import LookupHit, ReleasePlan
from .utils import (
    build_work_queries,
    clean_value,
    html_escape,
    mb_create_artist_url,
    mb_create_label_url,
    mb_create_work_url,
    mb_search_url,
    normalize_text,
    parse_release_date,
    slugify,
)


# ---------------------------------------------------------------------------
# Release seeding field builder
# ---------------------------------------------------------------------------

def build_release_form_fields(
        plan: ReleasePlan,
        release_country: str,
        language: str,
        script: str,
        edit_note: str,
) -> List[Tuple[str, str]]:
    _, date_parts = parse_release_date(plan.release_date_raw)

    fields: List[Tuple[str, str]] = [
        ("name", plan.title),
        ("status", plan.status),
        ("edit_note", edit_note.strip()),
    ]

    if plan.primary_type:
        fields.append(("type", plan.primary_type))
    if plan.upc:
        fields.append(("barcode", plan.upc))
    if language:
        fields.append(("language", language))
    if script:
        fields.append(("script", script))

    if date_parts["year"]:
        fields.append(("events.0.date.year", date_parts["year"]))
    if date_parts["month"]:
        fields.append(("events.0.date.month", date_parts["month"]))
    if date_parts["day"]:
        fields.append(("events.0.date.day", date_parts["day"]))
    if release_country:
        fields.append(("events.0.country", release_country))

    if plan.label_hit:
        fields.append(("labels.0.mbid", plan.label_hit.mbid))
    elif plan.release_label:
        fields.append(("labels.0.name", plan.release_label))
    if plan.catalog_number:
        fields.append(("labels.0.catalog_number", plan.catalog_number))

    if plan.artist_hit:
        fields.append(("artist_credit.names.0.mbid", plan.artist_hit.mbid))
        fields.append(("artist_credit.names.0.name", plan.release_artist))
    elif plan.release_artist:
        fields.append(("artist_credit.names.0.artist.name", plan.release_artist))
        fields.append(("artist_credit.names.0.name", plan.release_artist))

    fields.append(("mediums.0.format", plan.medium_format))
    for idx, track in enumerate(plan.tracks):
        fields.append((f"mediums.0.track.{idx}.number", str(idx + 1)))
        fields.append((f"mediums.0.track.{idx}.name", track.title))
        if track.duration_mmss:
            fields.append((f"mediums.0.track.{idx}.length", track.duration_mmss))
        if normalize_text(track.artist) != normalize_text(plan.release_artist):
            fields.append((f"mediums.0.track.{idx}.artist_credit.names.0.artist.name", track.artist))
            fields.append((f"mediums.0.track.{idx}.artist_credit.names.0.name", track.artist))

    return [(name, clean_value(value)) for name, value in fields if clean_value(value)]


def _render_hidden_inputs(fields: List[Tuple[str, str]]) -> str:
    return "\n".join(
        f'<input type="hidden" name="{html_escape(name)}" value="{html_escape(value)}">'
        for name, value in fields
    )


# ---------------------------------------------------------------------------
# HTML component renderers
# ---------------------------------------------------------------------------

def _render_lookup_badge(
        hit: Optional[LookupHit],
        entity_label: str,
        search_url: str,
        create_url: str = "",
) -> str:
    if hit:
        return (
            f'<span class="hit ok">Found {html_escape(entity_label)}: '
            f'<a href="{html_escape(hit.url)}" target="_blank" rel="noreferrer">{html_escape(hit.name)}</a> '
            f'<small>(score {hit.score})</small></span>'
        )
    links = [f'<a href="{html_escape(search_url)}" target="_blank" rel="noreferrer">search</a>']
    if create_url:
        links.append(f'<a href="{html_escape(create_url)}" target="_blank" rel="noreferrer">create</a>')
    return f'<span class="hit warn">No match for {html_escape(entity_label)} ({" | ".join(links)})</span>'


def _render_release_section(
        plan: ReleasePlan,
        release_country: str,
        language: str,
        script: str,
        edit_note: str,
) -> str:
    section_id = slugify(f"{plan.release_artist}-{plan.title}-{plan.catalog_number}")
    form_fields = build_release_form_fields(plan, release_country, language, script, edit_note)
    hidden_inputs = _render_hidden_inputs(form_fields)

    artist_search = mb_search_url(f'artist:"{plan.release_artist}"', "artist")
    label_search = mb_search_url(f'label:"{plan.release_label}"', "label")
    release_search = mb_search_url(f'release:"{plan.title}" AND artist:"{plan.release_artist}"', "release")
    rg_search = mb_search_url(f'releasegroup:"{plan.title}" AND artist:"{plan.release_artist}"', "release-group")

    track_rows: List[str] = []
    for idx, track in enumerate(plan.tracks, start=1):
        recording_search = mb_search_url(f'recording:"{track.title}" AND artist:"{track.artist}"', "recording")
        work_queries = build_work_queries(track.title, track.writer_composers, track.iswc)
        work_search = mb_search_url(work_queries[0], "work")
        work_create = mb_create_work_url(track.title)

        track_rows.append(f"""
            <tr>
              <td>{idx}</td>
              <td>
                <strong>{html_escape(track.title)}</strong><br>
                <small>Artist: {html_escape(track.artist)}</small>
              </td>
              <td>{html_escape(track.duration_mmss or track.duration_raw)}</td>
              <td>{html_escape(track.isrc)}</td>
              <td>{html_escape(track.iswc)}</td>
              <td>{html_escape(', '.join(track.writer_composers))}</td>
              <td>{_render_lookup_badge(track.existing_recording, 'recording', recording_search)}</td>
              <td>{_render_lookup_badge(track.existing_work, 'work', work_search, work_create)}</td>
              <td>{track.source_row_number}</td>
            </tr>""".strip())

    mb_release_link = ""
    if plan.release_hit:
        mb_release_link = (
            f' <a class="mb-link" href="{html_escape(plan.release_hit.url)}" target="_blank" rel="noreferrer">'
            f'&#9654; Open on MusicBrainz</a>'
        )

    return f"""
    <section id="{html_escape(section_id)}" class="release-card">
      <div class="release-head">
        <div>
          <h2>{html_escape(plan.title)}{mb_release_link}</h2>
          <div class="meta">
            <span><strong>Artist</strong> {html_escape(plan.release_artist)}</span>
            <span><strong>Date</strong> {html_escape(plan.release_date_iso or plan.release_date_raw)}</span>
            <span><strong>Tracks</strong> {len(plan.tracks)}</span>
            {'<span><strong>UPC</strong> ' + html_escape(plan.upc) + '</span>' if plan.upc else ''}
            {'<span><strong>Cat#</strong> ' + html_escape(plan.catalog_number) + '</span>' if plan.catalog_number else ''}
            {'<span><strong>Type</strong> ' + html_escape(plan.primary_type) + '</span>' if plan.primary_type else ''}
          </div>
        </div>
        <form action="{MB_BASE}/release/add" method="post" enctype="multipart/form-data" target="_blank" class="seed-form">
          {hidden_inputs}
          <button type="submit">&#43; Seed release editor</button>
        </form>
      </div>

      <hr class="section-divider">

      <div class="lookup-grid">
        {_render_lookup_badge(plan.artist_hit, 'Artist', artist_search, mb_create_artist_url(plan.release_artist))}
        {_render_lookup_badge(plan.label_hit, 'Label', label_search, mb_create_label_url(plan.release_label))}
        {_render_lookup_badge(plan.release_group_hit, 'Release Group', rg_search)}
        {_render_lookup_badge(plan.release_hit, 'Release', release_search)}
      </div>

      <details>
        <summary>&#9654; Seeding fields (debug)</summary>
        <pre>{html_escape(json.dumps(form_fields, indent=2))}</pre>
      </details>

      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Track</th>
            <th>Length</th>
            <th>ISRC</th>
            <th>ISWC</th>
            <th>Writer(s)</th>
            <th>Recording</th>
            <th>Work</th>
            <th>Row</th>
          </tr>
        </thead>
        <tbody>
          {' '.join(track_rows)}
        </tbody>
      </table>
    </section>
    """.strip()


_CSS = """
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    *, *::before, *::after { box-sizing: border-box; }

    :root {
      --bg:        #0d0f17;
      --surface:   #13161f;
      --surface2:  #1a1d2b;
      --border:    #252836;
      --border2:   #2e3147;
      --text:      #e2e4f0;
      --text-muted:#8b8fa8;
      --accent:    #7c6af7;
      --accent2:   #a78bfa;
      --ok-bg:     #0d2218;
      --ok-border: #1a5c38;
      --ok-text:   #4ade80;
      --warn-bg:   #1f1708;
      --warn-border:#7a5a00;
      --warn-text: #fbbf24;
      --link:      #818cf8;
    }

    body {
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      margin: 0;
      padding: 28px 32px;
      color: var(--text);
      background: var(--bg);
      min-height: 100vh;
      font-size: 14px;
      line-height: 1.6;
    }

    h1 {
      margin: 0 0 4px;
      font-size: 1.75rem;
      font-weight: 700;
      background: linear-gradient(135deg, var(--accent2) 0%, #c4b5fd 60%, #818cf8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      letter-spacing: -0.02em;
    }

    h2 {
      margin: 0 0 6px;
      font-size: 1.15rem;
      font-weight: 600;
      color: var(--text);
      letter-spacing: -0.01em;
    }

    .top {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 24px 28px;
      margin-bottom: 28px;
      box-shadow: 0 0 0 1px rgba(124,106,247,.08), 0 8px 32px rgba(0,0,0,.4);
    }

    .top-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
    }

    .logo-icon {
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, var(--accent), #c4b5fd);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      flex-shrink: 0;
    }

    .stats-row {
      display: flex;
      gap: 20px;
      flex-wrap: wrap;
      margin: 14px 0 10px;
    }

    .stat {
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 16px;
      font-size: 13px;
    }

    .stat strong {
      display: block;
      font-size: 1.4rem;
      font-weight: 700;
      color: var(--accent2);
      line-height: 1.2;
    }

    .note {
      color: var(--text-muted);
      line-height: 1.6;
      font-size: 13px;
      margin-top: 10px;
    }

    .note strong { color: var(--text); }

    .release-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 22px 24px;
      margin-bottom: 20px;
      box-shadow: 0 4px 24px rgba(0,0,0,.35);
      transition: border-color .15s;
    }

    .release-card:hover { border-color: var(--border2); }

    .release-head {
      display: flex;
      gap: 16px;
      justify-content: space-between;
      align-items: flex-start;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }

    .meta {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }

    .meta span {
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 3px 10px;
      font-size: 12px;
      color: var(--text-muted);
    }

    .meta span strong { color: var(--text); font-weight: 500; }

    .seed-form button {
      border: 0;
      background: linear-gradient(135deg, #6d5af0 0%, #9f7aea 100%);
      color: white;
      padding: 11px 20px;
      border-radius: 10px;
      cursor: pointer;
      font-weight: 600;
      font-size: 13px;
      letter-spacing: .01em;
      box-shadow: 0 2px 12px rgba(124,106,247,.4);
      transition: opacity .15s, box-shadow .15s;
      white-space: nowrap;
    }

    .seed-form button:hover {
      opacity: .9;
      box-shadow: 0 4px 20px rgba(124,106,247,.55);
    }

    .lookup-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 10px;
      margin: 0 0 16px;
    }

    .hit {
      display: block;
      padding: 10px 14px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--surface2);
      font-size: 13px;
      line-height: 1.45;
    }

    .hit.ok {
      background: var(--ok-bg);
      border-color: var(--ok-border);
      color: var(--ok-text);
    }

    .hit.warn {
      background: var(--warn-bg);
      border-color: var(--warn-border);
      color: var(--warn-text);
    }

    .hit small { opacity: .7; font-size: 11px; }

    a { color: var(--link); text-decoration: none; }
    a:hover { text-decoration: underline; color: var(--accent2); }

    details { margin: 14px 0 0; }

    summary {
      cursor: pointer;
      font-size: 12px;
      color: var(--text-muted);
      user-select: none;
      padding: 6px 0;
    }

    summary:hover { color: var(--text); }

    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: #090b12;
      color: #a5b4fc;
      padding: 14px 16px;
      border-radius: 10px;
      overflow: auto;
      font-size: 12px;
      border: 1px solid var(--border);
      margin-top: 8px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 16px;
      font-size: 13px;
    }

    th, td {
      text-align: left;
      vertical-align: top;
      padding: 9px 10px;
      border-top: 1px solid var(--border);
    }

    th {
      background: var(--surface2);
      color: var(--text-muted);
      font-weight: 500;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .06em;
    }

    tr:hover td { background: rgba(255,255,255,.02); }

    td strong { color: var(--text); font-weight: 500; }
    td small { color: var(--text-muted); }

    code {
      background: rgba(124,106,247,.15);
      color: var(--accent2);
      padding: 2px 7px;
      border-radius: 5px;
      font-size: 12px;
    }

    .mb-link {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 12px;
      color: var(--link);
      background: rgba(129,140,248,.1);
      border: 1px solid rgba(129,140,248,.25);
      border-radius: 6px;
      padding: 2px 8px;
    }

    .mb-link:hover { background: rgba(129,140,248,.2); text-decoration: none; }

    .section-divider {
      border: none;
      border-top: 1px solid var(--border);
      margin: 4px 0 16px;
    }
"""


# ---------------------------------------------------------------------------
# Top-level output functions
# ---------------------------------------------------------------------------

def render_html_dashboard(
        plans: List[ReleasePlan],
        csv_path: Path,
        release_country: str,
        language: str,
        script: str,
        edit_note: str,
) -> str:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    total_tracks = sum(len(plan.tracks) for plan in plans)
    body = "\n\n".join(
        _render_release_section(plan, release_country, language, script, edit_note)
        for plan in plans
    )

    found_count = sum(1 for p in plans if p.release_hit)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MusicBrainz Seeding Dashboard</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="top">
    <div class="top-header">
      <div class="logo-icon">🎵</div>
      <h1>MusicBrainz Seeding Dashboard</h1>
    </div>

    <div class="stats-row">
      <div class="stat"><strong>{len(plans)}</strong>Releases</div>
      <div class="stat"><strong>{total_tracks}</strong>Tracks</div>
      <div class="stat"><strong>{found_count}</strong>Matched</div>
      <div class="stat"><strong>{len(plans) - found_count}</strong>Unmatched</div>
    </div>

    <p class="note">
      Generated from <code>{html_escape(str(csv_path))}</code> &mdash; {html_escape(generated_at)}<br>
      Country: <strong>{html_escape(release_country or '—')}</strong> &nbsp;
      Language: <strong>{html_escape(language or '—')}</strong> &nbsp;
      Script: <strong>{html_escape(script or '—')}</strong>
    </p>
    <p class="note">
      Click <strong>Seed release editor</strong> to open the MusicBrainz release editor pre-filled with this release's data.
      Works and relationships still require manual linking after the release is created.
    </p>
  </div>

  {body}
</body>
</html>
"""


def write_json_sidecar(plans: List[ReleasePlan], output_path: Path) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "releases": [asdict(plan) for plan in plans],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

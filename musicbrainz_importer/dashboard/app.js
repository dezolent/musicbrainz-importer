(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("dashboard-data").textContent);
  var MB = "https://musicbrainz.org";
  var STORE = "mbi:done:v1";

  // ------------------------------------------------------------------ utils
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function el(html) {
    var t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function pct(a, b) { return b ? Math.round((a / b) * 100) : 0; }
  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }
  function loadDone() {
    try { return JSON.parse(localStorage.getItem(STORE) || "{}"); } catch (e) { return {}; }
  }
  function saveDone(map) {
    try { localStorage.setItem(STORE, JSON.stringify(map)); } catch (e) { /* private mode */ }
  }
  function confClass(hit) {
    if (!hit) return "bad";
    return hit.confidence === "exact" || hit.confidence === "strong" ? "ok" : "fuzzy";
  }
  function hitLink(hit, fallbackText) {
    if (!hit) return '<span class="none">' + esc(fallbackText || "Not found") + "</span>";
    return '<a href="' + esc(hit.url) + '" target="_blank" rel="noreferrer" title="' + esc(hit.mbid) + '">' + esc(hit.name) + "</a>" +
      '<span class="conf ' + esc(hit.confidence) + '" title="Matched by ' + esc(hit.method) + '">' + esc(hit.confidence) + "</span>";
  }
  var CHEV = '<svg class="chev" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M5 8l5 5 5-5"/></svg>';
  var SEARCH_ICON = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="9" cy="9" r="6"/><path d="M14 14l4 4"/></svg>';

  var done = loadDone();
  var state = { query: "", filters: new Set(), sort: "date-desc" };
  var releases = DATA.releases.slice();

  // ------------------------------------------------------------------ derived status
  function recStatus(r) {
    var m = r.counts.recordings_matched, n = r.counts.tracks;
    return m === n ? "ok" : m > 0 ? "partial" : "bad";
  }
  function workStatus(r) {
    var m = r.counts.works_matched, n = r.counts.tracks;
    return m === n ? "ok" : m > 0 ? "partial" : "bad";
  }
  function reviewStatus(r) {
    return r.counts.warnings > 0 ? "bad" : r.counts.infos > 0 ? "info" : "ok";
  }
  function isDone(r) { return !!done[r.key]; }

  var FILTERS = [
    { id: "unmatched_release", label: "No release", test: function (r) { return r.flags.unmatched_release; } },
    { id: "unmatched_recording", label: "Recordings missing", test: function (r) { return r.flags.unmatched_recording; } },
    { id: "unmatched_work", label: "Works missing", test: function (r) { return r.flags.unmatched_work; } },
    { id: "warnings", label: "Needs review", test: function (r) { return r.flags.warnings; } },
    { id: "fuzzy", label: "Low confidence", test: function (r) { return r.flags.fuzzy; } },
    { id: "missing_upc", label: "No UPC", test: function (r) { return r.flags.missing_upc; } },
    { id: "missing_isrc", label: "No ISRC", test: function (r) { return r.flags.missing_isrc; } },
    { id: "missing_iswc", label: "No ISWC", test: function (r) { return r.flags.missing_iswc; } },
    { id: "collaboration", label: "Collaborations", test: function (r) { return r.flags.collaboration; } },
    { id: "no_cover", label: "No cover art", test: function (r) { return !!r.hits.release && !r.cover_art_url; } },
    { id: "open", label: "Open", test: function (r) { return !isDone(r); } },
    { id: "done", label: "Done", test: function (r) { return isDone(r); } }
  ];

  var SORTS = {
    "date-desc": function (a, b) { return (b.release_date_iso || "").localeCompare(a.release_date_iso || ""); },
    "date-asc": function (a, b) { return (a.release_date_iso || "").localeCompare(b.release_date_iso || ""); },
    "title": function (a, b) { return a.title.localeCompare(b.title); },
    "issues": function (a, b) { return (b.counts.warnings - a.counts.warnings) || (b.counts.infos - a.counts.infos); },
    "unmatched": function (a, b) {
      var score = function (r) { return (r.flags.unmatched_release ? 4 : 0) + (r.flags.unmatched_recording ? 2 : 0) + (r.flags.unmatched_work ? 1 : 0); };
      return score(b) - score(a);
    }
  };

  function matchesQuery(r, q) {
    if (!q) return true;
    var hay = [r.title, r.release_artist, r.release_label, r.upc, r.catalog_number, r.release_date_iso]
      .concat(r.tracks.map(function (t) { return t.title + " " + t.isrc + " " + t.iswc + " " + t.artist; }))
      .join(" ").toLowerCase();
    return q.split(/\s+/).every(function (term) { return hay.indexOf(term) !== -1; });
  }
  function visible(r) {
    if (!matchesQuery(r, state.query.trim().toLowerCase())) return false;
    var ok = true;
    state.filters.forEach(function (id) {
      var f = FILTERS.filter(function (x) { return x.id === id; })[0];
      if (f && !f.test(r)) ok = false;
    });
    return ok;
  }

  // ------------------------------------------------------------------ masthead
  function renderMasthead() {
    var a = DATA.artist || {};
    var p = DATA.params || {};
    var sources = (p.sources_used || []).map(function (s) { return { spotify: "Spotify", itunes: "Apple Music", discogs: "Discogs", website: "Artist website" }[s] || s; });
    $("#masthead").innerHTML =
      '<div class="masthead-inner">' +
        '<div class="brand"><div class="brand-mark" aria-hidden="true">MB</div>' +
          '<div><h1>MusicBrainz seeding dashboard</h1>' +
          '<div class="sub">' + (a.url ? '<a href="' + esc(a.url) + '" target="_blank" rel="noreferrer">' + esc(a.name) + "</a>" : esc(a.name || "Catalog")) +
          " · " + esc(DATA.source_csv) + "</div></div></div>" +
        '<div class="masthead-meta">' +
          "<span>Generated <b>" + esc((DATA.generated_at || "").replace("T", " ").replace(/\.\d+Z$/, "Z")) + "</b></span>" +
          "<span>Country <b>" + esc(p.release_country || "—") + "</b></span>" +
          "<span>Language <b>" + esc(p.language || "—") + "</b> · Script <b>" + esc(p.script || "—") + "</b></span>" +
          "<span>Sources <b>" + esc(["MusicBrainz"].concat(sources).join(", ")) + "</b></span>" +
          (p.lookups_enabled ? "" : "<span><b>Offline run</b> — no lookups performed</span>") +
        "</div>" +
      "</div>";
  }

  // ------------------------------------------------------------------ KPIs
  function renderKpis() {
    var s = DATA.summary;
    var doneCount = releases.filter(isDone).length;
    function kpi(label, value, total, hint, warnish) {
      return '<div class="kpi' + (warnish ? " warnish" : "") + '"><div class="label">' + esc(label) + "</div>" +
        '<div class="value">' + esc(value) + (total != null ? "<small>/ " + esc(total) + "</small>" : "") + "</div>" +
        (total != null ? '<div class="bar"><i style="width:' + pct(value, total) + '%"></i></div>' : '<div class="hint">' + esc(hint || "") + "</div>") +
        "</div>";
    }
    $("#kpis").innerHTML =
      kpi("Releases in MusicBrainz", s.releases_matched, s.releases) +
      kpi("Recordings in MusicBrainz", s.recordings_matched, s.tracks) +
      kpi("Works in MusicBrainz", s.works_matched, s.tracks) +
      kpi("Warnings to review", s.warnings, null, plural(s.infos, "informational note"), s.warnings > 0) +
      kpi("Low-confidence matches", s.fuzzy, null, s.fuzzy ? "Verify before seeding" : "All matches are exact or strong", s.fuzzy > 0) +
      kpi("Marked done", doneCount, s.releases);
  }

  // ------------------------------------------------------------------ coverage matrix
  var COLS = [
    { key: "artist", label: "Artist", cell: function (r) { return { cls: r.hits.artist ? confClass(r.hits.artist) : "bad", text: "" }; } },
    { key: "label", label: "Label", cell: function (r) { return r.release_label ? { cls: r.hits.label ? confClass(r.hits.label) : "bad", text: "" } : { cls: "na", text: "" }; } },
    { key: "release_group", label: "Group", cell: function (r) { return { cls: r.hits.release_group ? confClass(r.hits.release_group) : "bad", text: "" }; } },
    { key: "release", label: "Release", cell: function (r) { return { cls: r.hits.release ? confClass(r.hits.release) : "bad", text: "" }; } },
    { key: "recordings", label: "Recordings", cell: function (r) { return { cls: recStatus(r), text: r.counts.recordings_matched + "/" + r.counts.tracks }; } },
    { key: "works", label: "Works", cell: function (r) { return { cls: workStatus(r), text: r.counts.works_matched + "/" + r.counts.tracks }; } },
    { key: "links", label: "Links", cell: function (r) { return r.counts.links ? { cls: "info", text: String(r.counts.links) } : { cls: "na", text: "" }; } },
    { key: "review", label: "Review", cell: function (r) { var st = reviewStatus(r); return { cls: st, text: st === "bad" ? String(r.counts.warnings) : st === "info" ? String(r.counts.infos) : "✓" }; } }
  ];

  function renderMatrix() {
    var rows = releases.slice().sort(SORTS["date-asc"]);
    var grid = $("#matrix");
    grid.style.setProperty("--cols", COLS.length);
    var html = '<div class="mh">Release</div>' + COLS.map(function (c) { return '<div class="mh">' + esc(c.label) + "</div>"; }).join("");
    rows.forEach(function (r) {
      html += '<div class="mrow" data-key="' + esc(r.key) + '">' +
        '<button type="button" class="mlabel' + (isDone(r) ? " done" : "") + '" data-jump="' + esc(r.key) + '" title="' + esc(r.release_artist + " – " + r.title) + '">' +
          '<span class="y">' + esc((r.release_date_iso || "").slice(0, 4) || "----") + '</span><span class="t">' + esc(r.title) + "</span></button>";
      COLS.forEach(function (c) {
        var cell = c.cell(r);
        html += '<button type="button" class="cell ' + cell.cls + '" data-jump="' + esc(r.key) + '" title="' + esc(r.title + " · " + c.label) + '" aria-label="' + esc(r.title + " " + c.label + " " + cell.cls) + '">' + esc(cell.text) + "</button>";
      });
      html += "</div>";
    });
    grid.innerHTML = html;
    $("#legend").innerHTML =
      '<span><i style="background:var(--ok-soft);box-shadow:inset 0 0 0 1px var(--ok)"></i>Found (exact or strong match)</span>' +
      '<span><i style="background:var(--fuzzy-soft);box-shadow:inset 0 0 0 1px var(--fuzzy)"></i>Low confidence — verify</span>' +
      '<span><i style="background:var(--warn-soft);box-shadow:inset 0 0 0 1px var(--warn)"></i>Partially found</span>' +
      '<span><i style="background:var(--bad-soft);box-shadow:inset 0 0 0 1px var(--bad)"></i>Missing, or warnings to review</span>' +
      '<span><i style="background:var(--info-soft)"></i>Count</span>' +
      '<span><i style="box-shadow:inset 0 0 0 1px var(--line)"></i>Not applicable</span>';
  }

  // ------------------------------------------------------------------ toolbar
  function renderToolbar() {
    var chips = FILTERS.map(function (f) {
      var n = releases.filter(f.test).length;
      return '<button type="button" class="chip" data-filter="' + f.id + '" aria-pressed="false">' + esc(f.label) + " <b>" + n + "</b></button>";
    }).join("");
    $("#toolbar").innerHTML =
      '<div class="toolbar-inner">' +
        '<div class="toolbar-row">' +
          '<label class="search"><span class="visually-hidden" hidden>Search</span>' + SEARCH_ICON +
            '<input type="search" id="q" placeholder="Search title, artist, ISRC, UPC, catalog number…" autocomplete="off"></label>' +
          '<select class="select" id="sort" aria-label="Sort releases">' +
            '<option value="date-desc">Newest first</option><option value="date-asc">Oldest first</option>' +
            '<option value="title">Title A–Z</option><option value="issues">Most warnings</option><option value="unmatched">Most missing</option>' +
          "</select>" +
          '<button type="button" class="btn" id="expand">Expand all</button>' +
          '<button type="button" class="btn" id="collapse">Collapse all</button>' +
        "</div>" +
        '<div class="toolbar-row"><div class="chips">' + chips + '</div><span class="count" id="count"></span></div>' +
      "</div>";

    $("#q").addEventListener("input", function (e) { state.query = e.target.value; applyFilters(); });
    $("#sort").addEventListener("change", function (e) { state.sort = e.target.value; sortCards(); });
    $("#expand").addEventListener("click", function () { $all(".card:not([hidden])").forEach(function (c) { c.open = true; }); });
    $("#collapse").addEventListener("click", function () { $all(".card").forEach(function (c) { c.open = false; }); });
    $all(".chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var id = chip.getAttribute("data-filter");
        if (state.filters.has(id)) state.filters.delete(id); else state.filters.add(id);
        if (id === "open" && state.filters.has("open")) state.filters.delete("done");
        if (id === "done" && state.filters.has("done")) state.filters.delete("open");
        $all(".chip").forEach(function (c) { c.setAttribute("aria-pressed", state.filters.has(c.getAttribute("data-filter")) ? "true" : "false"); });
        applyFilters();
      });
    });
  }

  function refreshChipCounts() {
    $all(".chip").forEach(function (chip) {
      var f = FILTERS.filter(function (x) { return x.id === chip.getAttribute("data-filter"); })[0];
      chip.querySelector("b").textContent = releases.filter(f.test).length;
    });
  }

  // ------------------------------------------------------------------ cards
  function entityRow(label, hit, searchUrl, createUrl, missingText) {
    var acts = [];
    if (hit) acts.push('<a href="' + esc(hit.url) + '" target="_blank" rel="noreferrer">Open</a>');
    if (searchUrl) acts.push('<a href="' + esc(searchUrl) + '" target="_blank" rel="noreferrer">Search</a>');
    if (!hit && createUrl) acts.push('<a href="' + esc(createUrl) + '" target="_blank" rel="noreferrer">Create</a>');
    return '<div class="entity"><div class="k">' + esc(label) + '</div><div class="v">' + hitLink(hit, missingText) + "</div>" +
      '<div class="acts">' + acts.join("") + "</div></div>";
  }

  function issuesList(items) {
    if (!items.length) return '<div class="empty">Nothing to review. CSV and MusicBrainz agree.</div>';
    var order = { warn: 0, info: 1 };
    items = items.slice().sort(function (a, b) { return order[a.d.severity] - order[b.d.severity]; });
    return '<ul class="issues">' + items.map(function (it) {
      var d = it.d;
      var src = d.source && d.source !== "musicbrainz" ? d.source : "musicbrainz";
      var srcLabel = { musicbrainz: "MB", csv: "CSV", spotify: "Spotify", itunes: "Apple", discogs: "Discogs", website: "Website" }[src] || src;
      var otherLabel = src === "csv" ? "Release Date" : srcLabel;
      var vals = "";
      if (d.csv_value || d.mb_value) {
        vals = '<div class="vals">' + (d.csv_value ? '<span class="csv">' + esc(d.csv_value) + "</span>" : "") +
          (d.mb_value ? '<span class="mb" data-src="' + esc(otherLabel) + '">' + esc(d.mb_value) + "</span>" : "") + "</div>";
      }
      return '<li class="' + esc(d.severity) + '"><span class="dot"></span><div><div class="msg">' +
        (it.track ? "<b>" + esc(it.track) + "</b> — " : "") + esc(d.message || d.field) +
        '<span class="src">' + esc(srcLabel) + "</span></div>" + vals + "</div></li>";
    }).join("") + "</ul>";
  }

  function linksPanel(r) {
    var chips = r.external_links.map(function (l) {
      var host = l.url.replace(/^https?:\/\/(www\.)?/, "").split("/")[0];
      return '<a class="linkchip" href="' + esc(l.url) + '" target="_blank" rel="noreferrer" title="' + esc(l.url) + '"><b>' + esc(l.label || host) + "</b>" +
        (l.link_type_id != null ? '<span class="lt">rel ' + esc(l.link_type_id) + "</span>" : "") + "</a>";
    });
    Object.keys(r.external_status || {}).forEach(function (src) {
      if (r.external_status[src] === "missing") {
        var name = { spotify: "Spotify", itunes: "Apple Music", discogs: "Discogs", website: "Artist website" }[src] || src;
        chips.push('<span class="linkchip missing">' + esc(name) + ": not found</span>");
      }
    });
    if (!chips.length) return '<div class="empty">No external links. Add a Discogs URL or Amazon ASIN to the CSV, or run with enrichment enabled.</div>';
    return '<div class="links">' + chips.join("") + "</div>";
  }

  function tracksTable(r) {
    var rows = r.tracks.map(function (t, i) {
      var flags = t.discrepancies.filter(function (d) { return d.severity === "warn"; }).length;
      var tlinks = t.external_links.map(function (l) {
        return '<a href="' + esc(l.url) + '" target="_blank" rel="noreferrer">' + esc(l.label || l.source) + "</a>";
      }).join("");
      return "<tr>" +
        '<td class="n">' + (i + 1) + "</td>" +
        "<td><div>" + esc(t.title) + (flags ? '<span class="flag" title="' + flags + ' warning(s)"></span>' : "") + "</div>" +
          (t.artist !== r.release_artist ? '<div class="sub">' + esc(t.artist) + "</div>" : "") + "</td>" +
        '<td class="mono">' + esc(t.duration_mmss || t.duration_raw || "—") + "</td>" +
        '<td class="mono">' + (t.isrc ? esc(t.isrc) : '<span class="missing">missing</span>') + "</td>" +
        '<td class="mono">' + (t.iswc ? esc(t.iswc) : '<span class="missing">missing</span>') + "</td>" +
        '<td class="sub">' + esc(t.writer_composers.join(", ")) + "</td>" +
        '<td><div class="status">' + hitLink(t.recording, "Not found") +
          '<span class="tlinks"><a href="' + esc(t.search_urls.recording) + '" target="_blank" rel="noreferrer">Search</a></span></div></td>' +
        '<td><div class="status">' + hitLink(t.work, "Not found") +
          '<span class="tlinks"><a href="' + esc(t.search_urls.work) + '" target="_blank" rel="noreferrer">Search</a>' +
          (t.work ? "" : '<a href="' + esc(t.create_urls.work) + '" target="_blank" rel="noreferrer">Create</a>') + "</span></div></td>" +
        '<td><div class="tlinks">' + (tlinks || '<span class="sub">—</span>') + "</div></td>" +
        '<td class="n" title="CSV row">' + esc(t.source_row_number) + "</td>" +
        "</tr>";
    }).join("");
    return '<div class="table-wrap"><table class="tracks"><thead><tr>' +
      "<th>#</th><th>Track</th><th>Length</th><th>ISRC</th><th>ISWC</th><th>Writers</th><th>Recording</th><th>Work</th><th>Links</th><th>Row</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>";
  }

  function seedForm(r) {
    var inputs = r.seed_fields.map(function (f) {
      return '<input type="hidden" name="' + esc(f[0]) + '" value="' + esc(f[1]) + '">';
    }).join("");
    var hasRelease = !!r.hits.release;
    return '<form action="' + MB + '/release/add" method="post" enctype="multipart/form-data" target="_blank">' + inputs +
      '<button type="submit" class="btn ' + (hasRelease ? "" : "primary") + '" title="' + (hasRelease ? "This release already exists. Seeding would create a second one." : "Open the MusicBrainz release editor pre-filled with this release") + '">' +
      (hasRelease ? "Seed anyway" : "Seed release editor") + "</button></form>";
  }

  function buildCard(r) {
    var allIssues = r.discrepancies.map(function (d) { return { d: d, track: "" }; })
      .concat(r.tracks.reduce(function (acc, t) { return acc.concat(t.discrepancies.map(function (d) { return { d: d, track: t.title }; })); }, []));
    var warns = r.counts.warnings, infos = r.counts.infos;
    var pills =
      '<span class="pill ' + (r.hits.release ? confClass(r.hits.release) : "bad") + '"><i></i>' + (r.hits.release ? "Release " + esc(r.hits.release.confidence) : "No release") + "</span>" +
      '<span class="pill ' + recStatus(r).replace("partial", "warn") + '"><i></i>Rec <span class="mono">' + r.counts.recordings_matched + "/" + r.counts.tracks + "</span></span>" +
      '<span class="pill ' + workStatus(r).replace("partial", "warn") + '"><i></i>Works <span class="mono">' + r.counts.works_matched + "/" + r.counts.tracks + "</span></span>" +
      (warns ? '<span class="pill warn"><i></i>' + plural(warns, "warning") + "</span>" : "") +
      (!warns && infos ? '<span class="pill info"><i></i>' + plural(infos, "note") + "</span>" : "");

    var coverSrc = r.cover_art_url || r.site_cover_url;
    var cover = coverSrc
      ? '<div class="cover" title="' + (r.cover_art_url ? "Cover Art Archive" : "Artist website") + '"><img src="' + esc(coverSrc) + '" alt="" loading="lazy" onerror="this.parentNode.textContent=\'no art\'"></div>'
      : '<div class="cover" aria-hidden="true">' + (r.hits.release ? "no art" : "new") + "</div>";
    var needsCoverArt = r.hits.release && !r.cover_art_url && r.site_cover_url;

    var card = el(
      '<details class="card' + (isDone(r) ? " is-done" : "") + '" id="rel-' + esc(r.key) + '" data-key="' + esc(r.key) + '">' +
        "<summary>" + cover +
          '<div class="head-main"><div class="head-title"><h3>' + esc(r.title) + '</h3><span class="credit">' + esc(r.release_artist) + "</span></div>" +
            '<div class="head-meta"><span>' + esc(r.release_date_iso || r.release_date_raw || "no date") + "</span>" +
              "<span>" + esc(r.primary_type || "untyped") + "</span>" +
              (r.upc ? '<span class="mono">UPC ' + esc(r.upc) + "</span>" : '<span class="mono">no UPC</span>') +
              (r.catalog_number ? '<span class="mono">' + esc(r.catalog_number) + "</span>" : "") +
              (r.release_label ? "<span>" + esc(r.release_label) + "</span>" : "") +
            "</div></div>" +
          '<div class="head-right"><div class="pills">' + pills + "</div>" +
            '<label class="done-toggle"><input type="checkbox"' + (isDone(r) ? " checked" : "") + "> Done</label>" + CHEV + "</div>" +
        "</summary>" +
        '<div class="card-body">' +
          '<div class="two-col">' +
            '<div class="panel"><div class="panel-head"><span>MusicBrainz entities</span>' +
              (r.hits.release ? '<a href="' + esc(r.hits.release.url) + '" target="_blank" rel="noreferrer">Open release</a>' : "") + "</div>" +
              '<div class="panel-body">' +
                entityRow("Artist", r.hits.artist, r.search_urls.artist, r.create_urls.artist) +
                entityRow("Label", r.hits.label, r.release_label ? r.search_urls.label : "", r.release_label ? r.create_urls.label : "", r.release_label ? "Not found" : "No label in CSV") +
                entityRow("Release group", r.hits.release_group, r.search_urls.release_group, "") +
                entityRow("Release", r.hits.release, r.search_urls.release, "") +
              "</div></div>" +
            '<div class="panel"><div class="panel-head"><span>Review</span><span>' + (warns ? plural(warns, "warning") : "") + (warns && infos ? " · " : "") + (infos ? plural(infos, "note") : "") + "</span></div>" +
              issuesList(allIssues) + "</div>" +
          "</div>" +
          tracksTable(r) +
          '<div class="panel"><div class="panel-head"><span>External links (seeded as URL relationships)</span></div>' + linksPanel(r) + "</div>" +
          '<div class="actions">' + seedForm(r) +
            (r.hits.release ? '<a class="btn" href="' + esc(r.hits.release.url) + '" target="_blank" rel="noreferrer">Open on MusicBrainz</a>' : "") +
            (r.hits.release ? '<a class="btn ghost" href="' + esc(r.hits.release.url) + '/edit" target="_blank" rel="noreferrer">Edit release</a>' : "") +
            (needsCoverArt
              ? '<a class="btn" href="' + esc(r.hits.release.url) + '/add-cover-art" target="_blank" rel="noreferrer" title="MusicBrainz has no front cover for this release. Upload the website image.">Add cover art</a>' +
                '<a class="btn ghost" href="' + esc(r.site_cover_url) + '" target="_blank" rel="noreferrer">Website image</a>'
              : (r.hits.release ? '<a class="btn ghost" href="' + esc(r.hits.release.url) + '/cover-art" target="_blank" rel="noreferrer">Cover art</a>' : "")) +
            (r.site_url ? '<a class="btn ghost" href="' + esc(r.site_url) + '" target="_blank" rel="noreferrer">Website</a>' : "") +
            '<span class="spacer"></span>' +
            '<details class="seedfields"><summary>' + r.seed_fields.length + " seeding fields</summary><pre>" +
              esc(r.seed_fields.map(function (f) { return f[0] + " = " + f[1]; }).join("\n")) + "</pre></details>" +
          "</div>" +
        "</div>" +
      "</details>"
    );

    var toggle = $(".done-toggle", card);
    toggle.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      var box = $("input", toggle);
      box.checked = !box.checked;
      if (box.checked) done[r.key] = true; else delete done[r.key];
      saveDone(done);
      card.classList.toggle("is-done", box.checked);
      var label = $('.mlabel[data-jump="' + r.key + '"]');
      if (label) label.classList.toggle("done", box.checked);
      renderKpis();
      refreshChipCounts();
      applyFilters();
    });
    return card;
  }

  var cardByKey = {};
  function renderReleases() {
    var wrap = $("#releases");
    wrap.innerHTML = "";
    releases.forEach(function (r) {
      var card = buildCard(r);
      cardByKey[r.key] = card;
      wrap.appendChild(card);
    });
    var empty = el('<div class="nores" id="nores" hidden>No releases match the current search and filters.</div>');
    wrap.appendChild(empty);
    sortCards();
  }

  function sortCards() {
    var wrap = $("#releases");
    var sorted = releases.slice().sort(SORTS[state.sort] || SORTS["date-desc"]);
    sorted.forEach(function (r) { wrap.appendChild(cardByKey[r.key]); });
    wrap.appendChild($("#nores"));
  }

  function applyFilters() {
    var shown = 0;
    releases.forEach(function (r) {
      var v = visible(r);
      cardByKey[r.key].hidden = !v;
      var row = $('.mrow[data-key="' + r.key + '"]');
      if (row) $all("button", row).forEach(function (b) { b.style.opacity = v ? "" : ".28"; });
      if (v) shown++;
    });
    $("#nores").hidden = shown > 0;
    $("#count").textContent = shown === releases.length ? plural(shown, "release") : shown + " of " + plural(releases.length, "release");
  }

  function jumpTo(key) {
    var card = cardByKey[key];
    if (!card) return;
    if (card.hidden) {
      state.filters.clear();
      state.query = "";
      $("#q").value = "";
      $all(".chip").forEach(function (c) { c.setAttribute("aria-pressed", "false"); });
      applyFilters();
    }
    card.open = true;
    card.scrollIntoView({ behavior: "smooth", block: "start" });
    $("summary", card).focus({ preventScroll: true });
  }

  function renderFoot() {
    $("#foot").innerHTML = "Seeding opens the MusicBrainz release editor pre-filled; nothing is submitted until you save it there. " +
      "Matched recordings are seeded by MBID so no duplicates are created. Done state is stored in this browser only.";
  }

  // ------------------------------------------------------------------ boot
  renderMasthead();
  renderKpis();
  renderMatrix();
  renderToolbar();
  renderReleases();
  renderFoot();
  applyFilters();

  document.addEventListener("click", function (e) {
    var jump = e.target.closest && e.target.closest("[data-jump]");
    if (jump) jumpTo(jump.getAttribute("data-jump"));
  });
})();

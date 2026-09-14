"""
Apply third-party catalog lookups (Spotify, Apple Music, Discogs) to plans:
seedable URL relationships plus cross-source discrepancies.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Iterable, List, Optional

from .constants import LINK_TYPE_DISCOGRAPHY_ENTRY
from .discrepancies import LENGTH_TOLERANCE_MS
from .external.discogs import discogs_release_url, match_discogs_release
from .external.links import build_external_links
from .external.spotify import select_spotify_track
from .external.website import SiteAlbum, SiteTrack, match_site_album, match_site_track, spotify_track_id
from .matching import normalize_title
from .models import Discrepancy, ExternalLink, ExternalRelease, ExternalTrack, ReleasePlan, TrackPlan
from .utils import clean_value, normalize_iswc


SOURCE_LABELS = {"spotify": "Spotify", "itunes": "Apple Music", "discogs": "Discogs", "website": "Website"}
PROVIDER_LABELS = {
    "spotify": "Spotify", "apple": "Apple Music", "youtube": "YouTube", "soundcloud": "SoundCloud", "tidal": "Tidal",
    "deezer": "Deezer", "beatport": "Beatport", "bandcamp": "Bandcamp", "amazon": "Amazon", "pandora": "Pandora", "audiomack": "Audiomack",
}


def _mmss(ms: Optional[int]) -> str:
    if ms is None:
        return ""
    total = int(round(ms / 1000))
    return f"{total // 60}:{total % 60:02d}"


def _add_links(target: List[ExternalLink], new_links: Iterable[ExternalLink]) -> None:
    seen = {link.url for link in target}
    for link in new_links:
        if link.url and link.url not in seen:
            target.append(link)
            seen.add(link.url)


def _compare_date(plan: ReleasePlan, release: ExternalRelease) -> None:
    if plan.release_date_iso and release.date and len(release.date) == 10 and plan.release_date_iso != release.date:
        plan.discrepancies.append(Discrepancy(
            "release_date", plan.release_date_iso, release.date, "warn",
            f"{SOURCE_LABELS.get(release.source, release.source.title())} lists a different release date", source=release.source,
        ))


def _compare_track(track: TrackPlan, ext: ExternalTrack) -> None:
    if track.duration_ms and ext.duration_ms and abs(ext.duration_ms - track.duration_ms) > LENGTH_TOLERANCE_MS:
        track.discrepancies.append(Discrepancy(
            "length", _mmss(track.duration_ms), _mmss(ext.duration_ms), "warn",
            f"{SOURCE_LABELS.get(ext.source, ext.source.title())} lists a different length", source=ext.source,
        ))
    if ext.url:
        label = SOURCE_LABELS.get(ext.source, ext.source.title())
        existing = [link for link in track.external_links if link.label == label]
        new_link = ExternalLink(url=ext.url, link_type_id=None, source=ext.source, label=label)
        if not existing:
            _add_links(track.external_links, [new_link])
        elif ext.source == "spotify" and existing[0].url != ext.url:
            # The Spotify track was chosen for this specific release; it supersedes the
            # website's one-page-per-song link, which may point at another release.
            track.external_links[track.external_links.index(existing[0])] = new_link


def _match_tracks_by_title(plan: ReleasePlan, release: ExternalRelease) -> None:
    by_title = {normalize_title(t.title): t for t in release.tracks}
    for track in plan.tracks:
        ext = by_title.get(normalize_title(track.title))
        if ext:
            _compare_track(track, ext)


def _warn(field: str, csv_value: str, other: str, message: str, source: str) -> Discrepancy:
    return Discrepancy(field, csv_value, other, "warn", message, source=source)


def _apply_site_track(track: TrackPlan, site: SiteTrack) -> None:
    links = [ExternalLink(url=site.url, link_type_id=None, source="website", label="Website")]
    if site.has_lyrics:
        links.append(ExternalLink(url=f"{site.url}#lyrics", link_type_id=None, source="website", label="Lyrics"))
    for provider, url in site.links.items():
        links.append(ExternalLink(url=url, link_type_id=None, source="website", label=PROVIDER_LABELS.get(provider, provider.title())))
    _add_links(track.external_links, links)

    if site.isrc and track.isrc and track.isrc.upper() != site.isrc.upper():
        track.discrepancies.append(_warn("isrc", track.isrc, site.isrc, "Website lists a different ISRC", "website"))
    elif site.isrc and not track.isrc:
        track.discrepancies.append(_warn("isrc", "", site.isrc, "Website has an ISRC the CSV lacks", "website"))
    if site.iswc and track.iswc and normalize_iswc(track.iswc) != normalize_iswc(site.iswc):
        track.discrepancies.append(_warn("iswc", track.iswc, site.iswc, "Website lists a different ISWC", "website"))
    elif site.iswc and not track.iswc:
        track.discrepancies.append(_warn("iswc", "", site.iswc, "Website has an ISWC the CSV lacks", "website"))
    if track.duration_ms and site.duration_ms and abs(site.duration_ms - track.duration_ms) > LENGTH_TOLERANCE_MS:
        track.discrepancies.append(_warn("length", _mmss(track.duration_ms), _mmss(site.duration_ms), "Website lists a different length", "website"))


def _apply_site_release(plan: ReleasePlan, url: str, cover_url: str, date: str) -> None:
    if url:
        plan.site_url = url
        _add_links(plan.external_links, [ExternalLink(url=url, link_type_id=LINK_TYPE_DISCOGRAPHY_ENTRY, source="website", label="Website")])
    if cover_url:
        plan.site_cover_url = cover_url
    if plan.release_date_iso and date and len(date) == 10 and plan.release_date_iso != date:
        plan.discrepancies.append(_warn("release_date", plan.release_date_iso, date, "Website lists a different release date", "website"))


def apply_enrichment(
        plan: ReleasePlan,
        spotify: Optional[ExternalRelease],
        itunes: Optional[ExternalRelease],
        discogs: Optional[Dict[str, Any]],
        spotify_tracks: Optional[Dict[str, ExternalTrack]] = None,
        checked: Iterable[str] = (),
        site_tracks: Optional[List[Optional[SiteTrack]]] = None,
        site_album: Optional[SiteAlbum] = None,
        spotify_rejections: Optional[Dict[str, str]] = None,
) -> None:
    """Mutate plan with links, per-source status and discrepancies. Pure w.r.t. the network."""
    site_tracks = list(site_tracks or [])
    site_found = site_album is not None or any(site_tracks)
    for source in checked:
        found = {"spotify": spotify, "itunes": itunes, "discogs": discogs, "website": site_found}.get(source)
        plan.external_status[source] = "found" if found else "missing"

    for track, site in zip(plan.tracks, site_tracks):
        if site:
            _apply_site_track(track, site)
    if site_album:
        _apply_site_release(plan, site_album.url, site_album.cover_url, site_album.date)
    elif len(plan.tracks) == 1 and site_tracks and site_tracks[0]:
        single = site_tracks[0]
        _apply_site_release(plan, single.url, single.cover_url, single.date)
    elif any(site_tracks):
        first = next(t for t in site_tracks if t)
        _apply_site_release(plan, first.album_url or first.url, first.cover_url, "")

    _add_links(plan.external_links, build_external_links(
        discogs_url=discogs_release_url(discogs) if discogs else "",
        spotify_album_url=spotify.url if spotify else "",
        apple_album_url=itunes.url if itunes else "",
    ))

    for release in (spotify, itunes):
        if release:
            _compare_date(plan, release)
            _match_tracks_by_title(plan, release)

    for track in plan.tracks:
        key = track.isrc.upper() if track.isrc else ""
        ext = (spotify_tracks or {}).get(key) if key else None
        if ext:
            _compare_track(track, ext)
            if ext.isrc and key and ext.isrc.upper() != key:
                track.discrepancies.append(_warn("isrc", track.isrc, ext.isrc, "Spotify lists a different ISRC for this track", "spotify"))
        reason = (spotify_rejections or {}).get(key) if key else None
        if reason:
            track.discrepancies.append(_warn("spotify_match", track.isrc, "", reason, "spotify"))


def enrich_plans(
        plans: List[ReleasePlan],
        spotify_client: Any,
        itunes_client: Any,
        discogs_client: Any,
        website_client: Any = None,
) -> None:
    """Run the network lookups for every plan and apply them."""
    sources = [name for name, client in (("website", website_client), ("spotify", spotify_client),
                                         ("itunes", itunes_client), ("discogs", discogs_client))
               if client is not None and getattr(client, "enabled", False)]
    if not sources:
        return
    print(f"\nEnriching from: {', '.join(sources)}", file=sys.stderr)

    all_site_tracks: List[SiteTrack] = website_client.tracks() if "website" in sources else []
    all_site_albums: List[SiteAlbum] = website_client.albums() if "website" in sources else []

    for plan in plans:
        spotify_release = itunes_release = None
        discogs_result = None
        spotify_tracks: Dict[str, ExternalTrack] = {}
        spotify_rejections: Dict[str, str] = {}
        site_tracks: List[Optional[SiteTrack]] = [match_site_track(all_site_tracks, t.isrc, t.title) for t in plan.tracks] if "website" in sources else []
        site_album = match_site_album(all_site_albums, plan.title) if "website" in sources and len(plan.tracks) > 1 else None

        if "spotify" in sources:
            spotify_release = spotify_client.album_by_upc(plan.upc)
            for idx, track in enumerate(plan.tracks):
                if not track.isrc:
                    continue
                site = site_tracks[idx] if idx < len(site_tracks) else None
                chosen = None
                if site and site.links.get("spotify"):
                    chosen = spotify_client.track_by_id(spotify_track_id(site.links["spotify"]))
                # The website has one page per song, so its Spotify link may point at another
                # release of the same recording. Prefer the version on this release when it exists.
                same_release = chosen is not None and normalize_title(chosen.album_title) == normalize_title(plan.title)
                if chosen is None or not same_release:
                    candidates = spotify_client.tracks_by_isrc(track.isrc)
                    if chosen is not None and chosen not in candidates:
                        candidates = list(candidates) + [chosen]
                    picked, reason = select_spotify_track(candidates, track.artist, track.title, track.duration_ms, plan.title)
                    if picked is not None:
                        chosen = picked
                    elif chosen is None and reason:
                        spotify_rejections[track.isrc.upper()] = reason
                if chosen:
                    spotify_tracks[track.isrc.upper()] = chosen
        if "itunes" in sources:
            itunes_release = itunes_client.album_by_upc(plan.upc)
        if "discogs" in sources:
            results = discogs_client.artist_releases(plan.release_artist)
            if not results and plan.credited_artists:
                results = discogs_client.artist_releases(clean_value(plan.artist_hit.name) if plan.artist_hit else plan.release_artist)
            discogs_result = match_discogs_release(results, plan.upc, plan.catalog_number, [t.isrc for t in plan.tracks], plan.title)
        apply_enrichment(plan, spotify_release, itunes_release, discogs_result, spotify_tracks, checked=sources,
                         site_tracks=site_tracks, site_album=site_album, spotify_rejections=spotify_rejections)
        status = "  ".join(f"{s}:{'✅' if plan.external_status.get(s) == 'found' else '—'}" for s in sources)
        print(f"  {plan.release_artist} – {plan.title}  |  {status}", file=sys.stderr)

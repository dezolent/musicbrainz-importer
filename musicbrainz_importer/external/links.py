"""Assemble seedable release-URL relationships from CSV columns and enrichment results."""

from __future__ import annotations

from typing import List

from ..constants import LINK_TYPE_AMAZON_ASIN, LINK_TYPE_DISCOGS, LINK_TYPE_FREE_STREAMING, LINK_TYPE_STREAMING
from ..models import ExternalLink
from ..utils import clean_value


def build_external_links(
        csv_discogs: str = "",
        csv_asin: str = "",
        discogs_url: str = "",
        spotify_album_url: str = "",
        apple_album_url: str = "",
) -> List[ExternalLink]:
    candidates = [
        (clean_value(csv_discogs), LINK_TYPE_DISCOGS, "csv", "Discogs"),
        (clean_value(discogs_url), LINK_TYPE_DISCOGS, "discogs", "Discogs"),
        (f"https://www.amazon.com/dp/{clean_value(csv_asin)}" if clean_value(csv_asin) else "", LINK_TYPE_AMAZON_ASIN, "csv", "Amazon"),
        (clean_value(spotify_album_url), LINK_TYPE_FREE_STREAMING, "spotify", "Spotify"),
        (clean_value(apple_album_url), LINK_TYPE_STREAMING, "itunes", "Apple Music"),
    ]
    links: List[ExternalLink] = []
    seen = set()
    for url, link_type, source, label in candidates:
        if not url or url in seen:
            continue
        seen.add(url)
        links.append(ExternalLink(url=url, link_type_id=link_type, source=source, label=label))
    return links

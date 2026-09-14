"""Small JSON GET helper with polite retry for third-party APIs."""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, Dict, Optional

import requests

_RETRY_DELAYS = (2, 6)


def get_json(
        session: Any,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        sleep: Callable[[float], None] = time.sleep,
        label: str = "",
) -> Dict[str, Any]:
    """GET JSON; retry on 429/5xx and network errors; return {} on failure."""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        if attempt:
            sleep(_RETRY_DELAYS[attempt - 1])
        try:
            response = session.get(url, params=params, headers=headers, timeout=30)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            print(f"  Warning: {label or url} network error ({exc})", file=sys.stderr)
            continue
        except requests.exceptions.RequestException as exc:
            print(f"  Warning: {label or url} failed ({exc})", file=sys.stderr)
            return {}
        status = getattr(response, "status_code", 200)
        if status == 429 or status >= 500:
            retry_after = (getattr(response, "headers", {}) or {}).get("Retry-After")
            if retry_after and str(retry_after).isdigit():
                sleep(float(retry_after))
            continue
        if status >= 400:
            if status != 404:
                print(f"  Warning: {label or url} HTTP {status}", file=sys.stderr)
            return {}
        try:
            return response.json() or {}
        except ValueError:
            return {}
    print(f"  Warning: {label or url} gave up after retries", file=sys.stderr)
    return {}

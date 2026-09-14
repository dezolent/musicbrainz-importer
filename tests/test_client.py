"""MusicBrainzClient: retry semantics and paginated browsing, using an injected fake session."""

import requests

from musicbrainz_importer.client import MusicBrainzClient


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}", response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(responses):
    sleeps = []
    session = FakeSession(responses)
    client = MusicBrainzClient(user_agent="test/1.0 (t@example.com)", session=session, sleep=sleeps.append)
    return client, session, sleeps


def test_search_retries_on_503_busy_and_then_succeeds():
    client, session, sleeps = _client([
        FakeResponse(503, {"error": "The MusicBrainz web server is currently busy."}),
        FakeResponse(200, {"recordings": [{"id": "r1", "title": "Gone"}]}),
    ])
    result = client.search("recording", "isrc:GBKQU1591272")
    assert [r["id"] for r in result] == ["r1"]
    assert len(session.calls) == 2
    assert sleeps and sleeps[0] > 0


def test_search_honours_retry_after_header_on_429():
    client, _, sleeps = _client([
        FakeResponse(429, {}, headers={"Retry-After": "7"}),
        FakeResponse(200, {"recordings": []}),
    ])
    client.search("recording", "isrc:X")
    assert sleeps[0] == 7


def test_search_gives_up_after_retries_and_returns_empty():
    client, session, _ = _client([FakeResponse(503, {}) for _ in range(10)])
    assert client.search("recording", "isrc:X") == []
    assert len(session.calls) == 4  # first attempt + 3 retries


def test_search_does_not_retry_on_400():
    client, session, _ = _client([FakeResponse(400, {"error": "bad query"})])
    assert client.search("recording", "isrc:X") == []
    assert len(session.calls) == 1


def test_search_retries_on_timeout():
    client, session, _ = _client([
        requests.exceptions.Timeout("slow"),
        FakeResponse(200, {"recordings": [{"id": "r1"}]}),
    ])
    assert client.search("recording", "isrc:X")[0]["id"] == "r1"
    assert len(session.calls) == 2


def test_browse_paginates_until_count_is_reached():
    client, session, _ = _client([
        FakeResponse(200, {"recording-count": 3, "recording-offset": 0, "recordings": [{"id": "a"}, {"id": "b"}]}),
        FakeResponse(200, {"recording-count": 3, "recording-offset": 2, "recordings": [{"id": "c"}]}),
    ])
    items = client.browse("recording", {"artist": "mbid-1"}, inc="isrcs+artist-credits", page_size=2)
    assert [i["id"] for i in items] == ["a", "b", "c"]
    assert session.calls[0][1]["offset"] == 0 and session.calls[0][1]["limit"] == 2
    assert session.calls[1][1]["offset"] == 2
    assert session.calls[0][1]["inc"] == "isrcs+artist-credits"


def test_lookup_returns_entity_dict():
    client, session, _ = _client([FakeResponse(200, {"id": "mbid-1", "name": "Dezolent"})])
    entity = client.lookup("artist", "mbid-1", inc="url-rels")
    assert entity["name"] == "Dezolent"
    assert session.calls[0][0].endswith("/artist/mbid-1")


def test_disabled_client_makes_no_requests():
    client, session, _ = _client([])
    client.enabled = False
    assert client.search("recording", "x") == []
    assert client.browse("recording", {"artist": "m"}) == []
    assert client.lookup("artist", "m") == {}
    assert session.calls == []


def test_throttle_spaces_consecutive_requests():
    client, _, sleeps = _client([FakeResponse(200, {"recordings": []}), FakeResponse(200, {"recordings": []})])
    client.search("recording", "a")
    client.search("recording", "b")
    assert any(0 < s <= 1.2 for s in sleeps)

import pytest
import requests

from ingest import http


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")
        return self


def test_recovers_from_rate_limit(monkeypatch):
    responses = [FakeResponse(429), FakeResponse(429), FakeResponse(200)]
    sleeps = []
    monkeypatch.setattr(http.requests, "get", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(http.time, "sleep", sleeps.append)

    resp = http.get_with_retry("https://example.com")

    assert resp.status_code == 200
    assert len(sleeps) == 2
    assert sleeps[0] == 5.0 and sleeps[1] == 10.0  # exponential ladder


def test_honors_retry_after_header(monkeypatch):
    responses = [FakeResponse(429, headers={"Retry-After": "30"}), FakeResponse(200)]
    sleeps = []
    monkeypatch.setattr(http.requests, "get", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(http.time, "sleep", sleeps.append)

    http.get_with_retry("https://example.com")

    assert sleeps == [30.0]


def test_raises_after_exhausting_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        http.requests, "get", lambda *a, **k: FakeResponse(500)
    )
    monkeypatch.setattr(http.time, "sleep", sleeps.append)

    with pytest.raises(requests.HTTPError):
        http.get_with_retry("https://example.com", max_retries=3)

    assert len(sleeps) == 2  # no sleep after the final attempt

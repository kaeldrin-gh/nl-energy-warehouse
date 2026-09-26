"""API tests: read-only endpoints served from the built sample warehouse."""

from fastapi.testclient import TestClient

from api.main import app


def make_client(warehouse, monkeypatch) -> TestClient:
    monkeypatch.setenv("DUCKDB_PATH", str(warehouse))
    return TestClient(app)


def test_index_lists_endpoints(built_sample_warehouse, monkeypatch):
    body = make_client(built_sample_warehouse, monkeypatch).get("/").json()

    assert "/prices/daily" in body["endpoints"]


def test_health_ok(built_sample_warehouse, monkeypatch):
    response = make_client(built_sample_warehouse, monkeypatch).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_warehouse_is_503(tmp_path, monkeypatch):
    client = make_client(tmp_path / "missing.duckdb", monkeypatch)

    assert client.get("/health").status_code == 503


def test_daily_prices_newest_first(built_sample_warehouse, monkeypatch):
    rows = (
        make_client(built_sample_warehouse, monkeypatch)
        .get("/prices/daily", params={"limit": 5})
        .json()
    )

    assert 0 < len(rows) <= 5
    dates = [row["local_date"] for row in rows]
    assert dates == sorted(dates, reverse=True)


def test_daily_prices_date_filter(built_sample_warehouse, monkeypatch):
    client = make_client(built_sample_warehouse, monkeypatch)
    newest = client.get("/prices/daily", params={"limit": 1}).json()[0]["local_date"]

    rows = client.get("/prices/daily", params={"start": newest, "end": newest}).json()

    assert [row["local_date"] for row in rows] == [newest]


def test_hourly_prices_for_a_day(built_sample_warehouse, monkeypatch):
    client = make_client(built_sample_warehouse, monkeypatch)
    day = client.get("/prices/daily", params={"limit": 1}).json()[0]["local_date"]

    rows = client.get("/prices/hourly", params={"date": day}).json()

    assert rows
    assert all(row["hour_local"].startswith(day) for row in rows)
    assert len({row["hour_utc"] for row in rows}) == len(rows)


def test_invalid_date_is_rejected(built_sample_warehouse, monkeypatch):
    client = make_client(built_sample_warehouse, monkeypatch)

    assert client.get("/prices/hourly", params={"date": "not-a-date"}).status_code == 422


def test_unknown_date_returns_empty(built_sample_warehouse, monkeypatch):
    client = make_client(built_sample_warehouse, monkeypatch)

    assert client.get("/prices/hourly", params={"date": "1999-01-01"}).json() == []


def test_limit_bounds_are_validated(built_sample_warehouse, monkeypatch):
    client = make_client(built_sample_warehouse, monkeypatch)

    assert client.get("/prices/daily", params={"limit": 0}).status_code == 422
    assert client.get("/prices/daily", params={"limit": 1000}).status_code == 422

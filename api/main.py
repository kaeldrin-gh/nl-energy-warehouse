"""Read-only HTTP API over the gold marts.

    pip install -e ".[api]"
    uvicorn api.main:app --reload        # http://localhost:8000/docs

The service reads the same DuckDB warehouse as the rest of the repo
(``DUCKDB_PATH``, default ``warehouse/energy.duckdb``), opens it read-only and
never writes. Endpoints are covered by ``tests/test_api.py``.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Annotated

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from ingest.config import settings

app = FastAPI(
    title="nl-energy-warehouse API",
    version="0.1.0",
    description="Read-only endpoints over the Dutch day-ahead price and weather marts.",
)

DAILY_COLUMNS = (
    "local_date",
    "hours_in_day",
    "avg_price_eur_mwh",
    "min_price_eur_mwh",
    "max_price_eur_mwh",
    "negative_price_hours",
    "avg_temp_c",
    "max_wind_ms",
    "total_radiation_mj_m2",
)

HOURLY_COLUMNS = (
    "hour_utc",
    "hour_local",
    "price_eur_mwh",
    "price_source",
    "temp_c",
    "wind_ms",
    "radiation_jm2",
    "is_negative_price",
)


def warehouse_path() -> Path:
    """Resolve the warehouse the way the CLI and dbt do."""
    raw = os.environ.get("DUCKDB_PATH")
    return Path(raw) if raw else settings.duckdb_path


WarehousePath = Annotated[Path, Depends(warehouse_path)]


def connect(path: Path) -> duckdb.DuckDBPyConnection:
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"warehouse not found: {path}")
    conn = duckdb.connect(str(path), read_only=True)
    conn.execute("SET TimeZone='UTC'")
    return conn


class DailyPrice(BaseModel):
    local_date: dt.date
    hours_in_day: int
    avg_price_eur_mwh: float | None
    min_price_eur_mwh: float | None
    max_price_eur_mwh: float | None
    negative_price_hours: int
    avg_temp_c: float | None
    max_wind_ms: float | None
    total_radiation_mj_m2: float | None


class HourlyPrice(BaseModel):
    hour_utc: dt.datetime
    hour_local: dt.datetime
    price_eur_mwh: float
    price_source: str
    temp_c: float | None
    wind_ms: float | None
    radiation_jm2: float | None
    is_negative_price: bool


@app.get("/", tags=["meta"])
def index() -> dict:
    """Small index so the service is discoverable from a browser."""
    return {
        "service": "nl-energy-warehouse",
        "docs": "/docs",
        "endpoints": ["/health", "/prices/daily", "/prices/hourly"],
    }


@app.get("/health", tags=["meta"])
def health(path: WarehousePath) -> dict:
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"warehouse not found: {path}")
    return {"status": "ok"}


@app.get("/prices/daily", response_model=list[DailyPrice], tags=["prices"])
def prices_daily(
    path: WarehousePath,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: Annotated[int, Query(ge=1, le=400)] = 90,
) -> list[DailyPrice]:
    """Daily aggregates from ``mart_daily_summary``, newest first."""
    clauses: list[str] = []
    params: list[object] = []
    if start:
        clauses.append("local_date >= ?")
        params.append(start)
    if end:
        clauses.append("local_date <= ?")
        params.append(end)
    where = f"where {' and '.join(clauses)}" if clauses else ""

    conn = connect(path)
    try:
        rows = conn.execute(
            f"""
            select {", ".join(DAILY_COLUMNS)}
            from mart_daily_summary
            {where}
            order by local_date desc
            limit ?
            """,
            [*params, limit],
        ).fetchall()
    finally:
        conn.close()
    return [DailyPrice(**dict(zip(DAILY_COLUMNS, row, strict=True))) for row in rows]


@app.get("/prices/hourly", response_model=list[HourlyPrice], tags=["prices"])
def prices_hourly(
    date: dt.date,
    path: WarehousePath,
) -> list[HourlyPrice]:
    """Every hour of one local date from ``fct_hourly_price_weather``."""
    conn = connect(path)
    try:
        rows = conn.execute(
            f"""
            select {", ".join(HOURLY_COLUMNS)}
            from fct_hourly_price_weather
            where cast(hour_local as date) = ?
            order by hour_utc
            """,
            [date],
        ).fetchall()
    finally:
        conn.close()
    return [HourlyPrice(**dict(zip(HOURLY_COLUMNS, row, strict=True))) for row in rows]

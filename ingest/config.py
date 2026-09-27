import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _duckdb_path() -> Path:
    # Same variable, same meaning as dbt's profile and the API: a relative value is
    # relative to the working directory. Ignoring it here once sent a sample load
    # into the real warehouse while dbt built a different file.
    raw = os.getenv("DUCKDB_PATH")
    return Path(raw) if raw else ROOT / "warehouse" / "energy.duckdb"


@dataclass(frozen=True)
class Settings:
    root: Path = field(default_factory=lambda: ROOT)
    duckdb_path: Path = field(default_factory=_duckdb_path)
    entsoe_token: str | None = os.getenv("ENTSOE_TOKEN")
    knmi_token: str | None = os.getenv("KNMI_TOKEN")
    nl_bidding_zone: str = "10YNL----------L"
    lookback_days: int = 7
    sample_days: int = 90
    request_timeout: int = 60


settings = Settings()

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    root: Path = field(default_factory=lambda: ROOT)
    duckdb_path: Path = field(default_factory=lambda: ROOT / "warehouse" / "energy.duckdb")
    entsoe_token: str | None = os.getenv("ENTSOE_TOKEN")
    knmi_token: str | None = os.getenv("KNMI_TOKEN")
    nl_bidding_zone: str = "10YNL----------L"
    lookback_days: int = 7
    sample_days: int = 90
    request_timeout: int = 60


settings = Settings()

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def load_fixture(name: str) -> bytes:
    return (REPO_ROOT / "tests" / "fixtures" / name).read_bytes()

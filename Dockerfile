FROM python:3.12-slim

WORKDIR /app

# Install the package (and dbt) first so source edits don't bust the wheel layer.
COPY pyproject.toml README.md ./
COPY ingest ./ingest
RUN pip install --no-cache-dir -e ".[dbt,test]"

# Pinned working set for reproducible builds (see README, "Reproducibility").
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY dbt ./dbt

ENV DUCKDB_PATH=/data/energy.duckdb
VOLUME /data

ENTRYPOINT ["python", "-m", "ingest.cli"]
CMD ["load", "--sample"]

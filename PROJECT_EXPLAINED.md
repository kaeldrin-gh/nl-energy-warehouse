# PROJECT_EXPLAINED.md — the whole project, explained simply

This file explains everything this project does, in plain language, for
someone who is new to data engineering. No prior knowledge assumed — every
technical term is either avoided or explained where it first appears.

---

## 1. What is this project? (the story)

Every day around 12:45, the Dutch electricity market runs an auction. Power
producers and buyers submit bids, and by roughly 12:45 the price of **every
hour of the next day** is decided. Those prices are published by **ENTSO-E**,
the European network of grid operators.

Sometimes those prices are wild. On December 12, 2024, one hour of Dutch
electricity cost **€873 per megawatt-hour** — about ten times a normal hour.
Sometimes an hour costs **less than zero**: producers literally pay consumers
to use electricity because there is too much wind and sun.

This project collects that price data (plus weather data), stores it safely,
cleans it, tests it, and turns it into charts and analysis. It exists to
answer one question:

> **What actually drives the hourly power price in the Netherlands, and when
> is it cheap?**

The full answer lives in `analysis/findings.md`. This document explains how
the machine that produces that answer works.

---

## 2. The cast of technologies (who's who)

You don't need to know any of these tools. Here is what each one is and why
it's in the project:

| Technology | What it is | The analogy |
| --- | --- | --- |
| **Python** | The programming language everything runs on | The kitchen where all the cooking happens |
| **DuckDB** | A database that lives in a single file on disk — no server, no installation | An Excel workbook with superpowers: millions of rows, queried in a language called SQL |
| **SQL** | The language used to ask databases questions ("give me the average price per hour") | Plain, structured questions |
| **dbt** | A tool that organizes SQL files into ordered steps, runs automatic tests on the results, and generates documentation | A recipe book where every recipe also proves it was cooked correctly |
| **pandas** | A Python library for tables — filtering, averaging, joining | Excel formulas, but reproducible and fast |
| **ENTSO-E API** | The official source of electricity prices (an "API" is a way for programs to ask a website for data) | The stock market ticker for electricity |
| **energy-charts.info** | A second, independent website that publishes the *same* prices | A second newspaper reporting the same match score — used to check the first |
| **Open-Meteo** | A free weather data service | The weather forecast, but for the past |
| **Parquet** | A file format for storing tables compactly | A zip file optimized for spreadsheets — 10× smaller, fast to scan |
| **Power BI** | Microsoft's tool for building interactive dashboards | The storefront where the data becomes charts people click |
| **matplotlib** | A Python library that draws charts into images | The autopilot that draws the report graphics |
| **GitHub Actions** | A robot that runs your commands in the cloud on a schedule or on every change | A night-shift employee who never sleeps |

---

## 3. The journey of one number: the €873 hour

The best way to understand the project is to follow a single data point
through the whole system.

### Step 0 — The event

On December 12, 2024, a windless cold snap hit Europe. Demand spiked, wind
power vanished, and the auction produced an extraordinary price: the hour
between 17:00 and 18:00 Dutch time would cost **€873/MWh**. ENTSO-E published
this number in a machine-readable file (XML format) on its website.

### Step 1 — Ingestion (`ingest/entsoe.py`)

A Python function called `fetch_day_ahead_prices` asks the ENTSO-E API: "give
me the day-ahead prices for the Netherlands between these two dates." It
receives XML back — a text format full of tags like `<price.amount>873.0</
price.amount>`.

A *parser* (a small translator program) reads that XML and converts it into a
pandas table: rows of `hour` and `price`. Two important things happen here:

- **Hourly averaging**: since 2025 the market prices 15-minute slots, not full
  hours. The parser averages the four slots of each hour into one honest
  hourly number.
- **`fetched_at`**: every row gets a timestamp of *when we downloaded it*.
  This matters later — it's how the project knows how fresh its data is.

### Step 2 — Landing in the raw zone (`ingest/db.py`)

The rows are written into DuckDB, into a table called `raw.entsoe_prices`.
"Raw" means: kept exactly as published, cleaned later. The write uses
**`INSERT OR REPLACE`** — database-speak for *"if this hour already exists,
overwrite it; otherwise add it."* That one rule makes the whole pipeline
**idempotent**: running it twice is harmless, because the second run simply
overwrites with the same values.

Each run is also logged in `raw.ingest_log` — a notebook entry of "who ran,
when, how many rows."

### Step 3 — Cleaning in staging (`dbt/models/staging/`)

Raw data is messy: duplicated rows from repeated fetches, hours labeled in
local Dutch time, weather from multiple providers. The **staging models** (SQL
files run by dbt) do three things:

- **Deduplication**: if the same hour was fetched twice, keep the newest fetch
  (`fetched_at` decides who wins).
- **Time conversion**: weather data is labeled in Dutch local time, which is
  UTC+1 in winter and UTC+2 in summer (daylight saving time). The staging SQL
  converts it to UTC using the *calendar*, not a hardcoded offset — so the two
  confusing nights a year (clocks forward/back) are handled correctly. There
  are automated tests that prove this with made-up DST days.
- **Unification**: weather can come from KNMI (the Dutch weather institute) or
  Open-Meteo; staging merges them into one feed and records which one was used.

### Step 4 — Business rules in intermediate (`dbt/models/intermediate/`)

`int_price_weather_hourly.sql` is where the thinking happens. It answers:

- *Which price do we trust?* ENTSO-E is authoritative. If ENTSO-E hasn't
  published an hour, the energy-charts copy fills in — and a column called
  `price_source` records who supplied it, forever.
- *How much do the two sources agree?* When both exist, the absolute
  difference is computed into `price_diff_eur`. (When only one exists, no
  difference is computed — you can't compare a source with itself.)
- *What was the weather that hour?* The unified weather feed is joined in by
  UTC hour.

### Step 5 — Marts (`dbt/models/marts/`)

Two final tables, built for humans and dashboards:

- `fct_hourly_price_weather`: **one row per hour** — price, cross-check price,
  difference, provenance, temperature, wind, radiation.
- `mart_daily_summary`: **one row per day** — average price, cheapest/most
  expensive hour, count of negative hours, weather totals.

"Marts" is warehouse jargon for *final, clean, purpose-built tables that BI
tools read*. Everything before this is plumbing; this is the product.

### Step 6 — Tests (`dbt/tests/` + `tests/`)

Before any of this is trusted, automatic checks run:

- Is every hour unique? Is any price below −€500 or above €4,000 (the
  exchange's own technical limits)?
- Do the two publishers agree within €2 on recent hours?
- Do hours follow each other without gaps?
- Does the whole pipeline survive the two daylight-saving transition nights?
- Do the exported files still have exactly the columns Power BI expects?

If any check fails, the build turns red. **Red means: a number you were about
to trust is wrong.**

### Step 7 — Serving (`ingest/cli.py export` + `report`)

Two doors out of the warehouse:

- `python -m ingest.cli export` writes the marts to Parquet files in
  `exports/` — the files Power BI reads.
- `python -m ingest.cli report` draws charts (with matplotlib) into
  `exports/report.html` — open it in a browser and you see the market.
- `python -m ingest.cli bi v1` runs any analysis query from
  `analysis/bi_queries.sql` directly against the warehouse and prints the
  result table.
- `python -m ingest.cli refresh` does the whole chain in one command:
  download new data → run all SQL → export → report.

### Step 8 — Power BI (`powerbi/`)

The file `powerbi/nl-energy-dashboard.pbix` opens in Power BI Desktop and
shows the dashboard built on the exported Parquet files: the daily price
timeline, the hour-of-day curve, negative-price days. Because it reads the
Parquet files, clicking **Refresh** in Power BI pulls in whatever the pipeline
produced most recently.

### Step 9 — The automation (`.github/workflows/`)

GitHub Actions is a cloud robot that runs commands for you. Three robots work
here:

- **ci** — on every change to the code: style checks, all 35 Python tests, a
  full pipeline run on sample data, and the same SQL built against a second
  database engine (PostgreSQL) to prove the project isn't locked to one tool.
- **docs** — rebuilds the SQL documentation site and publishes it online:
  [kaeldrin-gh.github.io/nl-energy-warehouse](https://kaeldrin-gh.github.io/nl-energy-warehouse/)
- **ingest** — every day at 15:45 Dutch time: downloads fresh prices, rebuilds,
  tests, exports. If anything fails, the robot turns red and sends an email.

### Step 10 — The postmortems (`INCIDENTS.md`)

Not everything went right — and that's the most valuable part. Eight real
problems were hit during the build (the source rewrote history; the weather
institute retired its downloads; a sanity test rejected *real* market prices;
the market changed to 15-minute slots...). Each one is written up as a
postmortem: what happened, how it was detected, and what design decision it
produced. Reading INCIDENTS.md is reading the project's autobiography.

---

## 4. Tour of the folders

| Path | What lives there |
| --- | --- |
| `ingest/` | Python code that downloads raw data (one file per source) |
| `dbt/models/staging/` | SQL that cleans raw data (dedupe, time zones) |
| `dbt/models/intermediate/` | SQL that applies business rules (fallback, diff) |
| `dbt/models/marts/` | SQL that builds the final tables for BI |
| `dbt/tests/` | SQL-based quality checks that can fail the build |
| `dbt/models/semantics.yml` | Metric definitions (average price, negative hours...) |
| `tests/` | Python tests (parsers, dedup, DST, export contracts) |
| `analysis/` | The SQL behind the dashboard, DAX measures, and the findings |
| `exports/` | Parquet files + `report.html` (generated, not hand-written) |
| `powerbi/` | The dashboard file |
| `.github/workflows/` | The three cloud robots |
| `INCIDENTS.md` | The eight postmortems |
| `warehouse/` | The DuckDB database file itself (local only, not in git) |

---

## 5. The commands you can run

```bash
pip install -e ".[dbt]"                        # one-time setup
python -m ingest.cli load --sample             # fake but realistic data, no accounts
dbt build --project-dir dbt --profiles-dir dbt # run all the SQL + tests

# with a real ENTSO-E token in .env:
python -m ingest.cli refresh                   # download -> build -> export -> report
python -m ingest.cli bi headline               # print key analysis numbers
python -m ingest.cli report                    # redraw the HTML report
```

`refresh` is the one to remember: it brings everything current in about a
minute.

---

## 6. Questions you might be asking

**Why a database *file* (DuckDB) instead of a "real" database server?**
Because the data is small (a few MB) and the audience is one analyst. DuckDB
removes all the server setup and cost, and if this grew to a company scale,
the dbt SQL moves to a big database (Snowflake/Postgres) almost unchanged —
in fact, the Postgres validation is already automated in CI.

**Why is there weather in a price project?** Because the price *is* weather:
wind farms and solar panels determine how expensive the next hour is. The
correlations are in `analysis/findings.md` — windy hours are ~46% cheaper.

**What does "idempotent" mean?** Running the same step twice gives the same
result as running it once. It's the property that makes daily automation safe.

**What is a "revision"?** Sources sometimes correct numbers after publishing.
This project assumes every old value may be rewritten, and re-downloads recent
days on every run so corrections are always picked up.

**What is "provenance"?** A label on every number saying where it came from
(`price_source`, `weather_source`). When two sources disagree, you always know
which one you're looking at.

**Is the data real?** Yes — 58,000+ hours of real ENTSO-E prices and real
reanalysis weather, Jan 2020 through today. There is also a deterministic
*sample mode* (fake data with a fixed seed) so anyone can run the project
without registering for anything.

---

## 7. If you remember only three things

1. **The pipeline is idempotent and revision-aware** — it can be re-run any
   number of times, and it re-checks recent history because sources rewrite it.
2. **Every number carries its provenance** — you always know which source
   supplied it, and two independent sources are compared automatically.
3. **Quality is enforced by tests, not hope** — a red build means "do not
   trust the numbers yet," and the eight postmortems in INCIDENTS.md show the
   system catching real problems exactly as designed.

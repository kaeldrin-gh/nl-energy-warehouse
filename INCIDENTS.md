# INCIDENTS.md

Postmortems of the data problems this warehouse is designed against. Each incident describes the failure mode, how it was (or could have been) detected, and the design decision in this repo that exists because of it. New incidents go on top.

---

## INC-007: The hour that published three quarters of itself

**Category**: partial data / source quality

The first live ENTSO-E days exposed two failure modes in the wild, both caught by the cross-source alignment check before they reached a single BI visual. First: ENTSO-E PT15M documents sometimes omit individual MTU positions outright - for Aug 25 12:00 UTC the document contained positions 58, 59, 60 but skipped 54-57's neighbours, leaving one hour with 3 of its 4 quarters. Averaging the survivors produced 15.25 EUR/MWh where the true hourly price was 11.44 - a 36% bias from a document that looks perfectly healthy. Second: energy-charts.info served a transiently wrong value for a week-old hour (147.54 vs the correct 153.25, confirmed identical quarter data from both sources), then corrected itself within minutes - proving that even "settled" history deserves refetching.

**Detection**: `assert_cross_source_alignment`, on day one. Mean cross-source diff was EUR 0.06; two hours stood out at EUR 3.8 and EUR 5.7. Quarter-level API probes of both sources turned each into a precise diagnosis within minutes - the alignment test did exactly what INC-001 designed it for.

**Design response**:
- Hours without full MTU coverage (`points x mtu_minutes != 3600`) are **dropped at parse time**, never published as biased means; the provenance/fallback path supplies them from the cross-check source instead, so the hour is honest about where its number came from.
- energy-charts backfills are **chunked like ENTSO-E's** (30 days), so transient source errors are re-validated window-by-window on every run instead of baked into a single giant request.
- The 7-day revision lookback remains the convergence mechanism: both transient cases healed on refetch without manual intervention.

---

## INC-009: The day the primary source said 503

**Category**: upstream outage / blast radius

The scheduled batch failed for the first time: ENTSO-E's Transparency Platform
returned HTTP 503 for the full length of the retry ladder (~2.5 minutes of
patience), and because the entsoe loader raised mid-loop, the *entire* daily
batch died with it - energy-charts and Open-Meteo were never fetched, no build
ran, no export was produced, no artifact shipped. One source's bad day had
become the whole pipeline's bad day. The data was fine; the blast radius
wasn't.

**Detection**: the red run itself, within minutes of the failure (that part
worked exactly as designed). The gap: a partial batch is strictly better than
no batch, and the pipeline threw the partial away.

**Design response**:
- **Per-source isolation** in the incremental load: each source is wrapped so
  its failure is recorded, printed, and skipped - never allowed to cancel the
  others. The load still exits non-zero when any source fails, so automation
  keeps treating the run as failed and the alert fires.
- **Downstream steps run with `always()`**: build, freshness, export and the
  artifact upload execute even after a failed load, shipping whatever the
  healthy sources delivered. Provenance flags mark the gaps; freshness flags
  the staleness.
- **More patience at the edge**: the backoff ladder's base delay raised to 10s
  (~5 minutes total), enough to ride out short outages; anything longer is
  exactly what the isolation is for.
- The intended behavior split, stated plainly: **red run + shipped artifact**
  on a partial batch. A green run with silently missing sources would be the
  real failure.

---

## INC-008: The project that only spoke DuckDB

**Category**: portability / dialect drift

The README claimed "the models are plain SQL and were written to port." The first CI run against PostgreSQL disagreed - quietly, at compile time, before any data moved. Four idioms that DuckDB accepts without complaint:

1. `qualify row_number() over (...) = 1` for latest-revision dedup - Postgres has no `QUALIFY` clause.
2. Unquoted interval literals (`interval 7 day`) - Postgres requires `interval '7 day'`.
3. `datediff('hour', a, b)` - a DuckDB function; Postgres offers epoch extraction.
4. `round(double precision, 2)` - Postgres only defines two-argument `round` for `numeric`.

None of these produce wrong data on DuckDB; all four produce a broken project everywhere else. "Written to port" is a runtime property, not a hope.

**Detection**: a `validate-postgres` CI job - Postgres 17 as a service container, seeded with the same deterministic sample raw data, running the identical dbt project with `--target postgres`. Every dialect failure surfaced as a compile error at 13:24 UTC on the first push, not during a hypothetical Snowflake migration two years later.

**Design response**:
- Portable idioms adopted project-wide: subquery dedup instead of `QUALIFY`, quoted interval literals, epoch-based gap math.
- `round_numeric` adapter-dispatch macro: model SQL stays dialect-free; the shim maps to each engine's two-argument `round`.
- The validation gate is permanent: any future model change that quietly leans on a DuckDB-ism fails `validate-postgres` in CI.
- Timezone conversion (`timezone('Europe/Amsterdam', ...)`) survived both engines unchanged - the one place we got lucky, now documented rather than assumed.

---

## INC-005: The sanity test that rejected reality

**Category**: quality / test calibration

Two years of real Dutch day-ahead prices contain an €873/MWh scarcity hour (December 2024) and a −€498/MWh solar-glut hour (May 2026). The price-sanity test, calibrated against synthetic sample data, flagged both as impossible (`price < -200 or price > 500`) and failed the build on the first genuine backfill. A guardrail tuned to fake data does not just miss bugs - it actively rejects the truth, and worse, it trains you to distrust the one signal that was working correctly.

**Detection**: the failure itself. Querying the offending rows showed coherent multi-hour ramps around each extreme - market events, not unit errors (a ×100 bug produces 52,310 EUR/MWh spikes in isolated hours, not smooth December-evening curves).

**Design response**:
- Bounds now follow the exchange's own technical limits (SDAC/EUPHEMIA: −500 .. +4000 EUR/MWh) instead of observed sample variance. Anything outside the *legal* trading range is a bug by definition; everything inside it is somebody's problem to explain, not the test's job to veto.
- Rule of thumb adopted repo-wide: thresholds derived from fixtures are placeholders until they have survived contact with production data.

---

## INC-006: KNMI retired the endpoint the parser was built against

**Category**: source lifecycle

The KNMI uurgeg ingestion downloads decade-zips from `cdn.knmi.nl`. Mid-project those URLs began returning 403 across all ranges: KNMI migrated bulk distribution to its Data Platform, leaving the interactive HTML page up but silently killing the file URLs the parser targets. Nothing about our code changed - the source's contract simply expired. The pipeline fails loudly here (a hard 403 beats empty files parsed into an empty table), so the breakage was visible immediately rather than discovered via missing weather months later.

**Design response**:
- Migration to the KNMI Data Platform API is tracked as backlog work, with the existing uurgeg fixture tests kept as the parser contract the new fetcher must satisfy.
- Raw tables store KNMI rows exactly as published (local-hour labels), which keeps the staging-layer DST logic reusable regardless of where the bytes come from.
- Until then, marts run on price-only data through the provenance/fallback path ([INC-004](#inc-004-one-row-per-hour-wrong-number-inside)); weather columns surface as explicit nulls, not zeros.

---

## INC-004: One row per hour, wrong number inside

**Category**: granularity / integration contract

The first live call against energy-charts.info broke three assumptions that all committed fixtures and sample runs had baked in. First, it rejects ENTSO-E EIC zone codes with HTTP 400 instead of empty data - the two APIs describe the same bidding zone with different identifiers. Second, since Europe's day-ahead coupling switched to 15-minute market time units, the API returns four price points per delivery hour; truncating timestamps to the hour and de-duplicating kept only each hour's :45 quarter as *the* hourly price - row counts stay plausible, values look like prices, but every downstream aggregate quietly carries a quarter-slot sample instead of the hour's mean. Third, the live load path had simply never executed: sample mode stamps `fetched_at` itself, so the fact that the live loaders did not (crashing the insert against the raw table schema) went unnoticed until the first real backfill.

**Detection**: assert payload size against the requested window before trusting it - 193 points for 48 hours means 15-minute resolution, not noise. Longer term, `assert_cross_source_alignment` would surface a systematic diff once ENTSO-E goes live, but only after the bad data had shipped.

**Design response**:
- Zone-id translation lives in one explicit map (`ZONE_MAP`) at the fetch boundary; neither the CLI nor the models know the two vocabularies differ.
- Sub-hourly points are averaged into their containing hour at parse time, matching the warehouse's declared grain (raw tables keyed on `hour_utc`) instead of the API's.
- Parsing is split from HTTP (`parse_price_payload`) so this behavior has unit tests that fail without network access.
- Live window loaders stamp `fetched_at` at ingestion time; parsers stay pure so their column contracts stay unit-testable.
- Resolved when ENTSO-E access arrived: the `PT15M` path now averages sub-hourly points into their hour exactly like energy-charts, covered by the 15-minute fixture test.

---

## INC-003: The price you fetched yesterday is not the price published today

**Category**: late-arriving revision

ENTSO-E publishes day-ahead prices around 12:45 CET for the next day, but does not treat publication as immutable. Grid events and re-run auctions cause retroactive corrections to already-published hours. An append-only pipeline that skips hours it "already has" will permanently store stale values and never learn about the correction.

**Detection**: cross-source comparison. energy-charts.info republishes ENTSO-E data independently, so a sustained divergence between the two sources is a revision alarm, not a bug. Enforced as `assert_cross_source_alignment`.

**Design response**:
- Ingestion is **revision-aware**: every run re-fetches a fixed lookback window (default 7 days) regardless of watermarks and upserts via `INSERT OR REPLACE` on the natural key (`hour_utc`), so the newest fetch wins.
- `fetched_at` is carried through staging, so any value in a mart is traceable to the run that last asserted it.
- Watermarks are used to bound the *forward* edge of the window, never to decide that a past hour is "done".

---

## INC-002: KNMI hours are 1-24 local, and local time is a lie twice a year

**Category**: timezone / DST

KNMI uurgegevens label hours 1-24 in local wall-clock time (hour H = the interval ending at H:00). Mapping those labels to UTC naively breaks twice a year:

- **Spring**: 02:00 local does not exist. A `date + H hours` formula produces an hour that never happened.
- **Autumn**: 02:00-03:00 local occurs twice. A naive conversion maps two different physical hours onto one UTC timestamp and one physical hour gets dropped.

**Design response**:
- Raw KNMI rows are stored **as published** (local labels, `interval_end_local`) with no conversion at ingestion time.
- Conversion to UTC happens once, in `stg_knmi__hourly_weather`, using named-zone arithmetic (`timezone('Europe/Amsterdam', ...)`) instead of fixed +1/+2 offsets, so DST is handled by the calendar, not by a hardcoded constant.
- The staging model is the single place this convention exists; everything downstream joins on `interval_start_utc`.

---

## INC-001: Two sources, one truth, zero tolerance policy

**Category**: reconciliation

The same physical quantity (Dutch day-ahead price) is available from ENTSO-E directly and from energy-charts.info. Treating them as interchangeable is how silent drift ships: a unit error, a timezone shift, or a revision on one side shows up as a small unexplained difference nobody owns.

**Design response**:
- energy-charts is ingested as a first-class source and joined into `fct_hourly_price_weather` with an explicit `price_diff_eur` column.
- `assert_cross_source_alignment` fails the build when recent prices diverge by more than EUR 2/MWh, which is loose enough to ignore rounding and strict enough to catch unit or offset bugs.
- The test is scoped to recent data on purpose: old disagreements are history to document, not builds to break.

---

## Template

```
## INC-00X: <one-line failure summary>

**Category**: <late-arriving data | timezone | reconciliation | quality | ...>

<What happened / what would happen without the fix. Concrete, with numbers where possible.>

**Detection**: <how you would know>

**Design response**:
- <decision in the repo>
```

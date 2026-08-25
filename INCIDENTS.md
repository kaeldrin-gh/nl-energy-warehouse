# INCIDENTS.md

Postmortems of the data problems this warehouse is designed against. Each incident describes the failure mode, how it was (or could have been) detected, and the design decision in this repo that exists because of it. New incidents go on top.

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

# Findings: what actually drives the Dutch hourly power price?

Every number below is computed from this repo's own marts — 58,319 delivery
hours, Jan 2020 → Aug 2026 (ENTSO-E primary, energy-charts cross-checked,
Open-Meteo ERA5 weather). Reproduce with `analysis/bi_queries.sql` or the
warehouse directly. Weather analysis covers hours with a weather match
(99.99%).

## 1 · The duck curve is real and it is priced

Average price by local hour (EUR/MWh, all years):

| night (02-04) | morning peak (08) | solar dip (13) | evening peak (19) |
| ---: | ---: | ---: | ---: |
| €88.5 | €128.7 | **€72.2** | **€147.1** |

The evening peak averages **2.0× the midday trough**. The cheapest five hours
of the day are 11:00–15:00; the most expensive three are 18:00–20:00.

## 2 · Wind is the strongest single weather driver

Correlation with price, all hours: temp **−0.05**, radiation **−0.18**, wind
**−0.25**. Winter months sharpen it: wind **−0.32**, temp **−0.19** (heating
demand).

The wind effect is easiest to see as regimes rather than correlation:

| regime | hours | avg price | share of hours that are negative |
| --- | ---: | ---: | ---: |
| wind < 6 m/s ("calm") | 50,305 | €113.0 | 2.4% |
| wind ≥ 6 m/s ("windy") | 8,007 | **€60.6** | **9.3%** |

Windy hours are **46% cheaper on average**, and 3.9× more likely to be
negative. Within solar hours (10:00–15:00 local), radiation's correlation
with price is **−0.31**.

## 3 · Negative prices are a weekend-solar phenomenon that is exploding

Negative-price hours by year:

| 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 97 | 70 | 85 | 316 | 458 | 584 | 347 |

*2026 is Jan–Aug only.

Two structural facts:

- **Hour of day**: 63% land between 12:00 and 16:00 local (13:00 and 14:00
  lead with 329 each) — solar glut, exactly where the duck curve dips.
- **Day of week**: **Sundays (722) and Saturdays (437)** carry 63% of all
  negative hours. Weekend midday averages **€49.7 with a 22.5% negative rate**,
  versus €90.6 / 6.7% on weekday midday. Solar output does not care about the
  calendar; industrial demand does.

## 4 · Six years, three market eras

| year | avg (EUR/MWh) | min | max |
| ---: | ---: | ---: | ---: |
| 2020 | 32.2 | −79.2 | 200.0 |
| 2021 | 103.0 | −66.2 | 620.0 |
| 2022 | **241.9** | −222.4 | 871.0 |
| 2023 | 95.8 | **−500.0** | 463.8 |
| 2024 | 77.3 | −200.0 | **873.0** |
| 2025 | 86.8 | −350.0 | 523.5 |
| 2026* | 102.6 | −498.4 | 799.4 |

- **2020**: Covid demand collapse — the cheapest year on record.
- **2022**: the gas crisis, averaging **7.5× 2020**; the Aug 29, 2022 evening
  peak (€871/MWh) held the record until...
- **Dec 12, 2024**: a continental scarcity event pushed a single Dutch hour to
  **€873/MWh** — the current record.
- **Jul 2, 2023**: the first hours at the exchange's −€500 floor (three
  consecutive hours), repeated at −€498.4 on May 1, 2026. The price floor is no
  longer theoretical; it has been touched.

## 5 · So when is it cheap?

Combine the three effects: **weekend midday (12:00–15:00) on a windy day is the
cheapest segment of the European electricity week** — average prices there run
at roughly half the evening-peak weekday price. The pipeline's
`mart_daily_summary` exposes `negative_price_hours` per day, which since 2024
is the practical "free electricity" calendar: expect it on sunny, windy
weekends, and do not expect it at all on a calm winter Wednesday evening.

## Caveats

- Weather from ERA5 reanalysis (Open-Meteo grid cell at De Bilt), not station
  observations, while INC-006 is open — magnitudes are reanalysis-consistent;
  correlations could shift slightly against true KNMI observations.
- Correlations here are univariate; they describe marginal associations, not a
  causal model. Wind ≥ 6 m/s is a modelling threshold chosen for readability,
  not a fitted breakpoint.
- Prices are EUR/MWh day-ahead, delivered hourly; 15-minute market time units
  are averaged to the hour at ingestion (INC-004).

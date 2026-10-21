# Model card: revenue forecast

`src/analytics/forecast.py`, run by `analytics score`, shown on the **Forecast** page (permission
`analytics:models.view`) and at `GET /api/models/revenue-forecast`.

## What it forecasts

Revenue per business and line of business (`mart_revenue_monthly`: credits minus debits on revenue
accounts, by posting month), monthly, **six months ahead**.

## Data

- **Input:** monthly totals per business and line of business, nothing finer. No patient, provider or
  journal line reaches any model.
- **Period:** from the first month with revenue to the **last complete month**: the month of the latest
  finance extract is left out, since it may not be finished. Months without revenue inside that span
  count as zero.
- **Minimum:** 18 complete months (a year to learn the season, six months to check it). A shorter series
  is listed as "too short" and gets no forecast.

## Candidates

| Model | Needs | What it is |
|---|---|---|
| `seasonal-naive` (baseline) | 1 month | The same month a year earlier (the last value under a year) |
| `ets` | 8 months | Exponential smoothing, damped additive trend; additive season from 24 months (statsmodels) |
| `sarima` | 30 months | SARIMA(0,1,1)(0,1,1)12, the "airline" model (statsmodels) |
| `gradient-boosting` | 24 months | Histogram gradient boosting on last month, same month last year, time and month of year, forecasting one month at a time (scikit-learn) |

A model whose minimum is longer than the first backtest origin is not tried on that series.

## How it is chosen

- **Rolling-origin backtest:** the latest six origins (fewer when the series is short) that leave six
  months to compare with. At each origin the model is fitted on the months before it and forecasts six.
- **Metrics,** stored per run in `ml.backtest`: MAE; MAPE (months with zero revenue left out); **MASE**,
  the mean absolute error divided by the in-sample error of the seasonal naive on the same training
  months, averaged over origins. MASE below 1: better than "same month last year" was in-sample.
- **Choice:** the lowest MASE. The baseline is kept unless another model is **strictly** better; a flat
  series (MASE undefined) keeps the baseline. The chosen model is then fitted on the whole series.
- **Band:** per horizon step, the 80th percentile of the chosen model's absolute backtest errors around
  the forecast. With six origins this says how far off the model has been lately; it is **not** a
  probability interval.

## Tested on

Synthetic series only (`tests/test_forecast.py`, `tests/ml_warehouse.py`): an exactly repeating year
(the baseline is perfect and kept), a season with a trend and noise (a model beats the baseline and the
forecast continues the trend), a short series (only the baseline and ETS are tried), a flat series, a
model that fails at one origin (left out), months without revenue.

## Limits

- **Not run on real books yet.** FinancePowerApp holds one month (October 2026), so every real series is
  too short; nothing here has been checked against real revenue.
- Monthly only; no holidays, fee-schedule changes, new physicians or closures. A one-off month (a large
  correction) moves the forecast.
- Six origins is a small backtest: MASE differences of a few hundredths between models are noise.
- Each series is forecast alone: the businesses' and lines' forecasts are not reconciled to a total.
- Refunds and adjustments booked to revenue accounts are in the history, so a month can be low or even
  negative, and so can a forecast.

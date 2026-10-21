# Model card: remittance anomalies

`src/analytics/anomalies.py`, run by `analytics score`, shown on the **OHIP** page ("Unusual months",
every `dashboard.view` user of the clinic) and at `GET /api/finance/ohip-anomalies`.

## What it flags

A provider (OHIP billing number) whose **short-paid** or **refused** rate in a month is far above the
same provider's own earlier months.

## Data

- `mart_ohip_provider_monthly`: per business, billing number and posting month, OHIP billed (journal) and
  the short-paid and refused adjustments on OHIP party lines. Rate = amount / billed.
- Complete months only (the month of the latest extract is left out). Months with nothing billed are
  not scored and not part of anyone's history. Lines without a billing number ("none") are not a
  provider and are not scored.
- Amounts per provider and month only: no claim, patient or health number.

## Method

For a month with at least **6 earlier billed months** of the same provider:

- robust z = 0.6745 × (rate − median) / MAD, over the **earlier months only** (Iglewicz and Hoaglin), so
  a month is judged by what was known before it and a run of bad months is flagged from its first month;
- when the earlier months never varied (MAD 0), 1.2533 × the mean absolute deviation; when that is 0
  too, any rate above the usual one counts as infinitely far ("Never varied before" on the page);
- **flagged** when all three hold: z ≥ 3.5; the rate is at least **2 percentage points** above the usual
  (median) rate; at least **$500** billed that month. Only a higher rate is flagged.

Every scored provider-month is stored per run in `ml.remittance_score` (rate, usual rate, spread, z,
months of history, flagged), so the threshold can be revisited from what was scored.

## Tested on

Synthetic provider-months (`tests/test_anomalies.py`, `tests/ml_warehouse.py`): a spike far above a
steady 1-2% (flagged, with its numbers), a lower rate (never), a small month and a small difference (not
flagged), a history of zeros, too little history, later months not changing the score of an earlier one,
refused on its own, the unfinished month.

## Limits

- **Not run on real remittances yet** (one month of books); the thresholds (3.5, 2 points, $500) are
  conventional starting points, not tuned on this clinic's data.
- By posting month of the journal, not by the remittance advice's payment date: a late remittance can
  land in another month than its claims.
- A provider's first six billed months are never scored; a new provider can be short-paid unnoticed.
- One provider at a time: a change that hits every provider (a fee schedule) shows as many flags, not
  as one cause.

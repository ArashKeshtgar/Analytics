"""Remittance anomalies (phase 5): a provider's short-paid or refused rate in a month, against the
same provider's own earlier months.

The rate is short-paid (or refused) divided by billed, from `mart_ohip_provider_monthly`. A month is
scored when the provider has at least `MIN_HISTORY` earlier months with billing; its robust z-score
is 0.6745 x (rate - median) / MAD of those months (Iglewicz and Hoaglin). It is flagged when all of:

- z is at least `Z_FLAG` (3.5): far above the provider's usual rate. Only higher is flagged; a lower
  rate is not a problem to look into.
- the rate is at least `MIN_POINTS` (2 percentage points) above the usual: a provider who is never
  short-paid is otherwise flagged for any cent.
- billed is at least `MIN_BILLED` ($500): a rate on a tiny month says little.

When the history does not vary at all (MAD zero) the mean absolute deviation is used (x 1.2533,
its consistency factor for a normal distribution); when that is zero too, any rate above the usual
one counts as infinitely far, and the other two rules decide.

Only earlier months are used, so a month is judged by what was known before it, and a run of bad
months is flagged from its first month on.
"""

import math
import statistics
from dataclasses import dataclass
from datetime import date

MIN_HISTORY = 6
Z_FLAG = 3.5
MIN_POINTS = 0.02
MIN_BILLED = 500.0
MEASURES = ("short_paid", "refused")


@dataclass(frozen=True)
class ProviderMonth:
    business_id: int
    provider: str
    month: date
    billed: float
    short_paid: float
    refused: float


@dataclass(frozen=True)
class Score:
    business_id: int
    provider: str
    month: date
    measure: str  # short_paid or refused
    billed: float
    amount: float
    rate: float
    usual_rate: float  # median of the earlier months
    spread: float  # the MAD (or the scaled mean absolute deviation) used
    history_months: int
    z: float  # math.inf when the history never varied and the rate is above it
    flagged: bool


def robust_z(value: float, history: list[float]) -> tuple[float, float, float]:
    """(z, median, spread) of `value` against `history`."""
    median = statistics.median(history)
    mad = statistics.median(abs(v - median) for v in history)
    if mad > 0:
        return 0.6745 * (value - median) / mad, median, mad
    mean_ad = statistics.fmean(abs(v - median) for v in history)
    if mean_ad > 0:
        spread = 1.2533 * mean_ad
        return 0.6745 * (value - median) / spread, median, spread
    if value > median:
        return math.inf, median, 0.0
    return (-math.inf if value < median else 0.0), median, 0.0


def score(rows: list[ProviderMonth], through: date | None = None) -> list[Score]:
    """Scores every provider-month with enough history (and billing), oldest first."""
    by_provider: dict[tuple[int, str], list[ProviderMonth]] = {}
    for r in rows:
        # "none" collects OHIP lines without a billing number: not one provider's history.
        if r.provider != "none" and (through is None or r.month <= through):
            by_provider.setdefault((r.business_id, r.provider), []).append(r)
    out: list[Score] = []
    for months in by_provider.values():
        months.sort(key=lambda r: r.month)
        billed = [r for r in months if r.billed > 0]
        for i, current in enumerate(billed):
            earlier = billed[:i]
            if len(earlier) < MIN_HISTORY:
                continue
            for measure in MEASURES:
                amount = getattr(current, measure)
                rate = amount / current.billed
                history = [getattr(r, measure) / r.billed for r in earlier]
                z, usual, spread = robust_z(rate, history)
                out.append(
                    Score(
                        business_id=current.business_id,
                        provider=current.provider,
                        month=current.month,
                        measure=measure,
                        billed=current.billed,
                        amount=amount,
                        rate=rate,
                        usual_rate=usual,
                        spread=spread,
                        history_months=len(earlier),
                        z=z,
                        flagged=z >= Z_FLAG
                        and rate - usual >= MIN_POINTS
                        and current.billed >= MIN_BILLED,
                    )
                )
    out.sort(key=lambda s: (s.business_id, s.provider, s.month, s.measure))
    return out

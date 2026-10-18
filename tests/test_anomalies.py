"""Remittance anomalies: a provider's month against the same provider's earlier months."""

import math
from datetime import date

import pytest

from analytics.anomalies import MIN_HISTORY, ProviderMonth, Score, robust_z, score
from analytics.forecast import month_add

START = date(2026, 1, 1)


def months(short_rates: list[float], billed: float = 10_000.0, provider: str = "123456"):
    return [
        ProviderMonth(1, provider, month_add(START, i), billed, rate * billed, 0.0)
        for i, rate in enumerate(short_rates)
    ]


def short_paid(scores: list[Score]) -> list[Score]:
    return [s for s in scores if s.measure == "short_paid"]


def test_robust_z_uses_the_median_and_mad() -> None:
    z, median, spread = robust_z(10.0, [1.0, 2.0, 3.0, 4.0, 5.0])
    assert (median, spread) == (3.0, 1.0)
    assert z == pytest.approx(0.6745 * 7)


def test_robust_z_when_the_history_hardly_varies() -> None:
    z, _, spread = robust_z(0.1, [0.0, 0.0, 0.0, 0.0, 0.0, 0.03])  # MAD 0, mean deviation not
    assert spread == pytest.approx(1.2533 * 0.005) and z > 3.5
    assert robust_z(0.05, [0.0] * 6)[0] == math.inf
    assert robust_z(0.0, [0.0] * 6)[0] == 0.0


def test_a_month_far_above_the_providers_usual_rate_is_flagged_with_its_numbers() -> None:
    rates = [0.01, 0.015, 0.012, 0.02, 0.011, 0.014, 0.013, 0.10]
    flagged = [s for s in short_paid(score(months(rates))) if s.flagged]
    assert len(flagged) == 1
    s = flagged[0]
    assert s.month == month_add(START, 7) and s.rate == pytest.approx(0.10)
    assert s.usual_rate == pytest.approx(0.013) and s.history_months == 7
    assert s.amount == pytest.approx(1000.0) and s.z >= 3.5


def test_a_lower_rate_is_never_flagged() -> None:
    rates = [0.05, 0.06, 0.055, 0.05, 0.06, 0.052, 0.0]
    assert not any(s.flagged for s in score(months(rates)))


def test_a_small_month_or_a_small_difference_is_not_flagged() -> None:
    rates = [0.01, 0.012, 0.011, 0.01, 0.012, 0.011, 0.20]
    assert not any(s.flagged for s in score(months(rates, billed=400.0)))
    # Never short-paid, then 1%: infinitely far from a flat history, but under 2 points.
    tiny = short_paid(score(months([0.0] * 6 + [0.01])))
    assert tiny[-1].z == math.inf and not tiny[-1].flagged
    big = short_paid(score(months([0.0] * 6 + [0.05])))
    assert big[-1].flagged


def test_a_month_needs_six_earlier_billed_months_and_only_earlier_ones_count() -> None:
    rates = [0.01] * MIN_HISTORY + [0.10, 0.10, 0.10]
    scores = short_paid(score(months(rates)))
    assert [s.month for s in scores] == [month_add(START, i) for i in range(6, 9)]
    assert scores[0].flagged and scores[0].history_months == 6
    # The same first bad month, whatever came after it.
    again = short_paid(score(months(rates[:7])))[0]
    assert (again.z, again.usual_rate) == (scores[0].z, scores[0].usual_rate)


def test_months_without_billing_and_the_unnamed_provider_are_not_scored() -> None:
    rows = months([0.01] * 6 + [0.10])
    rows.insert(3, ProviderMonth(1, "123456", date(2025, 6, 1), 0.0, 50.0, 0.0))
    rows += months([0.01] * 6 + [0.10], provider="none")
    scores = short_paid(score(rows))
    assert len(scores) == 1 and scores[0].provider == "123456" and scores[0].history_months == 6


def test_months_after_the_data_end_are_left_out() -> None:
    rows = months([0.01] * 6 + [0.10])
    assert score(rows, through=month_add(START, 5)) == []
    assert len(short_paid(score(rows, through=month_add(START, 6)))) == 1


def test_refused_is_scored_on_its_own() -> None:
    rows = [
        ProviderMonth(1, "999", month_add(START, i), 10_000.0, 100.0, 50.0 if i < 6 else 900.0)
        for i in range(7)
    ]
    flagged = [s for s in score(rows) if s.flagged]
    assert [(s.measure, s.rate) for s in flagged] == [("refused", pytest.approx(0.09))]

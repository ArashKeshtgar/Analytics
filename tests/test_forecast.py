"""Revenue forecasts: the candidates, the rolling-origin backtest and the choice (synthetic)."""

import math
from datetime import date

import numpy as np
import pytest

from analytics.forecast import (
    BASELINE,
    HORIZON,
    MODELS,
    Backtest,
    Model,
    backtest,
    choose,
    forecast_series,
    last_complete_month,
    mase_scale,
    month_add,
    monthly_series,
    origins,
    seasonal_naive,
)


def seasonal(months: int, trend: float = 0.0, noise: float = 0.0, seed: int = 1) -> np.ndarray:
    """A clinic-like year (quiet summer, busy winter) around 10,000, with trend and noise."""
    rng = np.random.default_rng(seed)
    pattern = np.array([1.1, 1.05, 1.0, 0.95, 0.9, 0.8, 0.75, 0.8, 1.0, 1.05, 1.1, 0.95])
    t = np.arange(months)
    return 10_000 * pattern[t % 12] + trend * t + rng.normal(0, noise, months)


def test_seasonal_naive_repeats_last_year_and_the_last_value_under_a_year() -> None:
    y = np.arange(1.0, 25.0)
    assert list(seasonal_naive(y, 3)) == [13.0, 14.0, 15.0]
    assert list(seasonal_naive(y, 14))[12:] == [13.0, 14.0]
    assert list(seasonal_naive(np.array([4.0, 5.0]), 2)) == [5.0, 5.0]


def test_backtest_origins_are_the_latest_that_leave_a_full_horizon() -> None:
    assert origins(18) == [12]
    assert origins(40) == [29, 30, 31, 32, 33, 34]
    assert origins(17) == []


def test_mase_unit_is_the_in_sample_seasonal_naive_error() -> None:
    y = np.array([float(v) for v in range(26)])  # each month is 12 more than a year earlier
    assert mase_scale(y) == 12.0
    assert mase_scale(np.array([1.0, 3.0, 2.0])) == 1.5  # under a year: the naive


def test_an_exactly_repeating_year_keeps_the_baseline() -> None:
    result = forecast_series(seasonal(48))
    base = next(b for b in result.backtests if b.model == BASELINE)
    assert base.mae == pytest.approx(0, abs=1e-9)
    assert result.chosen == BASELINE  # nothing can be strictly better than perfect
    assert result.forecast == pytest.approx(list(seasonal(54)[48:]))


def test_with_a_trend_a_model_beats_the_baseline_and_says_by_how_much() -> None:
    y = seasonal(48, trend=150, noise=150)
    result = forecast_series(y)
    assert result.status == "forecast"
    assert {b.model for b in result.backtests} == {m.name for m in MODELS}
    assert all(b.origins == 6 for b in result.backtests)
    by_name = {b.model: b for b in result.backtests}
    assert result.chosen != BASELINE
    chosen_mase = by_name[result.chosen].mase
    base_mase = by_name[BASELINE].mase
    assert chosen_mase is not None and base_mase is not None and chosen_mase < base_mase
    # The forecast continues the trend: above the same months a year earlier.
    assert np.mean(result.forecast) > np.mean(y[36:42])
    assert len(result.forecast) == HORIZON
    assert all(
        lo <= f <= hi for lo, f, hi in zip(result.lower, result.forecast, result.upper, strict=True)
    )


def test_a_series_shorter_than_eighteen_months_gets_no_forecast() -> None:
    result = forecast_series(seasonal(17))
    assert (result.status, result.chosen, result.forecast, result.backtests) == (
        "too-short",
        None,
        [],
        [],
    )


def test_a_model_is_only_compared_when_the_history_is_long_enough_for_it() -> None:
    names = {b.model for b in forecast_series(seasonal(20, noise=50)).backtests}
    assert names == {BASELINE, "ets"}  # SARIMA needs 30 months, gradient boosting 24


def test_a_flat_series_has_no_mase_and_keeps_the_baseline() -> None:
    result = forecast_series(np.full(30, 500.0))
    base = next(b for b in result.backtests if b.model == BASELINE)
    assert base.mase is None and base.mape == 0
    assert result.chosen == BASELINE and result.forecast == [500.0] * HORIZON


def test_a_model_that_fails_at_one_origin_is_left_out() -> None:
    calls = {"n": 0}

    def flaky(y: np.ndarray, h: int) -> np.ndarray | None:
        calls["n"] += 1
        return None if calls["n"] == 3 else seasonal_naive(y, h)

    assert backtest(seasonal(40), Model("flaky", 1, flaky)) is None


def test_mape_skips_months_with_no_revenue() -> None:
    y = seasonal(30)
    y[-1] = 0.0
    b = backtest(y, MODELS[0])
    assert b is not None and b.mape is not None and math.isfinite(b.mape)


def test_the_choice_needs_a_strictly_better_mase() -> None:
    def bt(name: str, mase: float | None) -> Backtest:
        return Backtest(name, 6, 1.0, 1.0, mase)

    assert choose([bt(BASELINE, 1.0), bt("ets", 0.8), bt("sarima", 0.9)]) == "ets"
    assert choose([bt(BASELINE, 1.0), bt("ets", 1.0)]) == BASELINE
    assert choose([bt(BASELINE, None), bt("ets", 0.5)]) == BASELINE


def test_months_without_revenue_are_zero_and_the_unfinished_month_is_left_out() -> None:
    rows = [(date(2026, 1, 1), 10.0), (date(2026, 3, 1), 5.0), (date(2026, 3, 1), 1.0)]
    rows.append((date(2026, 5, 1), 99.0))
    through = last_complete_month(date(2026, 5, 12))
    assert through == date(2026, 4, 1)
    found = monthly_series(rows, through)
    assert found is not None
    first, y = found
    assert first == date(2026, 1, 1) and list(y) == [10.0, 0.0, 6.0, 0.0]
    assert monthly_series([(date(2026, 5, 1), 1.0)], through) is None
    assert month_add(date(2026, 11, 1), 3) == date(2027, 2, 1)

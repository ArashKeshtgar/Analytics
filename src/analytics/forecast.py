"""Revenue forecasts (phase 5): per business and line of business, monthly, 6 months ahead.

Candidates, simplest first: seasonal naive (the baseline), ETS, SARIMA, gradient boosting on lags
and calendar features. Each is scored by a rolling-origin backtest (MAE, MAPE, MASE); the series
gets the candidate with the lowest MASE, and the baseline unless something beats it. A candidate
needs a minimum history (see `Model.min_train`) and is left out of a series that is shorter.

Input is monthly totals from `mart_revenue_monthly`; nothing below a business, line and month is
read, so no model ever sees a patient, a provider or a single journal line.
"""

import math
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from numpy.typing import NDArray

HORIZON = 6
SEASON = 12
ORIGINS = 6  # backtest origins, the latest ones that leave a full horizon to compare with
MIN_TRAIN = 12  # months before the first origin: a series needs MIN_TRAIN + HORIZON months

Series = NDArray[np.float64]
Forecaster = Callable[[Series, int], Series | None]


@dataclass(frozen=True)
class Model:
    name: str
    min_train: int  # months of history the model needs to be fitted at all
    fit: Forecaster


def seasonal_naive(y: Series, h: int) -> Series:
    """The same month a year earlier; the last value when there is less than a year."""
    if len(y) >= SEASON:
        return np.array([y[len(y) - SEASON + (i % SEASON)] for i in range(h)], dtype=float)
    return np.full(h, y[-1], dtype=float)


def ets(y: Series, h: int) -> Series | None:
    """Exponential smoothing: damped additive trend, additive season from two years of history."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    seasonal = "add" if len(y) >= 2 * SEASON else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = ExponentialSmoothing(
                y,
                trend="add",
                damped_trend=True,
                seasonal=seasonal,
                seasonal_periods=SEASON if seasonal else None,
                initialization_method="estimated",
            ).fit()
            out = np.asarray(model.forecast(h), dtype=float)
        except (ValueError, np.linalg.LinAlgError):
            return None
    return out if np.all(np.isfinite(out)) else None


def sarima(y: Series, h: int) -> Series | None:
    """The "airline" model, SARIMA(0,1,1)(0,1,1)12."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = SARIMAX(
                y,
                order=(0, 1, 1),
                seasonal_order=(0, 1, 1, SEASON),
                enforce_stationarity=False,
                enforce_invertibility=False,
            ).fit(disp=False)
            out = np.asarray(model.forecast(h), dtype=float)
        except (ValueError, np.linalg.LinAlgError):
            return None
    return out if np.all(np.isfinite(out)) else None


def _features(history: list[float], t: int) -> list[float]:
    """For month index t: last month, the same month a year earlier, time, month of year."""
    month = t % SEASON
    return [
        history[t - 1],
        history[t - SEASON],
        float(t),
        math.sin(2 * math.pi * month / SEASON),
        math.cos(2 * math.pi * month / SEASON),
    ]


def gradient_boosting(y: Series, h: int) -> Series | None:
    """Gradient boosting on lags and calendar features, forecasting one month at a time."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    history = [float(v) for v in y]
    rows = range(SEASON, len(history))
    x = np.array([_features(history, t) for t in rows])
    target = np.array([history[t] for t in rows])
    model = HistGradientBoostingRegressor(
        max_iter=200, learning_rate=0.05, min_samples_leaf=3, random_state=0
    )
    model.fit(x, target)
    out = []
    for _ in range(h):
        value = float(model.predict(np.array([_features(history, len(history))]))[0])
        out.append(value)
        history.append(value)
    return np.array(out, dtype=float)


BASELINE = "seasonal-naive"
MODELS = [
    Model(BASELINE, 1, lambda y, h: seasonal_naive(y, h)),
    Model("ets", 8, ets),
    Model("sarima", 2 * SEASON + 6, sarima),
    Model("gradient-boosting", 2 * SEASON, gradient_boosting),
]


@dataclass
class Backtest:
    model: str
    origins: int
    mae: float | None
    mape: float | None  # percent; None when every actual was zero
    mase: float | None  # None when the in-sample seasonal naive error is zero (a flat series)
    errors: list[list[float]] = field(default_factory=list)  # per origin, per horizon step


def mase_scale(train: Series) -> float:
    """In-sample mean absolute error of the seasonal naive (naive under a year): MASE's unit."""
    m = SEASON if len(train) > SEASON else 1
    return float(np.mean(np.abs(train[m:] - train[:-m])))


def origins(n: int, horizon: int = HORIZON) -> list[int]:
    """Training lengths of the backtest: the last ORIGINS that leave `horizon` months to check."""
    last = n - horizon
    return [o for o in range(max(MIN_TRAIN, last - ORIGINS + 1), last + 1)]


def backtest(y: Series, model: Model, horizon: int = HORIZON) -> Backtest | None:
    """Rolling origin: fit on y[:o], forecast `horizon` months, compare with y[o:o+horizon].

    None when the model cannot be fitted at every origin (too little history, or a failed fit):
    a model is only compared on the same origins as the others.
    """
    points = origins(len(y), horizon)
    if not points or points[0] < model.min_train:
        return None
    errors: list[list[float]] = []
    scaled: list[float] = []
    pct: list[float] = []
    for o in points:
        predicted = model.fit(y[:o], horizon)
        if predicted is None:
            return None
        actual = y[o : o + horizon]
        e = actual - predicted
        errors.append([float(v) for v in e])
        scale = mase_scale(y[:o])
        scaled.append(float(np.mean(np.abs(e))) / scale if scale > 0 else math.nan)
        pct.extend(float(abs(err) / abs(a)) for err, a in zip(e, actual, strict=True) if a != 0)
    flat = [abs(v) for row in errors for v in row]
    mase = float(np.mean(scaled))
    return Backtest(
        model=model.name,
        origins=len(points),
        mae=float(np.mean(flat)),
        mape=100 * float(np.mean(pct)) if pct else None,
        mase=None if math.isnan(mase) else mase,
        errors=errors,
    )


@dataclass
class SeriesResult:
    months: int
    status: str  # "forecast" or "too-short"
    chosen: str | None
    backtests: list[Backtest]
    forecast: list[float]
    lower: list[float]
    upper: list[float]


def choose(backtests: list[Backtest]) -> str:
    """Lowest MASE; the baseline unless another model is strictly better than it."""
    base = next(b for b in backtests if b.model == BASELINE)
    best = base
    for b in backtests:
        if b.mase is not None and (best.mase is None or b.mase < best.mase):
            best = b
    if base.mase is None or best.mase is None or best.mase >= base.mase:
        return BASELINE
    return best.model


def forecast_series(y: Series, horizon: int = HORIZON) -> SeriesResult:
    """Backtest every candidate, choose one, fit it on the whole series and forecast.

    The band is rough: per horizon step, the 80th percentile of the chosen model's absolute
    backtest errors, around the forecast. With six origins it says how wrong the model has been
    lately, not a probability.
    """
    if len(y) < MIN_TRAIN + horizon:
        return SeriesResult(len(y), "too-short", None, [], [], [], [])
    results = [b for m in MODELS if (b := backtest(y, m, horizon)) is not None]
    chosen = choose(results)
    model = next(m for m in MODELS if m.name == chosen)
    predicted = model.fit(y, horizon)
    if predicted is None:  # fitted at every origin but not on the whole series: fall back
        chosen, predicted = BASELINE, seasonal_naive(y, horizon)
    errors = next(b for b in results if b.model == chosen).errors
    width = [float(np.quantile([abs(row[k]) for row in errors], 0.8)) for k in range(horizon)]
    values = [float(v) for v in predicted]
    return SeriesResult(
        months=len(y),
        status="forecast",
        chosen=chosen,
        backtests=results,
        forecast=values,
        lower=[v - w for v, w in zip(values, width, strict=True)],
        upper=[v + w for v, w in zip(values, width, strict=True)],
    )


def month_add(month: date, n: int) -> date:
    index = month.year * 12 + month.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def last_complete_month(as_of: date) -> date:
    """The month before `as_of`'s: the month of the extract may not be finished."""
    return month_add(date(as_of.year, as_of.month, 1), -1)


def monthly_series(rows: list[tuple[date, float]], through: date) -> tuple[date, Series] | None:
    """Monthly values from the first month with revenue to `through`, missing months as zero."""
    kept = [(m, v) for m, v in rows if m <= through]
    if not kept:
        return None
    first = min(m for m, _ in kept)
    by_month: dict[date, float] = {}
    for m, v in kept:
        by_month[m] = by_month.get(m, 0.0) + v
    n = (through.year - first.year) * 12 + through.month - first.month + 1
    return first, np.array([by_month.get(month_add(first, i), 0.0) for i in range(n)], dtype=float)

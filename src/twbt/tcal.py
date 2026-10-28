"""Trading calendar helpers and point-in-time revenue availability."""
from __future__ import annotations
import numpy as np, pandas as pd


def next_trading_day_on_or_after(dates: pd.DatetimeIndex, d) -> pd.Timestamp:
    i = dates.searchsorted(pd.Timestamp(d), side="left")
    return dates[i] if i < len(dates) else pd.NaT


def revenue_available_date(rev_year: int, rev_month: int, dates: pd.DatetimeIndex, day: int = 11) -> pd.Timestamp:
    """No announcement date in the data -> day `day` of the following month, rolled to the next trading day."""
    y, m = (rev_year + 1, 1) if rev_month == 12 else (rev_year, rev_month + 1)
    return next_trading_day_on_or_after(dates, pd.Timestamp(y, m, day))


def add_available_date(rev: pd.DataFrame, dates: pd.DatetimeIndex, day: int = 11) -> pd.DataFrame:
    """Vectorised revenue_available_date over a frame with revenue_year / revenue_month."""
    y = rev["revenue_year"].to_numpy() + (rev["revenue_month"].to_numpy() == 12)
    m = rev["revenue_month"].to_numpy() % 12 + 1
    nominal = pd.to_datetime(pd.DataFrame({"year": y, "month": m, "day": day})).to_numpy()
    idx = dates.searchsorted(nominal, side="left")
    ok = idx < len(dates)
    avail = np.full(len(rev), np.datetime64("NaT"), dtype="datetime64[ns]")
    avail[ok] = dates.to_numpy()[idx[ok]]
    before = nominal < dates[0]          # outside the calendar: keep the nominal date
    avail[before] = nominal[before]
    out = rev.copy()
    out["available_date"] = pd.to_datetime(avail)
    return out


def week_last_trading_days(dates: pd.DatetimeIndex) -> set:
    s = pd.Series(dates, index=dates)
    return set(s.groupby(dates.to_period("W-SUN")).max())

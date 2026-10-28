"""Detect emerging-market (興櫃) bars in FinMind daily prices.

Listed TWSE/TPEx stocks must trade on the exchange tick grid; emerging-market prices are
negotiated and routinely fall off that grid. The listing date is taken as the first bar after
which (almost) every price is on-grid.
"""
from __future__ import annotations
import numpy as np, pandas as pd

# (upper bound, tick) for listed common stocks
TICKS = [(10, 0.01), (50, 0.05), (100, 0.1), (500, 0.5), (1000, 1.0), (np.inf, 5.0)]


def tick_for(p: np.ndarray) -> np.ndarray:
    t = np.full(p.shape, 5.0)
    for hi, tk in reversed(TICKS):
        t = np.where(p < hi, tk, t)
    return t


def on_grid(p: np.ndarray) -> np.ndarray:
    t = tick_for(p)
    q = p / t
    return np.abs(q - np.round(q)) < 1e-6


def bar_on_grid(df: pd.DataFrame) -> pd.Series:
    """True when a bar looks like listed-market trading: every price on the tick grid and
    open/close inside [min, max]. Emerging-market bars often break the second rule (the stored
    'open' is not an auction price), which also catches sub-10 TWD stocks whose 0.01 grid is uninformative."""
    cols = ["open", "max", "min", "close"]
    ok = np.ones(len(df), dtype=bool)
    for c in cols:
        ok &= on_grid(df[c].to_numpy(dtype=float))
    lo, hi = df["min"].to_numpy(dtype=float) - 1e-9, df["max"].to_numpy(dtype=float) + 1e-9
    for c in ["open", "close"]:
        v = df[c].to_numpy(dtype=float)
        ok &= (v >= lo) & (v <= hi)
    return pd.Series(ok, index=df.index)


def listing_date(df: pd.DataFrame, window: int = 20, min_ok: float = 0.95):
    """First date from which a rolling `window` of bars is >= min_ok on-grid and stays so.

    Returns (listing_date, off_grid_share_before, off_grid_share_after)."""
    g = bar_on_grid(df).astype(float)
    if len(g) == 0:
        return pd.NaT, np.nan, np.nan
    roll = g[::-1].rolling(window, min_periods=1).mean()[::-1]      # forward-looking share on-grid
    good = roll >= min_ok
    # last index where the forward window is bad -> listing is the bar after it
    bad_idx = np.where(~good.to_numpy())[0]
    start = 0 if len(bad_idx) == 0 else bad_idx[-1] + 1
    gv = g.to_numpy()
    if start > 0:                      # the window tolerates a stray off-grid bar: move to the first on-grid bar
        while start < len(gv) and gv[start] < 1:
            start += 1
        while start > 0 and gv[start - 1] == 1 and start - 1 > (bad_idx[-1] if len(bad_idx) else -1):
            start -= 1
    if start >= len(g):
        return pd.NaT, 1 - g.mean(), np.nan
    d = g.index[start]
    return d, 1 - g.iloc[:start].mean() if start else 0.0, 1 - g.iloc[start:].mean()

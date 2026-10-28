import numpy as np, pandas as pd
from twbt.listing import on_grid, listing_date


def test_tick_grid():
    assert on_grid(np.array([9.99, 10.05, 49.95, 50.1, 99.9, 100.5, 499.5, 500.0, 1005.0])).all()
    assert not on_grid(np.array([10.03, 50.05, 100.3, 1003.0, 32.72])).any()


def _frame(prices, start="2020-01-01"):
    d = pd.bdate_range(start, periods=len(prices))
    p = np.array(prices, dtype=float)
    return pd.DataFrame({"open": p, "max": p, "min": p, "close": p}, index=d)


def test_listing_date_after_emerging_prefix_with_stray_offgrid_bar():
    # emerging bars (off-grid), one accidental on-grid emerging bar, a final off-grid emerging bar, then listing
    pre = [32.72, 33.11, 33.05, 34.13, 35.27] * 6 + [72.55]
    listed = [63.0, 65.6, 65.8, 64.0, 63.5] * 6
    df = _frame(pre + listed)
    d, _, _ = listing_date(df)
    assert d == df.index[len(pre)]


def test_never_listed_returns_nat():
    d, _, _ = listing_date(_frame([32.72, 33.11, 34.13, 35.27, 36.01] * 10))
    assert pd.isna(d)


def test_always_listed_returns_first_bar():
    df = _frame([50.0, 50.1, 50.2, 50.3] * 10)
    assert listing_date(df)[0] == df.index[0]

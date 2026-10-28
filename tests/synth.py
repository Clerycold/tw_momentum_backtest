"""Tiny synthetic market for engine / signal tests."""
import numpy as np, pandas as pd
from twbt.config import load_config
from twbt.data import Market
from twbt.tcal import add_available_date


def make_market(n_stocks=12, start="2014-01-01", end="2015-12-31", delist=None, seed=0):
    cfg = load_config()
    cfg["periods"]["dev_end"] = end
    dates = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    ids = ["0050"] + [str(1101 + i) for i in range(n_stocks)]
    drift = np.linspace(0.0002, 0.0015, len(ids))
    close = pd.DataFrame({s: 50 * np.exp(np.cumsum(drift[i] + 0.01 * rng.standard_normal(len(dates))))
                          for i, s in enumerate(ids)}, index=dates)
    delist = delist or {}
    for sid, last in delist.items():
        close.loc[close.index > pd.Timestamp(last), sid] = np.nan
    open_ = close.shift().fillna(close) * 1.001
    open_ = open_.where(close.notna())
    money = (close * 5_000_000).where(close.notna())
    rows = []
    for s in ids[1:]:
        for k, ym in enumerate(range(2012 * 12, 2016 * 12)):
            rows.append(dict(stock_id=s, ym=ym, revenue_year=ym // 12, revenue_month=ym % 12 + 1,
                             yoy=0.1 + 0.01 * k, avg_short=0.2 + 0.01 * k, avg_long=0.1))
    rev = add_available_date(pd.DataFrame(rows), dates, cfg["data"]["revenue_available_day"])
    rev["cond_a"] = rev.avg_short > rev.avg_long
    rev = rev.dropna(subset=["available_date"])
    taiex = pd.Series(np.linspace(8000, 10000, len(dates)), index=dates)
    first = close.apply(pd.Series.first_valid_index)
    last = close.apply(pd.Series.last_valid_index)
    m = Market(dates, open_, close, money, close.copy(), close.ffill().shift().where(open_.notna()), taiex,
               pd.DataFrame(columns=["date", "stock_id", "kind", "share_mult", "cash_per_share", "ref_price", "before_price"]),
               pd.DataFrame(columns=["date", "stock_id", "prev_close", "open", "close", "ret"]),
               {s: f"ind{int(s) % 4}" for s in ids[1:]},
               {sid: (pd.Timestamp(d) + pd.Timedelta(days=10), last[sid]) for sid, d in delist.items()},
               first, last, rev)
    cfg["periods"]["dev_start"] = "2015-01-01"
    return m, cfg

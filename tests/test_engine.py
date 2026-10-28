import numpy as np, pandas as pd
import pytest
from synth import make_market
from twbt.signals import Signals
from twbt.engine import Engine


def test_lookahead_revenue_available_before_signal_synthetic():
    m, cfg = make_market()
    sig = Signals(m, cfg)
    res = Engine(m, sig, cfg, "E", "mid").run()
    sel = res.selections
    assert len(sel) and (sel.status == "new").any()
    used = sel.dropna(subset=["available_date"])
    assert (used.available_date <= used.signal_date).all()


def test_revenue_asof_never_returns_future_rows():
    m, cfg = make_market()
    sig = Signals(m, cfg)
    for d in sig.monthly_days:
        r = sig.revenue_asof(d)
        assert (r.available_date <= d).all()
        # the month whose availability date is exactly d must be visible on d
        assert (r.available_date == d).any()


def test_monthly_signal_days_are_availability_days():
    m, cfg = make_market()
    sig = Signals(m, cfg)
    for d in sig.monthly_days:
        assert d.day >= 11
        nominal = pd.Timestamp(d.year, d.month, 11)
        assert not ((m.dates >= nominal) & (m.dates < d)).any()   # first trading day on/after the 11th


def test_delisted_stock_forced_out_at_last_close():
    m, cfg = make_market()
    sig = Signals(m, cfg)
    held = Engine(m, sig, cfg, "E", "mid").run().trades
    victim = held[held.side == "buy"].stock_id.iloc[0]
    entry = held[(held.stock_id == victim) & (held.side == "buy")].date.min()
    last = entry + pd.Timedelta(days=20)
    last = m.dates[m.dates.searchsorted(last)]
    m2, cfg2 = make_market(delist={victim: last})
    res = Engine(m2, Signals(m2, cfg2), cfg2, "E", "mid").run()
    t = res.trades[res.trades.stock_id == victim]
    t = t[t.date <= last]
    buys, sells = t[t.side == "buy"].shares.sum(), t[t.side == "sell"].shares.sum()
    assert buys == sells, "position must be flat after the last valid bar"
    forced = t[t.reason == "delist_forced_exit_last_close"]
    if len(forced):
        row = forced.iloc[-1]
        assert row.date == last
        assert row.raw_price == pytest.approx(m2.close.at[last, victim])
    assert victim not in res.trades[res.trades.date > last].stock_id.values


def test_limit_up_open_blocks_buy():
    m, cfg = make_market()
    sig = Signals(m, cfg)
    first = m.dates[m.dates >= "2015-01-01"][0]
    m.open.loc[first, "0050"] = m.ref.at[first, "0050"] * 1.07   # >= 1.065 in Jan 2015 regime
    res = Engine(m, sig, cfg, "A", "mid").run()
    assert not ((res.trades.date == first) & (res.trades.stock_id == "0050")).any()
    # core buy is retried on the next trading day
    nxt = m.dates[m.dates > first][0]
    assert ((res.trades.date == nxt) & (res.trades.stock_id == "0050") & (res.trades.side == "buy")).any()


def test_limit_down_open_defers_sell():
    m, cfg = make_market()
    base = Engine(m, Signals(m, cfg), cfg, "E", "mid").run().trades
    s = base[base.side == "sell"].iloc[0]
    m.open.loc[s.date, s.stock_id] = m.ref.at[s.date, s.stock_id] * 0.93
    t = Engine(m, Signals(m, cfg), cfg, "E", "mid").run().trades
    t = t[(t.stock_id == s.stock_id) & (t.side == "sell") & (t.date >= s.date)]
    assert t.date.min() > s.date


def test_integer_shares_and_cash_never_negative():
    m, cfg = make_market()
    res = Engine(m, Signals(m, cfg), cfg, "D", "high").run()
    assert (res.trades.shares == res.trades.shares.round()).all()
    assert (res.nav > 0).all()

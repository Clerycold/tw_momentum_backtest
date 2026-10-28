"""Performance and diagnostic metrics."""
from __future__ import annotations
import numpy as np, pandas as pd


def cagr(nav: pd.Series) -> float:
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    return (nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1


def mdd(nav: pd.Series) -> float:
    return float((nav / nav.cummax() - 1).min())


def sharpe(nav: pd.Series, rf: float = 0.0, n: int = 252) -> float:
    r = nav.pct_change().dropna() - rf / n
    return float(r.mean() / r.std(ddof=1) * np.sqrt(n)) if r.std() > 0 else np.nan


def summarize(res, initial: float, bench_nav: pd.Series, regime: pd.Series, n: int = 252, rf: float = 0.0) -> dict:
    # prepend initial capital one day before the first trading day so day-1 costs/moves count
    nav0 = pd.Series([initial], index=[res.nav.index[0] - pd.Timedelta(days=1)])
    navf = pd.concat([nav0, res.nav])
    yrs = (navf.index[-1] - navf.index[0]).days / 365.25
    t = res.trades
    traded = t.notional.sum() if len(t) else 0.0
    turnover = traded / 2 / res.nav.mean() / yrs
    total_cost = res.costs["fee"] + res.costs["tax"] + res.costs["slippage"]
    gross = res.nav.iloc[-1] - initial + total_cost
    out = dict(strategy=res.strategy, scenario=res.scenario,
               CAGR=cagr(navf), MDD=mdd(navf), Sharpe=sharpe(navf, rf, n),
               excess_CAGR_vs_A=cagr(navf) - cagr(pd.concat([nav0, bench_nav])),
               final_nav=res.nav.iloc[-1], turnover=turnover,
               cost_total=total_cost, cost_share_of_gross=total_cost / gross if gross > 0 else np.nan,
               avg_exposure=res.exposure.mean(), blocked_orders=res.costs["blocked"])
    # regime split: day-t return attributed to regime at t-1 close (known in advance)
    r = navf.pct_change().dropna()
    reg = regime.shift().reindex(r.index)
    for k in ["bull", "bear", "sideways"]:
        rr = r[reg == k]
        out[f"{k}_ann_ret"] = (1 + rr).prod() ** (n / len(rr)) - 1 if len(rr) else np.nan
        out[f"{k}_days"] = len(rr)
    rt = res.roundtrips
    if len(rt):
        wins, losses = rt.pnl[rt.pnl > 0], rt.pnl[rt.pnl <= 0]
        out.update(sat_trades=len(rt), sat_avg_hold_days=rt.holding_days.mean(), win_rate=(rt.pnl > 0).mean(),
                   profit_factor=wins.sum() / -losses.sum() if losses.sum() < 0 else np.inf,
                   top5_share_of_profit=wins.nlargest(5).sum() / wins.sum() if wins.sum() > 0 else np.nan)
    return out


def attribution_2x2(m: dict) -> dict:
    """m: strategy -> metric value. A=none, B=filter, C=selection, D=both."""
    A, B, C, D = m["A"], m["B"], m["C"], m["D"]
    return dict(filter_effect=((B - A) + (D - C)) / 2, selection_effect=((C - A) + (D - B)) / 2,
                interaction=(D - C) - (B - A), total=D - A)

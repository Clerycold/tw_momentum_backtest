"""Signals: market filter, satellite selection (entry rules, buffer, industry cap), weekly MA exit."""
from __future__ import annotations
import numpy as np, pandas as pd

from .tcal import next_trading_day_on_or_after, week_last_trading_days


class Signals:
    def __init__(self, mkt, cfg: dict):
        self.mkt, self.cfg = mkt, cfg
        s, f = cfg["satellite"], cfg["market_filter"]
        core = cfg["core"]["symbol"]
        tx = mkt.taiex
        self.strong = (tx > tx.rolling(f["ma_days"], min_periods=f["ma_days"]).mean())
        slope = tx.rolling(f["ma_days"]).mean().diff(cfg["backtest"]["regimes"]["slope_days"])
        self.regime = pd.Series(np.where(self.strong & (slope > 0), "bull",
                                np.where(~self.strong & (slope < 0), "bear", "sideways")), index=tx.index)

        stocks = [c for c in mkt.close.columns if c != core]
        px = mkt.adj_close[stocks]
        valid = mkt.close[stocks].notna()
        self.valid = valid
        self.ma = px.rolling(s["ma_days"], min_periods=s["ma_days"]).mean()
        self.ma_ok = (px > self.ma) & valid
        alive = px.notna()
        self.adv = mkt.money[stocks].fillna(0).where(alive).rolling(s["adv_days"], min_periods=s["adv_days"]).mean()
        self.adv_ok = self.adv >= s["min_adv"]
        self.rs = px / px.shift(s["rs_days"]) - 1
        bars = valid.cumsum()
        eligible = valid & (bars >= s["min_history_bars"]) & self.rs.notna()
        self.rs_rank = self.rs.where(eligible).rank(axis=1, ascending=False, pct=True)   # 0 = strongest

        # flagged unexplained jumps: block new entries for N trading days afterwards
        self.blackout = pd.DataFrame(False, index=px.index, columns=stocks)
        n = cfg["capital_action_detection"]["signal_blackout_days"]
        pos = {d: i for i, d in enumerate(px.index)}
        for fl in mkt.flags.itertuples():
            if fl.stock_id in self.blackout.columns and fl.date in pos:
                i = pos[fl.date]
                self.blackout.iloc[i:i + n, self.blackout.columns.get_loc(fl.stock_id)] = True

        self.week_last = week_last_trading_days(mkt.dates)
        self.monthly_days = self._monthly_signal_days()
        self._rev_cache = {}

    def _monthly_signal_days(self) -> list:
        """Signal day = revenue availability day (11th, rolled forward); orders fill next trading day open."""
        dates = self.mkt.dates
        day = self.cfg["data"]["revenue_available_day"]
        months = pd.period_range(dates[0], dates[-1], freq="M")
        out = [next_trading_day_on_or_after(dates, pd.Timestamp(p.year, p.month, day)) for p in months]
        return sorted({d for d in out if pd.notna(d)})

    def revenue_asof(self, d: pd.Timestamp) -> pd.DataFrame:
        """Latest revenue row per stock whose available_date <= d (point-in-time)."""
        if d in self._rev_cache:
            return self._rev_cache[d]
        r = self.mkt.revenue
        r = r[r.available_date <= d]
        last = r.sort_values(["stock_id", "ym"]).groupby("stock_id").tail(1).set_index("stock_id")
        min_ym = d.year * 12 + d.month - 1 - self.cfg["data"]["max_revenue_staleness_months"]
        last["fresh"] = last.ym >= min_ym
        self._rev_cache[d] = last
        return last

    def select(self, d: pd.Timestamp, held: list) -> tuple[list, pd.DataFrame]:
        s = self.cfg["satellite"]
        rank, rs = self.rs_rank.loc[d], self.rs.loc[d]
        ma_ok, adv_ok, bo = self.ma_ok.loc[d], self.adv_ok.loc[d], self.blackout.loc[d]
        rev = self.revenue_asof(d)
        cond_a = (rev.cond_a & rev.fresh).reindex(rank.index, fill_value=False)

        keep = [h for h in held if h in rank.index and rank.get(h, np.nan) <= s["rs_hold_top_pct"]
                and ma_ok.get(h, False) and adv_ok.get(h, False)]
        cand = rank.index[cond_a & ma_ok & adv_ok & (rank <= s["rs_entry_top_pct"]) & ~bo]
        cand = [c for c in rs[cand].sort_values(ascending=False).index if c not in keep]

        ind = self.mkt.industry
        count = {}
        for h in keep:
            k = ind.get(h, f"UNK_{h}")
            count[k] = count.get(k, 0) + 1
        chosen = list(keep)
        for c in cand:
            if len(chosen) >= s["max_positions"]:
                break
            k = ind.get(c, f"UNK_{c}")
            if count.get(k, 0) >= s["max_per_industry"]:
                continue
            chosen.append(c)
            count[k] = count.get(k, 0) + 1
        new = [c for c in chosen if c not in keep]
        used = rev.reindex(new)[["ym", "available_date", "avg_short", "avg_long"]].copy()
        used["signal_date"], used["status"] = d, "new"
        kept = rev.reindex(keep)[["ym", "available_date", "avg_short", "avg_long"]].copy()
        kept["signal_date"], kept["status"] = d, "kept"
        return chosen, pd.concat([used, kept]).rename_axis("stock_id").reset_index()

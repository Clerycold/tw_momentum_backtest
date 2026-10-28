"""Daily event-driven portfolio simulator.

Timeline for each trading day t:
  1. corporate actions effective on t (cash dividends, stock dividends/splits, flagged jumps)
  2. open: execute orders generated at t-1 close (sells first, then buys)
  3. close: forced exit of stocks whose final valid bar is t and that are on the delisting list
  4. mark to market at close
  5. generate signals from data up to t's close -> orders for t+1 open
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np, pandas as pd

from .costs import CostModel
from .data import limit_for, _limits

STRATEGIES = {  # core share, satellite share, market filter
    "A": (1.0, 0.0, False),
    "B": (1.0, 0.0, True),
    "C": (0.6, 0.4, False),
    "D": (0.6, 0.4, True),
    "E": (0.0, 1.0, False),
}


@dataclass
class Result:
    strategy: str
    scenario: str
    nav: pd.Series
    exposure: pd.Series
    trades: pd.DataFrame
    roundtrips: pd.DataFrame
    selections: pd.DataFrame
    costs: dict


class Engine:
    def __init__(self, mkt, sig, cfg: dict, strategy: str, scenario: str):
        self.m, self.sig, self.cfg = mkt, sig, cfg
        self.name, self.scenario = strategy, scenario
        core_share, sat_share, self.use_filter = STRATEGIES[strategy]
        self.core = cfg["core"]["symbol"]
        self.core_share = core_share
        self.sat_share = sat_share
        if strategy in ("C", "D"):
            self.core_share, self.sat_share = cfg["core"]["weight_in_exposure"], cfg["satellite"]["weight_in_exposure"]
        self.cost = CostModel.from_config(cfg["costs"], scenario)
        self.regimes = _limits(cfg)
        f = cfg["market_filter"]
        self.e_strong, self.e_weak = f["exposure_strong"], f["exposure_weak"]
        self.max_pos = cfg["satellite"]["max_positions"]
        self.tol = cfg["satellite"]["rebalance_tolerance"]
        self.close_ff = mkt.close.ffill()
        ev = mkt.events
        self.ev_by_date = {d: g for d, g in ev.groupby("date")}
        self.fl_by_date = {d: g for d, g in mkt.flags.groupby("date")}
        self.delist_on = {}
        for sid, (_, last) in mkt.delist.items():
            self.delist_on.setdefault(last, []).append(sid)

    # ---------- helpers ----------
    def exposure(self, d) -> float:
        if not self.use_filter:
            return 1.0
        return self.e_strong if bool(self.sig.strong.get(d, False)) else self.e_weak

    def _px_valuation(self, sid, d):
        return self.close_ff.at[d, sid]

    def nav_at_close(self, d):
        return self.cash + sum(n * self._px_valuation(s, d) for s, n in self.shares.items() if n)

    def _slip(self, sid, d_signal):
        if sid in self.m.is_etf:
            return self.cost.slippage(True)
        adv = self.sig.adv.at[d_signal, sid] if sid in self.sig.adv.columns else None
        return self.cost.slippage(False, None if pd.isna(adv) else adv)

    def _record(self, d, sid, side, qty, px_raw, px_exec, fee, tax, reason):
        notional = qty * px_exec
        self.trades.append(dict(date=d, strategy=self.name, scenario=self.scenario, stock_id=sid, side=side,
                                shares=qty, raw_price=px_raw, exec_price=px_exec, notional=notional,
                                fee=fee, tax=tax, slippage_cost=abs(px_exec - px_raw) * qty, reason=reason))
        self.cost_tot["fee"] += fee
        self.cost_tot["tax"] += tax
        self.cost_tot["slippage"] += abs(px_exec - px_raw) * qty
        if sid != self.core:
            rt = self.open_rt.setdefault(sid, dict(stock_id=sid, entry_date=d, cf=0.0, bought=0.0))
            if side == "buy":
                rt["cf"] -= notional + fee
                rt["bought"] += notional + fee
            else:
                rt["cf"] += notional - fee - tax

    def _close_rt_if_flat(self, sid, d):
        if sid != self.core and self.shares.get(sid, 0) == 0 and sid in self.open_rt:
            rt = self.open_rt.pop(sid)
            i0, i1 = self.m.dates.get_loc(rt["entry_date"]), self.m.dates.get_loc(d)
            self.roundtrips.append(dict(strategy=self.name, scenario=self.scenario, stock_id=sid,
                                        entry_date=rt["entry_date"], exit_date=d, holding_days=i1 - i0,
                                        pnl=rt["cf"], ret=rt["cf"] / rt["bought"] if rt["bought"] else np.nan))

    def _sell(self, d, sid, qty, px_raw, slip, reason):
        px = px_raw * (1 - slip)
        notional = qty * px
        fee, tax = self.cost.fee(notional), self.cost.tax(notional, sid in self.m.is_etf)
        self.cash += notional - fee - tax
        self.shares[sid] -= qty
        self._record(d, sid, "sell", qty, px_raw, px, fee, tax, reason)
        if self.shares[sid] == 0:
            del self.shares[sid]
            self._close_rt_if_flat(sid, d)

    # ---------- daily steps ----------
    def corporate_actions(self, d):
        g = self.ev_by_date.get(d)
        if g is not None:
            for e in g.itertuples():
                n = self.shares.get(e.stock_id, 0)
                if not n:
                    continue
                if e.kind == "cash_div":
                    amt = n * e.cash_per_share
                    self.cash += amt
                    if e.stock_id in self.open_rt:
                        self.open_rt[e.stock_id]["cf"] += amt
                    if e.stock_id == self.core:
                        self.core_div_today = True
                else:
                    new = n * e.share_mult
                    self.shares[e.stock_id] = math.floor(new + 1e-9)
                    frac = (new - self.shares[e.stock_id]) * e.ref_price    # cash in lieu of odd fraction
                    self.cash += frac
                    if e.stock_id in self.open_rt:
                        self.open_rt[e.stock_id]["cf"] += frac
        g = self.fl_by_date.get(d)
        if g is not None:
            for f in g.itertuples():
                n = self.shares.get(f.stock_id, 0)
                if n and f.open > 0:
                    new = n * f.prev_close / f.open                         # value-preserving at the open
                    self.shares[f.stock_id] = math.floor(new + 1e-9)
                    self.cash += (new - self.shares[f.stock_id]) * f.open
                    self.flag_hits.append((d, f.stock_id))

    def execute_open(self, d, d_signal):
        if not self.pending:
            return
        o = self.m.open.loc[d]
        nav = self.cash + sum(n * (o[s] if pd.notna(o.get(s, np.nan)) else self.close_ff.at[d, s])
                              for s, n in self.shares.items())
        up, down = limit_for(d, self.regimes)
        ref = self.m.ref.loc[d]
        sells, buys = [], []
        retry = {}
        for sid, (w, reason) in list(self.pending.items()):
            cur = self.shares.get(sid, 0)
            px = o.get(sid, np.nan)
            if pd.isna(px):                      # no trading today
                if w * nav < cur * self.close_ff.at[d, sid] or sid == self.core:
                    continue                     # keep pending sell (and core buys)
                del self.pending[sid]
                continue
            slip = self._slip(sid, d_signal)
            tgt_val = w * nav
            if tgt_val < cur * px:
                tgt = math.floor(tgt_val / px) if w > 0 else 0
                if cur - tgt > 0:
                    sells.append((sid, cur - tgt, px, slip, reason, ref.get(sid, np.nan)))
                else:
                    del self.pending[sid]
            else:
                tgt = math.floor(tgt_val / (px * (1 + slip)))
                if tgt - cur > 0:
                    buys.append((sid, tgt - cur, px, slip, reason, ref.get(sid, np.nan)))
                retry[sid] = self.pending.pop(sid)
        for sid, qty, px, slip, reason, r in sells:
            if pd.notna(r) and px <= r * down + 1e-9:
                self.blocked.append((d, sid, "sell_limit_down"))
                continue                          # cannot sell at limit-down open, retry next day
            self._sell(d, sid, qty, px, slip, reason)
            del self.pending[sid]
        ok = []
        for sid, qty, px, slip, reason, r in buys:
            if pd.notna(r) and px >= r * up - 1e-9:
                self.blocked.append((d, sid, "buy_limit_up"))
                if sid == self.core:              # core retries next day; satellite slot stays cash
                    self.pending[sid] = retry[sid]
                continue
            ok.append((sid, qty, px, slip, reason))
        need = sum(q * p * (1 + s) + self.cost.fee(q * p * (1 + s)) for _, q, p, s, _ in ok)
        scale = min(1.0, self.cash / need) if need > 0 else 1.0
        for sid, qty, px, slip, reason in ok:
            pxe = px * (1 + slip)
            q = math.floor(qty * scale)
            while q > 0 and q * pxe + self.cost.fee(q * pxe) > self.cash + 1e-6:
                q -= 1
            if q <= 0:
                continue
            fee = self.cost.fee(q * pxe)
            self.cash -= q * pxe + fee
            self.shares[sid] = self.shares.get(sid, 0) + q
            self._record(d, sid, "buy", q, px, pxe, fee, 0.0, reason)

    def delist_exits(self, d):
        for sid in self.delist_on.get(d, []):
            n = self.shares.get(sid, 0)
            if n:
                self._sell(d, sid, n, self.m.close.at[d, sid], self._slip(sid, d), "delist_forced_exit_last_close")
            self.pending.pop(sid, None)

    def make_orders(self, d, initial=False):
        e = self.exposure(d)
        core_w = self.core_share * e
        slot_w = self.sat_share * e / self.max_pos
        nav = self.nav_at_close(d)
        wt = lambda s: self.shares.get(s, 0) * self._px_valuation(s, d) / nav
        changed = self.use_filter and e != self.cur_exposure
        monthly = self.sat_share > 0 and (d in self.sig.monthly_days or initial)
        sats = [s for s in self.shares if s != self.core]

        if self.core_share > 0:
            dev = abs(wt(self.core) - core_w) > self.tol * core_w
            if initial or changed or (self.core_div_today and self.sat_share == 0) or (monthly and dev):
                self.pending[self.core] = (core_w, "core_target")
        if monthly:
            chosen, used = self.sig.select(d, sats)
            self.selections.append(used.assign(strategy=self.name, scenario=self.scenario))
            for s in sats:
                if s not in chosen:
                    self.pending[s] = (0.0, "monthly_drop")
            for s in chosen:
                if s not in sats or changed or abs(wt(s) - slot_w) > self.tol * slot_w:
                    self.pending[s] = (slot_w, "monthly_entry" if s not in sats else "monthly_resize")
        elif changed:
            for s in sats:
                if self.pending.get(s, (None,))[0] != 0.0:
                    self.pending[s] = (slot_w, "exposure_rescale")
        if self.sat_share > 0 and d in self.sig.week_last and not monthly:
            for s in sats:
                if self.sig.valid.at[d, s] and not self.sig.ma_ok.at[d, s]:
                    self.pending[s] = (0.0, "weekly_ma60_exit")
        self.cur_exposure = e

    def run(self, start=None, end=None) -> Result:
        cfg = self.cfg
        start = pd.Timestamp(start or cfg["periods"]["dev_start"])
        end = pd.Timestamp(end or cfg["periods"]["dev_end"])
        dates = self.m.dates
        sim = dates[(dates >= start) & (dates <= end)]
        pre = dates[dates < start][-1]
        self.cash = float(cfg["backtest"]["initial_capital"])
        self.shares, self.pending, self.open_rt = {}, {}, {}
        self.trades, self.roundtrips, self.selections, self.blocked, self.flag_hits = [], [], [], [], []
        self.cost_tot = dict(fee=0.0, tax=0.0, slippage=0.0)
        self.cur_exposure, self.core_div_today = None, False
        self.make_orders(pre, initial=True)
        nav, expo = {}, {}
        d_signal = pre
        for d in sim:
            self.core_div_today = False
            self.corporate_actions(d)
            self.execute_open(d, d_signal)
            self.delist_exits(d)
            nav[d] = self.nav_at_close(d)
            expo[d] = sum(n * self._px_valuation(s, d) for s, n in self.shares.items()) / nav[d]
            if d != sim[-1]:
                self.make_orders(d)
                d_signal = d
        for sid in list(self.open_rt):   # mark open round trips at final close for stats
            rt = self.open_rt[sid]
            val = self.shares.get(sid, 0) * self._px_valuation(sid, sim[-1])
            i0 = dates.get_loc(rt["entry_date"])
            self.roundtrips.append(dict(strategy=self.name, scenario=self.scenario, stock_id=sid,
                                        entry_date=rt["entry_date"], exit_date=pd.NaT,
                                        holding_days=dates.get_loc(sim[-1]) - i0, pnl=rt["cf"] + val,
                                        ret=(rt["cf"] + val) / rt["bought"] if rt["bought"] else np.nan))
        sel = pd.concat(self.selections, ignore_index=True) if self.selections else pd.DataFrame()
        cols = ["date", "strategy", "scenario", "stock_id", "side", "shares", "raw_price", "exec_price",
                "notional", "fee", "tax", "slippage_cost", "reason"]
        return Result(self.name, self.scenario, pd.Series(nav), pd.Series(expo), pd.DataFrame(self.trades, columns=cols),
                      pd.DataFrame(self.roundtrips), sel,
                      dict(self.cost_tot, blocked=len(self.blocked), flag_hits=len(self.flag_hits)))

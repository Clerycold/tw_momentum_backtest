"""Build point-in-time panels from the raw FinMind cache (data/raw)."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re
import numpy as np, pandas as pd

from .tcal import add_available_date

ETF_CATEGORIES = {"ETF", "上櫃指數股票型基金(ETF)", "上櫃ETF", "ETN", "指數投資證券(ETN)", "受益證券", "存託憑證", "Index", "大盤", "所有證券"}


@dataclass
class Market:
    dates: pd.DatetimeIndex                 # trading calendar (TAIEX bars), incl. warm-up
    open: pd.DataFrame                      # raw prices, NaN when no valid bar
    close: pd.DataFrame
    money: pd.DataFrame                     # Trading_money (TWD)
    adj_close: pd.DataFrame                 # back-adjusted, ffilled within life; signals only
    ref: pd.DataFrame                       # reference price for limit checks (prev close / event ref)
    taiex: pd.Series
    events: pd.DataFrame                    # date, stock_id, kind, share_mult, cash_per_share, ref_price
    flags: pd.DataFrame                     # detected unexplained jumps (suspected capital reductions)
    industry: dict
    delist: dict                            # stock_id -> (delist_date, last_valid_bar)
    first_bar: pd.Series
    last_bar: pd.Series
    revenue: pd.DataFrame                   # per (stock, revenue month) signal rows with available_date
    is_etf: set = field(default_factory=lambda: {"0050"})


def _limits(cfg):
    return [(pd.Timestamp(r["until"]), r["up"], r["down"]) for r in cfg["execution"]["limit_regimes"]]


def limit_for(date, regimes):
    for until, up, down in regimes:
        if date <= until:
            return up, down
    return regimes[-1][1:]


def clean_industry(info: pd.DataFrame, cfg: dict) -> dict:
    d = cfg["data"]
    x = info[["stock_id", "industry_category"]].dropna().drop_duplicates()
    x = x[~x.industry_category.isin(d["drop_industry"])]
    x["industry_category"] = x.industry_category.replace(d["industry_alias"])
    x = x.drop_duplicates().sort_values(["stock_id", "industry_category"])
    return x.groupby("stock_id").industry_category.first().to_dict()


def read_parts(raw: Path, sub: str, name: str, sufs=("",)) -> pd.DataFrame:
    """Concatenate raw/<sub><suf>/<name>.parquet over period suffixes ('' = dev cache, '_oos' = OOS cache)."""
    parts = [pd.read_parquet(f) for suf in sufs if (f := raw / f"{sub}{suf}" / f"{name}.parquet").exists()]
    parts = [x for x in parts if len(x)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def load_raw_prices(raw: Path, end, sufs=("",), symbols=None) -> dict:
    out = {}
    names = sorted({f.stem for suf in sufs for f in (raw / f"price{suf}").glob("*.parquet")})
    if symbols is not None:
        names = [n for n in names if n in set(symbols)]
    for name in names:
        df = read_parts(raw, "price", name, sufs)
        df["date"] = pd.to_datetime(df["date"])
        df = df[(df.date <= end) & (df.close > 0) & (df.open > 0)]   # close==0 rows = suspended day
        if len(df):
            out[name] = df.drop_duplicates("date").set_index("date").sort_index()
    return out


def build_events(prices: dict, raw: Path, end, ids, sufs=("",)) -> pd.DataFrame:
    rows = []
    for sid in ids:
        dv = read_parts(raw, "dividend", sid, sufs)
        if dv.empty:
            continue
        for _, r in dv.iterrows():
            d = pd.Timestamp(r["date"])
            if d > end or r["before_price"] <= 0 or r["reference_price"] <= 0:
                continue
            kind = str(r["stock_or_cache_dividend"]).strip()
            if kind == "息":   # pure cash: pay cash, shares unchanged
                rows.append((d, sid, "cash_div", 1.0, r["before_price"] - r["reference_price"], r["reference_price"], r["before_price"]))
            else:             # 權 / 權息: cash vs stock split not given -> value-preserving share adjustment
                rows.append((d, sid, "stock_div", r["before_price"] / r["reference_price"], 0.0, r["reference_price"], r["before_price"]))
    for name in ["TaiwanStockSplitPrice", "TaiwanStockParValueChange"]:
        s = read_parts(raw, "global", name, sufs)
        if s.empty:
            continue
        if name == "TaiwanStockParValueChange":
            s = s.rename(columns={"before_close": "before_price", "after_ref_close": "after_price"})
        for _, r in s.iterrows():
            d = pd.Timestamp(r["date"])
            if d <= end and r["stock_id"] in prices and r["after_price"] > 0:
                rows.append((d, r["stock_id"], "split", r["before_price"] / r["after_price"], 0.0, r["after_price"], r["before_price"]))
    ev = pd.DataFrame(rows, columns=["date", "stock_id", "kind", "share_mult", "cash_per_share", "ref_price", "before_price"])
    return ev.drop_duplicates(["date", "stock_id", "kind"]).sort_values(["date", "stock_id"]).reset_index(drop=True)


def detect_unexplained_jumps(close: pd.DataFrame, open_: pd.DataFrame, events: pd.DataFrame, cfg: dict,
                             compound_gaps: bool = False) -> pd.DataFrame:
    """Opening gaps vs the previous valid close beyond the exchange limit that no known event explains."""
    cd = cfg["capital_action_detection"]
    lims = [(pd.Timestamp(r["until"]), r["pct"]) for r in cd["exchange_limits"]]
    thr = pd.Series([next(p for u, p in lims if d <= u) for d in close.index], index=close.index) + cd["excess_over_limit"]
    known = set(zip(events.date, events.stock_id))
    rows = []
    for sid in close.columns:
        c = close[sid].dropna()
        if len(c) <= cd["skip_first_bars"]:
            continue
        prev = c.shift()
        o = open_[sid].reindex(c.index)
        # a corporate action shows up as an opening gap beyond the exchange limit;
        # close-based moves can exceed it legitimately when a no-trade day sits in between
        gap = (o / prev - 1).iloc[cd["skip_first_bars"]:]
        lim = thr.reindex(gap.index) - cd["excess_over_limit"]
        if compound_gaps:
            # no-trade days in between: the price may move one full limit per session
            pos = pd.Series(np.arange(len(close.index)), index=close.index)
            n = (pos.reindex(c.index) - pos.reindex(c.index).shift()).reindex(gap.index)   # sessions since prev bar
            up = (1 + lim) ** n - 1 + cd["excess_over_limit"]
            dn = 1 - (1 - lim) ** n + cd["excess_over_limit"]
            hit = gap[(gap > up) | (-gap > dn)]
        else:
            hit = gap[gap.abs() > thr.reindex(gap.index)]
        for d, x in hit.items():
            if (d, sid) not in known:
                rows.append((d, sid, prev[d], o[d], c[d], x))
    return pd.DataFrame(rows, columns=["date", "stock_id", "prev_close", "open", "close", "ret"])


def build_revenue(raw: Path, ids, dates: pd.DatetimeIndex, cfg: dict, sufs=("",)) -> pd.DataFrame:
    s, l = cfg["satellite"]["rev_short_months"], cfg["satellite"]["rev_long_months"]
    out = []
    for sid in ids:
        v = read_parts(raw, "revenue", sid, sufs)
        if v.empty:
            continue
        v = v[["stock_id", "revenue", "revenue_year", "revenue_month"]]
        v = v.drop_duplicates(["revenue_year", "revenue_month"], keep="last")
        v["ym"] = v.revenue_year * 12 + v.revenue_month - 1
        v = v.set_index("ym").sort_index()
        full = v.reindex(range(v.index.min(), v.index.max() + 1))        # explicit gaps -> NaN
        prior = full.revenue.shift(12)
        yoy = np.where(prior > 0, full.revenue / prior - 1, np.nan)
        yoy = pd.Series(yoy, index=full.index)
        avg_s = yoy.rolling(s, min_periods=s).mean()
        avg_l = yoy.rolling(l, min_periods=l).mean()
        g = pd.DataFrame({"stock_id": sid, "ym": full.index, "yoy": yoy, "avg_short": avg_s, "avg_long": avg_l})
        g = g[full.revenue.notna().to_numpy()]
        g["revenue_year"], g["revenue_month"] = g.ym // 12, g.ym % 12 + 1
        out.append(g)
    if not out:                                            # core-only market (forward A/B test)
        return pd.DataFrame(columns=["stock_id", "ym", "yoy", "avg_short", "avg_long", "revenue_year",
                                     "revenue_month", "available_date", "cond_a"])
    rev = pd.concat(out, ignore_index=True)
    rev = add_available_date(rev, dates, cfg["data"]["revenue_available_day"])
    rev["cond_a"] = rev.avg_short > rev.avg_long          # NaN comparisons -> False
    return rev.dropna(subset=["available_date"]).sort_values(["available_date", "stock_id"]).reset_index(drop=True)


def trim_to_listing(prices: dict, core: str, official_list: dict | None = None) -> tuple[dict, pd.DataFrame]:
    """Drop emerging-market (興櫃) bars: keep each stock only from its detected listing date.

    When the official TWSE listing date falls within 30 days after the estimate, the official date wins
    (a TPEx->TWSE transfer has a much later official date and keeps the earlier TPEx-listed estimate)."""
    from .listing import listing_date
    official_list = official_list or {}
    out, log = {}, []
    for sid, p in prices.items():
        if sid == core:
            out[sid] = p
            continue
        d, _, _ = listing_date(p)
        o = official_list.get(sid)
        if pd.notna(d) and o is not None and pd.notna(o) and 0 < (o - d).days <= 30:
            d = o
        log.append((sid, p.index[0], d))
        if pd.notna(d):
            out[sid] = p[p.index >= d]
    return out, pd.DataFrame(log, columns=["stock_id", "first_bar", "listing_date"])


def official_events(raw: Path, prices: dict, known: pd.DataFrame, end, sufs=("",)) -> pd.DataFrame:
    """Official reductions / ex-rights on dates FinMind has no event for (value-preserving at the official ref)."""
    from .official import load_official
    off = load_official(raw / "official", sufs)
    off = off[(off.date <= end) & off.stock_id.isin(prices.keys())]
    have = set(zip(known.date, known.stock_id))
    rows = []
    for r in off.itertuples():
        idx = prices[r.stock_id].index
        i = idx.searchsorted(r.date)            # official resume date may have no bar (e.g. locked limit, no trade)
        if i >= len(idx) or (idx[i] - r.date).days > 10:
            continue
        d = idx[i]
        if (d, r.stock_id) in have:
            continue
        rows.append((d, r.stock_id, f"official_{r.kind}", r.before_price / r.ref_price, 0.0, r.ref_price, r.before_price))
        have.add((d, r.stock_id))
    return pd.DataFrame(rows, columns=known.columns)


def load_market(cfg: dict, raw: Path, fix_listing: bool = True, use_official: bool = True, end=None,
                symbols=None) -> Market:
    """end=None -> dev_end. A later end stitches the *_oos caches on (caller must have passed the OOS guard),
    and an end after oos_end also the *_fwd caches (forward test). symbols restricts the stock universe."""
    dev_end = pd.Timestamp(cfg["periods"]["dev_end"])
    end = dev_end if end is None else pd.Timestamp(end)
    sufs = ("",) if end <= dev_end else ("", "_oos")
    if end > pd.Timestamp(cfg["periods"]["oos_end"]):
        sufs += ("_fwd",)
    tx = read_parts(raw, "global", "TAIEX", sufs).drop_duplicates("date")
    tx["date"] = pd.to_datetime(tx.date)
    tx = tx[tx.date <= end].set_index("date").sort_index()
    dates = pd.DatetimeIndex(tx.index)

    info = pd.read_parquet(raw / "global" / "TaiwanStockInfo.parquet")
    dl = pd.read_parquet(raw / "global" / "TaiwanStockDelisting.parquet")
    dl["date"] = pd.to_datetime(dl.date)
    etf_ids = set(info[info.industry_category.isin(ETF_CATEGORIES)].stock_id)
    pat = re.compile(cfg["data"]["common_stock_regex"])

    prices = load_raw_prices(raw, end, sufs, symbols)
    ids = [s for s in prices if s == cfg["core"]["symbol"] or (pat.match(s) and s not in etf_ids)]
    prices = {s: prices[s] for s in ids}
    listing_log = None
    if fix_listing:
        ol = None
        f_ol = raw / "official" / "twse_company_basic.parquet"
        if f_ol.exists():
            tw = pd.read_parquet(f_ol)
            ol = dict(zip(tw["公司代號"].astype(str), pd.to_datetime(tw["上市日期"].astype(str), format="%Y%m%d", errors="coerce")))
        prices, listing_log = trim_to_listing(prices, cfg["core"]["symbol"], ol)
        ids = [s for s in ids if s in prices]

    def panel(col):
        return pd.DataFrame({s: p[col] for s, p in prices.items()}).reindex(dates)
    open_, close, money = panel("open"), panel("close"), panel("Trading_money")

    events = build_events(prices, raw, end, ids, sufs)
    if use_official:
        events = pd.concat([events, official_events(raw, prices, events, end, sufs)], ignore_index=True)
        events = events.sort_values(["date", "stock_id"]).reset_index(drop=True)
    flags = detect_unexplained_jumps(close, open_, events, cfg, compound_gaps=fix_listing)

    # back-adjustment factor: price on/after event is "true", earlier prices scaled by ref/before
    ev_f = pd.DataFrame(1.0, index=dates, columns=close.columns)
    adj_rows = [(e.date, e.stock_id, e.ref_price / e.before_price) for e in events.itertuples()]
    adj_rows += [(f.date, f.stock_id, f.open / f.prev_close) for f in flags.itertuples()]
    for d, sid, f in adj_rows:
        if sid in ev_f.columns and d in ev_f.index:
            ev_f.at[d, sid] *= f
    # price at t is scaled by the product of all event factors strictly after t
    factor = ev_f[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    first_bar, last_bar = close.apply(pd.Series.first_valid_index), close.apply(pd.Series.last_valid_index)
    alive = pd.DataFrame({s: (dates >= first_bar[s]) & (dates <= last_bar[s]) for s in close.columns}, index=dates)
    adj_close = (close * factor).ffill().where(alive)

    # limit reference: previous valid close, replaced by announced reference price on event days
    ref = close.ffill().shift().where(open_.notna())
    for e in events.itertuples():
        if e.stock_id in ref.columns and e.date in ref.index:
            ref.at[e.date, e.stock_id] = e.ref_price
    for f in flags.itertuples():
        ref.at[f.date, f.stock_id] = np.nan   # unknown reference -> no limit check

    delist = {}
    for r in dl.itertuples():
        if r.stock_id in close.columns and r.date <= end and pd.notna(last_bar[r.stock_id]):
            delist[r.stock_id] = (r.date, last_bar[r.stock_id])

    revenue = build_revenue(raw, [s for s in ids if s != cfg["core"]["symbol"]], dates, cfg, sufs)
    return Market(dates, open_, close, money, adj_close, ref, tx.close, events, flags,
                  clean_industry(info, cfg), delist, first_bar, last_bar, revenue)

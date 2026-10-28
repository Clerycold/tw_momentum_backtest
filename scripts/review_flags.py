"""Classify every flagged price jump against official exchange records."""
import sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from twbt.official import load_official

flags = pd.read_csv(ROOT / "reports" / (sys.argv[1] if len(sys.argv) > 1 else "v2_corrected") / "flagged_price_jumps_for_review.csv", dtype={"stock_id": str}, parse_dates=["date"])
off = load_official(ROOT / "data" / "raw" / "official")
tx = pd.read_parquet(ROOT / "data" / "raw" / "global" / "TAIEX.parquet")
cal = pd.DatetimeIndex(pd.to_datetime(tx.date)).sort_values()


def bars(sid):
    p = pd.read_parquet(ROOT / "data" / "raw" / "price" / f"{sid}.parquet")
    p["date"] = pd.to_datetime(p.date)
    return p[(p.close > 0) & (p.open > 0)].set_index("date").sort_index()


out = []
cache = {}
for f in flags.itertuples():
    p = cache.setdefault(f.stock_id, bars(f.stock_id))
    i = p.index.get_loc(f.date)
    prev_d = p.index[i - 1]
    gap_days = cal.searchsorted(f.date) - cal.searchsorted(prev_d) - 1      # trading days without a bar
    o = off[(off.stock_id == f.stock_id) & (off.date == f.date)]
    near = off[(off.stock_id == f.stock_id) & ((off.date - f.date).abs() <= pd.Timedelta(days=10))]
    our = f.open / f.prev_close
    if len(o):
        r = o.iloc[0]
        cls = "官方減資" if r.kind == "reduction" else "官方除權息/現增（FinMind 缺）"
        offf = r.ref_price / r.before_price
        out.append((*f[1:], gap_days, cls, r.source, r.detail, r.before_price, r.ref_price, offf, our / offf - 1))
    elif len(near):
        r = near.iloc[0]
        out.append((*f[1:], gap_days, "官方紀錄日期相近（±10 天）", r.source, f"{r.date.date()} {r.detail}", r.before_price, r.ref_price,
                    r.ref_price / r.before_price, np.nan))
    elif gap_days > 0:
        out.append((*f[1:], gap_days, "停牌後復牌（無官方公司行為）", "", "", np.nan, np.nan, np.nan, np.nan))
    else:
        out.append((*f[1:], gap_days, "無法解釋", "", "", np.nan, np.nan, np.nan, np.nan))

cols = ["date", "stock_id", "prev_close", "open", "close", "gap", "no_trade_days_before", "class", "source", "detail",
        "official_before", "official_ref", "official_factor", "our_factor_error"]
rev = pd.DataFrame(out, columns=cols)
if rev.empty:
    print("no flagged jumps left")
    rev.to_csv(ROOT / "reports" / (sys.argv[1] if len(sys.argv) > 1 else "v2_corrected") / "flag_review.csv", index=False, encoding="utf-8-sig")
    sys.exit(0)
rev.to_csv(ROOT / "reports" / (sys.argv[1] if len(sys.argv) > 1 else "v2_corrected") / "flag_review.csv", index=False, encoding="utf-8-sig")
print(rev["class"].value_counts().to_string())
c = rev.dropna(subset=["our_factor_error"])
print("\nour factor vs official (confirmed):", c.our_factor_error.abs().describe().round(4).to_dict())
print("errors > 5%:", (c.our_factor_error.abs() > 0.05).sum())

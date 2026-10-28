"""Run the 2015-2021 development backtest: 5 strategies x 3 slippage scenarios, then write the report."""
import sys, time, json
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from twbt.config import load_config, guard_period, check_config_lock
from twbt.data import load_market
from twbt.signals import Signals
from twbt.engine import Engine
from twbt.metrics import summarize, attribution_2x2
from twbt.report import write_report, plot_curves

import argparse
ap = argparse.ArgumentParser()
ap.add_argument("--variant", choices=["v1_original", "v2_corrected"], default="v2_corrected")
args = ap.parse_args()
FIX = args.variant == "v2_corrected"
cfg = load_config()
P = cfg["periods"]
guard_period(cfg, P["dev_start"], P["dev_end"])
if not (ROOT / "data" / "raw" / "DOWNLOAD_DONE").exists():
    sys.exit("download not finished (data/raw/DOWNLOAD_DONE missing)")
if cfg.get("oos_unlocked"):
    # after the OOS unlock: verify the strategy parameters still equal the dev-locked archive, report the dev hash
    from twbt.config import check_oos_lock
    import json
    check_oos_lock()
    cfg_hash = json.loads((ROOT / "logs" / "config_lock.json").read_text())["config_sha256"]
    cfg["_oos_note"] = "- 樣本外：已於 2026-10-27 解鎖（`logs/oos_unlock_log.jsonl`）；本報告只含開發期數字"
else:
    cfg_hash = check_config_lock()

t0 = time.time()
mkt = load_market(cfg, ROOT / "data" / "raw", fix_listing=FIX, use_official=FIX)
sig = Signals(mkt, cfg)
print(f"market loaded: {mkt.close.shape}, {len(mkt.events)} events, {len(mkt.flags)} flagged jumps, {time.time()-t0:.0f}s")

results = {}
for sc in cfg["costs"]["slippage_scenarios"]:
    for st in cfg["backtest"]["strategies"]:
        results[(st, sc)] = Engine(mkt, sig, cfg, st, sc).run()
        print(st, sc, f"final NAV {results[(st, sc)].nav.iloc[-1]:,.0f}")

# --- look-ahead audit on the real run: every revenue row used must be available on/before its signal day
sel = pd.concat([r.selections for r in results.values() if len(r.selections)], ignore_index=True)
used = sel.dropna(subset=["available_date"])
assert (used.available_date <= used.signal_date).all(), "look-ahead: revenue used before availability"
assert (sel[sel.status == "new"].available_date.notna()).all(), "new entry without revenue data"

init = cfg["backtest"]["initial_capital"]
rows = []
for (st, sc), r in results.items():
    rows.append(summarize(r, init, results[("A", sc)].nav, sig.regime,
                          cfg["backtest"]["trading_days_per_year"], cfg["backtest"]["risk_free"]))
metrics = pd.DataFrame(rows)

out = ROOT / "reports" / args.variant
out.mkdir(parents=True, exist_ok=True)
pd.concat([r.trades for r in results.values()]).to_csv(out / "trades_dev_2015_2021.csv", index=False, encoding="utf-8-sig")
pd.concat([r.roundtrips for r in results.values()]).to_csv(out / "satellite_roundtrips_dev_2015_2021.csv", index=False, encoding="utf-8-sig")
metrics.to_csv(out / "metrics_dev_2015_2021.csv", index=False, encoding="utf-8-sig")
mkt.flags.to_csv(out / "flagged_price_jumps_for_review.csv", index=False, encoding="utf-8-sig")
sel.to_csv(out / "selection_revenue_audit.csv", index=False, encoding="utf-8-sig")

# --- survivorship-bias size (decision 1a): later-delisted stocks that pass b/c/d but lack usable revenue
delisted = set(mkt.delist)
bias = []
for d in sig.monthly_days:
    if d < pd.Timestamp(P["dev_start"]) - pd.Timedelta(days=40):
        continue
    rev = sig.revenue_asof(d)
    has_rev = set(rev.index[rev.fresh])
    ok = (sig.ma_ok.loc[d] & sig.adv_ok.loc[d] & (sig.rs_rank.loc[d] <= cfg["satellite"]["rs_entry_top_pct"]))
    passing = set(ok.index[ok])
    bias.append(dict(signal_date=d, pass_bcd=len(passing), pass_bcd_delisted=len(passing & delisted),
                     pass_bcd_delisted_no_revenue=len((passing & delisted) - has_rev),
                     pass_bcd_any_no_revenue=len(passing - has_rev)))
bias = pd.DataFrame(bias)
bias.to_csv(out / "survivorship_bias_check.csv", index=False, encoding="utf-8-sig")

attrib = {}
for sc in cfg["costs"]["slippage_scenarios"]:
    m = metrics[metrics.scenario == sc].set_index("strategy")
    attrib[sc] = {k: attribution_2x2(m[k].to_dict()) for k in ["CAGR", "Sharpe", "MDD"]}

plot_curves(results, cfg, out)
write_report(cfg, cfg_hash, mkt, sig, results, metrics, attrib, bias, out / "dev_2015_2021.md", variant=args.variant)
print("done", f"{time.time()-t0:.0f}s")

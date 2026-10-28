"""Out-of-sample run (2022-01-01 .. oos_end): same strategies, parameters and pre-registered criterion as dev."""
import copy, sys, time
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from twbt.config import load_config, guard_period, check_oos_lock
from twbt.data import load_market
from twbt.signals import Signals
from twbt.engine import Engine
from twbt.metrics import summarize, attribution_2x2
from twbt.report import write_report, plot_curves

cfg = load_config()
P = cfg["periods"]
cfg_hash = check_oos_lock()
guard_period(cfg, P["oos_start"], P["oos_end"])
if not (ROOT / "data" / "raw" / "DOWNLOAD_OOS_DONE").exists():
    sys.exit("OOS download not finished")

t0 = time.time()
mkt = load_market(cfg, ROOT / "data" / "raw", end=P["oos_end"])      # 2014 .. oos_end, warm-up included
sig = Signals(mkt, cfg)
print(f"market loaded: {mkt.close.shape}, {mkt.dates[0].date()}..{mkt.dates[-1].date()}, "
      f"{len(mkt.events)} events, {len(mkt.flags)} flagged jumps, {time.time()-t0:.0f}s")

run_cfg = copy.deepcopy(cfg)                                  # report/engine read the window from dev_* keys
run_cfg["periods"]["dev_start"], run_cfg["periods"]["dev_end"] = P["oos_start"], P["oos_end"]
run_cfg["_phase"] = "樣本外"
run_cfg["_lock_note"] = "（樣本外鎖定，`logs/config_lock_oos.json`；開發期 config 雜湊 " + \
    __import__("json").loads((ROOT / "logs" / "config_lock.json").read_text())["config_sha256"][:12] + "…，兩者只差樣本外起訖日與解鎖開關）"
run_cfg["_oos_note"] = f"- 樣本外於 {P['oos_start']} ~ {P['oos_end']} 執行；解鎖紀錄 `logs/oos_unlock_log.jsonl`；策略參數與判準與開發期相同"

results = {}
for sc in cfg["costs"]["slippage_scenarios"]:
    for st in cfg["backtest"]["strategies"]:
        results[(st, sc)] = Engine(mkt, sig, run_cfg, st, sc).run(P["oos_start"], P["oos_end"])
        print(st, sc, f"final NAV {results[(st, sc)].nav.iloc[-1]:,.0f}")

sel = pd.concat([r.selections for r in results.values() if len(r.selections)], ignore_index=True)
used = sel.dropna(subset=["available_date"])
assert (used.available_date <= used.signal_date).all(), "look-ahead: revenue used before availability"
assert (sel[sel.status == "new"].available_date.notna()).all(), "new entry without revenue data"

init = cfg["backtest"]["initial_capital"]
metrics = pd.DataFrame([summarize(r, init, results[("A", sc)].nav, sig.regime,
                                  cfg["backtest"]["trading_days_per_year"], cfg["backtest"]["risk_free"])
                        for (st, sc), r in results.items()])

out = ROOT / "reports" / "oos_2022_2026"
out.mkdir(parents=True, exist_ok=True)
pd.concat([r.trades for r in results.values()]).to_csv(out / "trades_oos.csv", index=False, encoding="utf-8-sig")
pd.concat([r.roundtrips for r in results.values()]).to_csv(out / "satellite_roundtrips_oos.csv", index=False, encoding="utf-8-sig")
metrics.to_csv(out / "metrics_oos.csv", index=False, encoding="utf-8-sig")
mkt.flags.to_csv(out / "flagged_price_jumps_for_review.csv", index=False, encoding="utf-8-sig")
sel.to_csv(out / "selection_revenue_audit.csv", index=False, encoding="utf-8-sig")

delisted = set(mkt.delist)
bias = []
for d in sig.monthly_days:
    if d < pd.Timestamp(P["oos_start"]):
        continue
    rev = sig.revenue_asof(d)
    has_rev = set(rev.index[rev.fresh])
    ok = sig.ma_ok.loc[d] & sig.adv_ok.loc[d] & (sig.rs_rank.loc[d] <= cfg["satellite"]["rs_entry_top_pct"])
    passing = set(ok.index[ok])
    bias.append(dict(signal_date=d, pass_bcd=len(passing), pass_bcd_delisted=len(passing & delisted),
                     pass_bcd_delisted_no_revenue=len((passing & delisted) - has_rev),
                     pass_bcd_any_no_revenue=len(passing - has_rev)))
bias = pd.DataFrame(bias)
bias.to_csv(out / "survivorship_bias_check.csv", index=False, encoding="utf-8-sig")

attrib = {sc: {k: attribution_2x2(metrics[metrics.scenario == sc].set_index("strategy")[k].to_dict())
               for k in ["CAGR", "Sharpe", "MDD"]} for sc in cfg["costs"]["slippage_scenarios"]}
plot_curves(results, run_cfg, out)
write_report(run_cfg, cfg_hash, mkt, sig, results, metrics, attrib, bias, out / "oos_2022_2026.md", variant="")

# dev vs OOS side by side (mid)
dev = pd.read_csv(ROOT / "reports" / "v2_corrected" / "metrics_dev_2015_2021.csv")
cols = ["CAGR", "MDD", "Sharpe", "excess_CAGR_vs_A"]
cmp_ = dev[dev.scenario == "mid"].set_index("strategy")[cols].join(
    metrics[metrics.scenario == "mid"].set_index("strategy")[cols], lsuffix="_dev", rsuffix="_oos")
cmp_.to_csv(out / "dev_vs_oos_mid.csv", encoding="utf-8-sig")
lines = ["\n## 附錄：開發期（v2）與樣本外對照（mid 滑價）\n",
         "| 策略 | CAGR 開發 | CAGR 樣本外 | MDD 開發 | MDD 樣本外 | Sharpe 開發 | Sharpe 樣本外 |", "|---|---|---|---|---|---|---|"]
for s, r in cmp_.iterrows():
    lines.append(f"| {s} | {r.CAGR_dev*100:.2f}% | {r.CAGR_oos*100:.2f}% | {r.MDD_dev*100:.2f}% | {r.MDD_oos*100:.2f}% | "
                 f"{r.Sharpe_dev:.3f} | {r.Sharpe_oos:.3f} |")
with open(out / "oos_2022_2026.md", "a", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("done", f"{time.time()-t0:.0f}s")

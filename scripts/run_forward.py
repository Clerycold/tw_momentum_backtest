"""Forward test status / verdict for the pre-registered hypothesis in forward_B.yaml."""
import copy, sys, time
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from twbt.config import load_config
from twbt.forward import load_forward, check_forward_lock, verdict
from twbt.data import load_market
from twbt.signals import Signals
from twbt.engine import Engine
from twbt.metrics import summarize

cfg, fwd = load_config(), load_forward()
fwd_hash = check_forward_lock()
start, eval_d = pd.Timestamp(fwd["period"]["forward_start"]), pd.Timestamp(fwd["period"]["evaluation_date"])
core = cfg["core"]["symbol"]
mkt = load_market(cfg, ROOT / "data" / "raw", end=eval_d, symbols=[core])   # data after evaluation_date never enters
last = mkt.dates[-1]
out = ROOT / "reports" / "forward_B"
out.mkdir(parents=True, exist_ok=True)
L = [f"# 前瞻驗證進度：{fwd['challenger']} 對 {fwd['benchmark']}", "",
     f"- 預先登記：`forward_B.yaml`（SHA256 `{fwd_hash[:12]}…`，鎖定紀錄 `logs/forward_B_lock.json`）",
     f"- 策略 config：`{fwd['strategy_config_sha256'][:12]}…`（與樣本外相同）",
     f"- 前瞻期：{start.date()} 起，判定日 {eval_d.date()}；資料最後日期 {last.date()}",
     f"- 判準：mid 滑價下 {fwd['criterion']['sharpe']}，且 {fwd['criterion']['mdd']}", ""]

if last < start:
    L += ["**尚無前瞻期資料**，等 2026-11-02 之後的交易日資料下載後再執行。"]
    (out / "status.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("no forward data yet; last date", last.date())
    sys.exit(0)

sig = Signals(mkt, cfg)
rc = copy.deepcopy(cfg)
res = {s: Engine(mkt, sig, rc, s, fwd["scenario"]).run(start, last) for s in (fwd["benchmark"], fwd["challenger"])}
bench = res[fwd["benchmark"]].nav
m = {s: summarize(r, fwd["initial_capital"], bench, sig.regime, cfg["backtest"]["trading_days_per_year"],
                  cfg["backtest"]["risk_free"]) for s, r in res.items()}
weak_days = int((~sig.strong.loc[start:last].iloc[:-1]).sum())   # last close's signal has not been traded yet
v = verdict(m[fwd["challenger"]], m[fwd["benchmark"]], last, eval_d, weak_days > 0)
n = len(bench)

L += [f"## 狀態：{v}", "",
      f"已累積 {n} 個交易日；濾網處於防守的交易日 {weak_days} 天；最新收盤大盤"
      + ("在 200 日線之上（B 曝險 100%）" if sig.strong.loc[last] else "跌破 200 日線（B 曝險 30%）"), "",
      "| 策略 | 累積報酬 | CAGR | MDD | Sharpe | 平均曝險 |", "|---|---|---|---|---|---|"]
for s, x in m.items():
    L.append(f"| {s} | {res[s].nav.iloc[-1] / fwd['initial_capital'] - 1:+.2%} | {x['CAGR']:.2%} | {x['MDD']:.2%} | "
             f"{x['Sharpe']:.3f} | {x['avg_exposure']:.1%} |")
L += ["", "> 判定日前的數字只是進度。依預先登記，不得提前下結論，也不得因此修改規則。"]
(out / "status.md").write_text("\n".join(L) + "\n", encoding="utf-8")
row = dict(run_at=time.strftime("%Y-%m-%d %H:%M:%S"), last_date=last.date(), days=n, weak_days=weak_days, status=v,
           **{f"{k}_{s}": m[s][k] for s in m for k in ("CAGR", "MDD", "Sharpe")})
hist = out / "history.csv"
pd.DataFrame([row]).to_csv(hist, mode="a", header=not hist.exists(), index=False, encoding="utf-8-sig")
print(v, {s: (round(x["Sharpe"], 3), round(x["MDD"], 4)) for s, x in m.items()})

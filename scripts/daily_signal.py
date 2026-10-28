"""After-close job: refresh data, compute rule B's market-filter state, notify via Telegram.
Sends on a state change (action needed), on Fridays (weekly brief) and when data looks stale.
Usage: python scripts/daily_signal.py [--dry-run] [--kind change|weekly|daily] [--no-download]"""
import argparse, json, subprocess, sys, time
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from twbt.config import load_config
from twbt.data import load_market
from twbt.notify import filter_state, build_message, stale_message, send_telegram

ap = argparse.ArgumentParser()
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--kind", choices=["change", "weekly", "daily"], help="force a message type (testing / on demand)")
ap.add_argument("--no-download", action="store_true")
a = ap.parse_args()
STATE = ROOT / "logs" / "signal_state.json"
LOG = ROOT / "logs" / "daily_signal.log"


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


try:
    cfg = load_config()
    if not a.no_download:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "download_forward.py")], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError("資料下載失敗：" + (r.stderr.strip().splitlines() or ["?"])[-1])
    today = pd.Timestamp.now().normalize()
    mkt = load_market(cfg, ROOT / "data" / "raw", end=today, symbols=[cfg["core"]["symbol"]])
    f = cfg["market_filter"]
    st = filter_state(mkt.taiex, f["ma_days"])
    last = st.index[-1]
    sent = json.loads(STATE.read_text()) if STATE.exists() else {}

    if np.busday_count(last.date(), today.date()) >= 2:          # two+ weekdays without a bar
        if sent.get("stale_for") != str(last.date()) or a.kind:
            send_telegram(stale_message(last, today), a.dry_run)
            sent["stale_for"] = str(last.date())
        log(f"stale data, last={last.date()}")
    elif sent.get("last_date") == str(last.date()) and not a.kind:
        log(f"already handled {last.date()}")
    else:
        kind = a.kind or ("change" if st.strong.iloc[-1] != st.strong.iloc[-2] else "weekly" if last.weekday() == 4 else None)
        ev = mkt.events
        dv = ev[(ev.date == last) & (ev.stock_id == cfg["core"]["symbol"]) & (ev.kind == "cash_div")]
        div = {"cash": float(dv.cash_per_share.iloc[0])} if len(dv) else None
        if kind is None and div:
            kind = "daily"                                        # ex-dividend day: remind even mid-week
        if kind:
            send_telegram(build_message(st, {True: f["exposure_strong"], False: f["exposure_weak"]}, div, kind), a.dry_run)
        sent.update(last_date=str(last.date()), strong=bool(st.strong.iloc[-1]), kind=kind)
        log(f"{last.date()} strong={bool(st.strong.iloc[-1])} gap={st.gap.iloc[-1]:+.4f} sent={kind}")
    if not a.dry_run:
        STATE.write_text(json.dumps(sent, ensure_ascii=False))
except Exception as e:
    log(f"ERROR {e}")
    try:
        send_telegram(f"⚠ <b>資產配置訊號程式失敗</b>\n{str(e)[:300]}\n今天的訊號無法確認。", a.dry_run)
    except Exception as e2:
        log(f"ERROR telegram {e2}")
    raise

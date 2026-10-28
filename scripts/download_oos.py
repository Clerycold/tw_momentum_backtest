"""Download 2022-01-01 .. oos_end raw data (separate *_oos folders). Requires the OOS unlock + lock."""
import sys, logging, time
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from twbt.config import load_config, guard_period, check_oos_lock
from twbt.finmind import FinMind

cfg = load_config()
P = cfg["periods"]
check_oos_lock()
guard_period(cfg, P["oos_start"], P["oos_end"])
S, E = P["oos_start"], P["oos_end"]
logging.basicConfig(filename=ROOT / "logs" / "download_oos.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
log = logging.getLogger("dl_oos")
fm = FinMind(ROOT / "data" / "raw", hard_end=E)

fm.fetch("TaiwanStockSplitPrice", "global_oos", "TaiwanStockSplitPrice", start=S, end=E)
fm.fetch("TaiwanStockParValueChange", "global_oos", "TaiwanStockParValueChange", start=S, end=E)
fm.fetch("TaiwanStockTradingDate", "global_oos", "TaiwanStockTradingDate", start=S, end=E)
fm.fetch("TaiwanStockPrice", "global_oos", "TAIEX", data_id="TAIEX", start=S, end=E)
fm.fetch("TaiwanStockTotalReturnIndex", "global_oos", "TAIEX_TR", data_id="TAIEX", start=S, end=E)

info = pd.read_parquet(ROOT / "data" / "raw" / "global" / "TaiwanStockInfo.parquet")
dl = pd.read_parquet(ROOT / "data" / "raw" / "global" / "TaiwanStockDelisting.parquet")
dl["date"] = pd.to_datetime(dl["date"])
common = r"^[1-9]\d{3}$"
ids = set(info[info.type.isin(["twse", "tpex"]) & info.stock_id.str.match(common)].stock_id)
ids |= set(dl[(dl.date >= cfg["data"]["price_start"]) & dl.stock_id.str.match(common)].stock_id)
# stocks that are emerging today but traded on TWSE/TPEx 2022-2026 are not in this list; noted as a limitation
ids = ["0050"] + sorted(ids)
log.info("candidate ids: %d", len(ids))
t0 = time.time()
for k, sid in enumerate(ids):
    px = fm.fetch("TaiwanStockPrice", "price_oos", sid, data_id=sid, start=S, end=E)
    if px.empty:
        continue
    fm.fetch("TaiwanStockDividendResult", "dividend_oos", sid, data_id=sid, start=S, end=E)
    if sid != "0050":
        fm.fetch("TaiwanStockMonthRevenue", "revenue_oos", sid, data_id=sid, start=S, end=E)
    if k % 25 == 0:
        log.info("progress %d/%d  calls=%d  elapsed=%.1fmin", k, len(ids), fm.calls, (time.time() - t0) / 60)
log.info("DONE calls=%d", fm.calls)
(ROOT / "data" / "raw" / "DOWNLOAD_OOS_DONE").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))

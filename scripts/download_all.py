"""Download every raw dataset needed for the 2015-2021 dev backtest. Resumable."""
import sys, logging, time
from pathlib import Path
import pandas as pd, yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from twbt.finmind import FinMind

cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
D = cfg["data"]
logging.basicConfig(filename=ROOT / "logs" / "download.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
log = logging.getLogger("dl")
fm = FinMind(ROOT / "data" / "raw", hard_end=cfg["periods"]["dev_end"])
END = cfg["periods"]["dev_end"]

# --- global (list-type) datasets: no end_date filter possible, they are reference lists ---
g = {}
for ds in ["TaiwanStockInfo", "TaiwanStockDelisting"]:
    g[ds] = fm.fetch(ds, "global", ds)
g["split"] = fm.fetch("TaiwanStockSplitPrice", "global", "TaiwanStockSplitPrice", start=D["price_start"], end=END)
g["par"] = fm.fetch("TaiwanStockParValueChange", "global", "TaiwanStockParValueChange", start=D["price_start"], end=END)
fm.fetch("TaiwanStockTradingDate", "global", "TaiwanStockTradingDate", start=D["price_start"], end=END)
fm.fetch("TaiwanStockPrice", "global", "TAIEX", data_id="TAIEX", start=D["price_start"], end=END)
fm.fetch("TaiwanStockTotalReturnIndex", "global", "TAIEX_TR", data_id="TAIEX", start=D["price_start"], end=END)

info, dl = g["TaiwanStockInfo"], g["TaiwanStockDelisting"]
common = r"^[1-9]\d{3}$"
ids = set(info[info.type.isin(["twse", "tpex"]) & info.stock_id.str.match(common)].stock_id)
dl["date"] = pd.to_datetime(dl["date"])
ids |= set(dl[(dl.date >= D["price_start"]) & dl.stock_id.str.match(common)].stock_id)
ids = ["0050"] + sorted(ids)
log.info("candidate ids: %d", len(ids))

t0 = time.time()
for k, sid in enumerate(ids):
    px = fm.fetch("TaiwanStockPrice", "price", sid, data_id=sid, start=D["price_start"], end=END)
    if px.empty:
        continue  # never traded in window -> skip revenue/dividend (saves quota)
    fm.fetch("TaiwanStockDividendResult", "dividend", sid, data_id=sid, start=D["price_start"], end=END)
    if sid != "0050":
        fm.fetch("TaiwanStockMonthRevenue", "revenue", sid, data_id=sid, start=D["revenue_start"], end=END)
    if k % 25 == 0:
        log.info("progress %d/%d  calls=%d  elapsed=%.1fmin", k, len(ids), fm.calls, (time.time() - t0) / 60)
log.info("DONE calls=%d", fm.calls)
(ROOT / "data" / "raw" / "DOWNLOAD_DONE").write_text(time.strftime("%F %T"))

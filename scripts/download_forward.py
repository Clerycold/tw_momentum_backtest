"""Refresh forward-period data (oos_end+1 .. today) for the A/B forward test: only TAIEX, 0050 and global events."""
import sys, logging, time
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from twbt.config import load_config
from twbt.forward import check_forward_lock
from twbt.finmind import FinMind

cfg = load_config()
check_forward_lock()
S = (pd.Timestamp(cfg["periods"]["oos_end"]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
E = pd.Timestamp.now().strftime("%Y-%m-%d")
logging.basicConfig(filename=ROOT / "logs" / "download_forward.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
fm = FinMind(ROOT / "data" / "raw", hard_end=E)
core = cfg["core"]["symbol"]
for dataset, sub, name, did in [("TaiwanStockPrice", "global_fwd", "TAIEX", "TAIEX"),
                                ("TaiwanStockTradingDate", "global_fwd", "TaiwanStockTradingDate", None),
                                ("TaiwanStockSplitPrice", "global_fwd", "TaiwanStockSplitPrice", None),
                                ("TaiwanStockParValueChange", "global_fwd", "TaiwanStockParValueChange", None),
                                ("TaiwanStockPrice", "price_fwd", core, core),
                                ("TaiwanStockDividendResult", "dividend_fwd", core, core)]:
    df = fm.fetch(dataset, sub, name, data_id=did, start=S, end=E, refresh=True)
    last = pd.to_datetime(df["date"]).max().date() if len(df) and "date" in df else None
    logging.info("%s %s rows=%d last=%s", dataset, name, len(df), last)
    print(dataset, name, len(df), last)

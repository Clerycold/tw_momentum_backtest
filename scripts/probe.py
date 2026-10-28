"""Step 0 data audit probe. Caches every raw response to data/raw/probe/*.parquet."""
import os, sys, json, time
from pathlib import Path
import pandas as pd, requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "probe"
CACHE.mkdir(parents=True, exist_ok=True)
TOKEN = os.environ["FINMIND_TOKEN"]
URL = "https://api.finmindtrade.com/api/v4/data"

def get(dataset, data_id=None, start=None, end=None, tag=None):
    tag = tag or f"{dataset}_{data_id or 'ALL'}_{start}_{end}"
    f = CACHE / f"{tag}.parquet"
    meta = CACHE / f"{tag}.json"
    if f.exists():
        return pd.read_parquet(f), json.loads(meta.read_text())
    p = {"dataset": dataset}
    if data_id: p["data_id"] = data_id
    if start: p["start_date"] = start
    if end: p["end_date"] = end
    r = requests.get(URL, params=p, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=120)
    j = r.json()
    m = {"http": r.status_code, "status": j.get("status"), "msg": j.get("msg")}
    df = pd.DataFrame(j.get("data", []))
    if r.status_code == 200 and j.get("status") == 200:
        df.to_parquet(f); meta.write_text(json.dumps(m))
    return df, m

if __name__ == "__main__":
    args = sys.argv[1:]
    df, m = get(*[a if a != "-" else None for a in args])
    print(m, df.shape)
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(df.dtypes.to_string()); print(df.head(15).to_string()); print(df.tail(5).to_string())

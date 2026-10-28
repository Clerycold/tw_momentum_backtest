"""Download official TWSE / TPEx capital-reduction and ex-rights records (2014-2021) for flag review."""
import json, sys, time
from pathlib import Path
import pandas as pd, requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "official"
OUT.mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0"}


def get(name, url):
    f = OUT / f"{name}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    for attempt in range(5):
        try:
            j = requests.get(url, headers=H, timeout=60).json()
            f.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
            time.sleep(3)
            return j
        except Exception as e:
            print("retry", name, e)
            time.sleep(20)
    raise RuntimeError(name)


def table(j):
    t = j["tables"][0] if "tables" in j else j
    return pd.DataFrame(t.get("data") or [], columns=t.get("fields"))


frames = {"twse_reduction": [], "tpex_reduction": [], "twse_exright": [], "tpex_exright": []}
Y0, Y1 = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (2014, 2021)
SUF = "" if (Y0, Y1) == (2014, 2021) else "_oos"
for y in range(Y0, Y1 + 1):
    frames["twse_reduction"].append(table(get(f"twse_reduction_{y}",
        f"https://www.twse.com.tw/rwd/zh/reducation/TWTAUU?startDate={y}0101&endDate={y}1231&response=json")))
    frames["tpex_reduction"].append(table(get(f"tpex_reduction_{y}",
        f"https://www.tpex.org.tw/www/zh-tw/bulletin/revivt?startDate={y}/01/01&endDate={y}/12/31&response=json")))
    for m in range(1, 13):
        if pd.Timestamp(y, m, 1) > pd.Timestamp("2026-09-30"):
            break
        end = (pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd()).day
        frames["twse_exright"].append(table(get(f"twse_exright_{y}{m:02d}",
            f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={y}{m:02d}01&endDate={y}{m:02d}{end}&response=json")))
        frames["tpex_exright"].append(table(get(f"tpex_exright_{y}{m:02d}",
            f"https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate={y}/{m:02d}/01&endDate={y}/{m:02d}/{end}&response=json")))
    print(y, "ok", flush=True)

for k, v in frames.items():
    df = pd.concat(v, ignore_index=True)
    df.to_parquet(OUT / f"{k}{SUF}.parquet", index=False)
    print(k, len(df))

"""Official TWSE / TPEx corporate-action records, normalised to (date, stock_id, before_price, ref_price, kind)."""
from __future__ import annotations
import re
from pathlib import Path
import numpy as np, pandas as pd


def _roc(s: str) -> pd.Timestamp:
    """'106/01/16', '1060330', '106年08月01日' -> Timestamp."""
    d = re.findall(r"\d+", str(s))
    if len(d) == 1:                       # 1060330
        x = d[0]
        y, m, dd = int(x[:-4]), int(x[-4:-2]), int(x[-2:])
    else:
        y, m, dd = map(int, d[:3])
    return pd.Timestamp(y + 1911, m, dd)


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return np.nan


def load_official(dir_: Path, sufs=("",)) -> pd.DataFrame:
    rows = []
    specs = [
        ("twse_reduction", "恢復買賣日期", "股票代號", "停止買賣前收盤價格", "恢復買賣參考價", "reduction"),
        ("tpex_reduction", "恢復買賣日期", "股票代號", "最後交易日之收盤價格", "減資恢復買賣開始日參考價格", "reduction"),
        ("twse_exright", "資料日期", "股票代號", "除權息前收盤價", "除權息參考價", "exright"),
        ("tpex_exright", "除權息日期", "代號", "除權息前收盤價", "除權息參考價", "exright"),
    ]
    for name, dcol, scol, bcol, rcol, kind in specs:
        fs = [Path(dir_) / f"{name}{suf}.parquet" for suf in sufs]
        fs = [f for f in fs if f.exists()]
        if not fs:
            continue
        df = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
        for rec in df.to_dict("records"):
            rows.append((_roc(rec[dcol]), str(rec[scol]).strip(), _num(rec[bcol]), _num(rec[rcol]), kind, name,
                         str(rec.get("減資原因", rec.get("權/息", ""))).strip()))
    out = pd.DataFrame(rows, columns=["date", "stock_id", "before_price", "ref_price", "kind", "source", "detail"])
    out = out[(out.before_price > 0) & (out.ref_price > 0)]
    return out.drop_duplicates(["date", "stock_id", "kind"]).reset_index(drop=True)

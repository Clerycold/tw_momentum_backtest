"""FinMind client with parquet cache, rate-limit handling and a hard dev-period end date."""
from __future__ import annotations
import os, time, json, logging
from pathlib import Path
import pandas as pd, requests

API = "https://api.finmindtrade.com/api/v4/data"
USER_INFO = "https://api.web.finmindtrade.com/v2/user_info"
log = logging.getLogger("finmind")


class FinMind:
    def __init__(self, raw_dir: Path, hard_end: str):
        self.raw = Path(raw_dir)
        self.hard_end = pd.Timestamp(hard_end)
        self.token = os.environ["FINMIND_TOKEN"]
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {self.token}"
        self.calls = 0

    def _wait_quota(self):
        """Block until the hourly quota has room again."""
        while True:
            try:
                j = self.s.get(USER_INFO, timeout=30).json()
                used, cap = j.get("user_count", 0), j.get("api_request_limit_hour", 600)
                if used < cap - 5:
                    return
                log.warning("quota %s/%s used, next_available=%s; sleeping 5 min", used, cap, j.get("next_available_time"))
            except Exception as e:  # network hiccup
                log.warning("user_info failed: %s", e)
            time.sleep(300)

    def fetch(self, dataset, subdir, name, data_id=None, start=None, end=None, refresh=False) -> pd.DataFrame:
        """Cached fetch. Empty results are cached as <name>.empty so they are not refetched.
        refresh=True drops the cache first (forward data that grows over time)."""
        if end is not None and pd.Timestamp(end) > self.hard_end:
            raise ValueError(f"end {end} beyond locked dev end {self.hard_end.date()}")
        d = self.raw / subdir
        d.mkdir(parents=True, exist_ok=True)
        f, fe = d / f"{name}.parquet", d / f"{name}.empty"
        if refresh:
            f.unlink(missing_ok=True); fe.unlink(missing_ok=True)
        if f.exists():
            return pd.read_parquet(f)
        if fe.exists():
            return pd.DataFrame()
        p = {"dataset": dataset}
        if data_id: p["data_id"] = data_id
        if start: p["start_date"] = start
        if end: p["end_date"] = end
        errors = 0
        while errors < 20:
            try:
                r = self.s.get(API, params=p, timeout=120)
                self.calls += 1
                j = r.json()
            except Exception as e:
                errors += 1
                log.warning("%s %s error %s; retry", dataset, data_id, e); time.sleep(30); continue
            if r.status_code == 402 or "limit" in str(j.get("msg", "")).lower():
                # quota hits do not count as errors; user_info can lag behind the API, so always pause
                self._wait_quota(); time.sleep(60); continue
            if j.get("status") != 200:
                raise RuntimeError(f"{dataset} {data_id}: {r.status_code} {j.get('msg')}")
            df = pd.DataFrame(j.get("data", []))
            if df.empty:
                fe.write_text(json.dumps(p))
            else:
                df.to_parquet(f, index=False)
            return df
        raise RuntimeError(f"giving up {dataset} {data_id}")

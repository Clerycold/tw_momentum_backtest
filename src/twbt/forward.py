"""Forward (paper) test of a post-hoc hypothesis: pre-registration lock and the single verdict rule."""
from __future__ import annotations
import json, time
from pathlib import Path
import pandas as pd, yaml

from .config import ROOT, sha256_file


def load_forward(path: Path = ROOT / "forward_B.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def check_forward_lock(fwd_path: Path = ROOT / "forward_B.yaml",
                       config_path: Path = ROOT / "config.yaml",
                       lock_path: Path = ROOT / "logs" / "forward_B_lock.json",
                       now: pd.Timestamp | None = None) -> str:
    """The strategy config must be the OOS-locked one; the pre-registration is frozen on first run,
    and that first run must happen before the forward period starts."""
    fwd = load_forward(fwd_path)
    if sha256_file(config_path) != fwd["strategy_config_sha256"]:
        raise RuntimeError("config.yaml differs from the strategy config named in the pre-registration")
    h = sha256_file(fwd_path)
    if lock_path.exists():
        locked = json.loads(lock_path.read_text())["forward_sha256"]
        if locked != h:
            raise RuntimeError(f"pre-registration changed since lock ({locked[:12]} -> {h[:12]})")
        return h
    now = pd.Timestamp.now() if now is None else pd.Timestamp(now)
    if now >= pd.Timestamp(fwd["period"]["forward_start"]):
        raise RuntimeError("cannot lock a pre-registration after the forward period has started")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps({"forward_sha256": h, "strategy_config_sha256": fwd["strategy_config_sha256"],
                                     "locked_at": now.strftime("%Y-%m-%d %H:%M:%S")}))
    return h


def verdict(m_chal: dict, m_bench: dict, last_date, evaluation_date, filter_triggered: bool) -> str:
    """'進度' until the evaluation date is covered by data; then exactly one of 通過 / 不通過 / 無法判定."""
    if pd.Timestamp(last_date) < pd.Timestamp(evaluation_date):
        return "進度（未到判定日，不構成結論）"
    if not filter_triggered:
        return "無法判定（濾網從未觸發，B 與 A 相同）"
    ok = m_chal["Sharpe"] > m_bench["Sharpe"] and abs(m_chal["MDD"]) <= abs(m_bench["MDD"])
    return "通過" if ok else "不通過"

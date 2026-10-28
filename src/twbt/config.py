"""Config loading, config lock (SHA256) and out-of-sample guard."""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
import pandas as pd, yaml

ROOT = Path(__file__).resolve().parents[2]
OOS_START = pd.Timestamp("2022-01-01")


class OOSLockedError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_config(path: Path = ROOT / "config.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def guard_period(cfg: dict, start, end, config_path: Path = ROOT / "config.yaml",
                 log_dir: Path = ROOT / "logs") -> None:
    """Refuse any period touching 2022-01-01+ unless oos_unlocked is true; the config hash is then logged."""
    if pd.Timestamp(end) < OOS_START and pd.Timestamp(start) < OOS_START:
        return
    if cfg.get("oos_unlocked") is not True:
        raise OOSLockedError(f"period {start}..{end} touches the locked out-of-sample range (>= {OOS_START.date()})")
    h = sha256_file(config_path)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(log_dir) / "oos_unlock_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "config_sha256": h,
                            "start": str(start), "end": str(end)}) + "\n")


OOS_ONLY_KEYS = {("periods", "oos_start"), ("periods", "oos_end"), ("oos_unlocked",)}


def _strip_oos(c: dict) -> dict:
    c = json.loads(json.dumps(c))
    for k in OOS_ONLY_KEYS:
        d = c
        for p in k[:-1]:
            d = d.get(p, {})
        d.pop(k[-1], None)
    return c


def check_oos_lock(config_path: Path = ROOT / "config.yaml",
                   dev_copy: Path = ROOT / "logs" / "config_dev_locked.yaml",
                   dev_lock: Path = ROOT / "logs" / "config_lock.json",
                   oos_lock: Path = ROOT / "logs" / "config_lock_oos.json") -> str:
    """OOS run: the dev-locked config must be intact and differ from the current one only in OOS keys;
    the current config hash is then frozen for all OOS runs."""
    dev_hash = json.loads(dev_lock.read_text())["config_sha256"]
    if sha256_file(dev_copy) != dev_hash:
        raise RuntimeError("archived dev config does not match the dev lock")
    if _strip_oos(load_config(dev_copy)) != _strip_oos(load_config(config_path)):
        raise RuntimeError("config differs from the dev-locked version beyond the OOS period / unlock keys")
    h = sha256_file(config_path)
    if oos_lock.exists():
        locked = json.loads(oos_lock.read_text())["config_sha256"]
        if locked != h:
            raise RuntimeError(f"config.yaml changed since OOS lock ({locked[:12]} -> {h[:12]})")
    else:
        oos_lock.write_text(json.dumps({"config_sha256": h, "dev_config_sha256": dev_hash,
                                        "locked_at": time.strftime("%Y-%m-%d %H:%M:%S")}))
    return h


def check_config_lock(config_path: Path = ROOT / "config.yaml",
                      lock_path: Path = ROOT / "logs" / "config_lock.json") -> str:
    """First run records the config hash; later runs must match it (dev parameters are frozen)."""
    h = sha256_file(config_path)
    if lock_path.exists():
        locked = json.loads(lock_path.read_text())["config_sha256"]
        if locked != h:
            raise RuntimeError(f"config.yaml changed since lock ({locked[:12]} -> {h[:12]}); dev parameters are frozen")
    else:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps({"config_sha256": h, "locked_at": time.strftime("%Y-%m-%d %H:%M:%S")}))
    return h

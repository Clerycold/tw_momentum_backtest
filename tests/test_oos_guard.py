import json
import pytest
from twbt.config import guard_period, OOSLockedError, check_config_lock


def test_dev_period_allowed(tmp_path):
    guard_period({"oos_unlocked": False}, "2015-01-01", "2021-12-31", tmp_path / "c.yaml", tmp_path)


def test_oos_blocked_by_default(tmp_path):
    with pytest.raises(OOSLockedError):
        guard_period({"oos_unlocked": False}, "2015-01-01", "2022-01-03", tmp_path / "c.yaml", tmp_path)


def test_oos_unlock_records_hash(tmp_path):
    cfgf = tmp_path / "c.yaml"
    cfgf.write_text("oos_unlocked: true\n")
    guard_period({"oos_unlocked": True}, "2022-01-01", "2023-01-01", cfgf, tmp_path)
    rec = json.loads((tmp_path / "oos_unlock_log.jsonl").read_text().splitlines()[0])
    assert len(rec["config_sha256"]) == 64


def test_config_lock_detects_change(tmp_path):
    cfgf, lock = tmp_path / "c.yaml", tmp_path / "lock.json"
    cfgf.write_text("a: 1\n")
    check_config_lock(cfgf, lock)
    check_config_lock(cfgf, lock)
    cfgf.write_text("a: 2\n")
    with pytest.raises(RuntimeError):
        check_config_lock(cfgf, lock)


def test_finmind_client_refuses_oos_end(tmp_path, monkeypatch):
    monkeypatch.setenv("FINMIND_TOKEN", "x")
    from twbt.finmind import FinMind
    with pytest.raises(ValueError):
        FinMind(tmp_path, "2021-12-31").fetch("TaiwanStockPrice", "price", "2330", "2330", "2021-01-01", "2022-01-05")

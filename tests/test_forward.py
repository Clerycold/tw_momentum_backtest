import json
import pytest
from twbt.config import sha256_file
from twbt.forward import check_forward_lock, verdict


def _files(tmp_path, start="2026-11-02"):
    c = tmp_path / "config.yaml"
    c.write_text("a: 1\n")
    f = tmp_path / "fwd.yaml"
    f.write_text(f"strategy_config_sha256: {sha256_file(c)}\nperiod:\n  forward_start: '{start}'\n")
    return f, c, tmp_path / "lock.json"


def test_lock_only_before_forward_start(tmp_path):
    f, c, lock = _files(tmp_path)
    with pytest.raises(RuntimeError):
        check_forward_lock(f, c, lock, now="2026-11-02")
    check_forward_lock(f, c, lock, now="2026-10-28")
    assert json.loads(lock.read_text())["locked_at"].startswith("2026-10-28")
    check_forward_lock(f, c, lock, now="2027-05-01")          # already locked -> later runs fine


def test_lock_detects_edits(tmp_path):
    f, c, lock = _files(tmp_path)
    check_forward_lock(f, c, lock, now="2026-10-28")
    f.write_text(f.read_text() + "x: 1\n")
    with pytest.raises(RuntimeError):
        check_forward_lock(f, c, lock, now="2026-10-29")


def test_strategy_config_must_match(tmp_path):
    f, c, lock = _files(tmp_path)
    c.write_text("a: 2\n")
    with pytest.raises(RuntimeError):
        check_forward_lock(f, c, lock, now="2026-10-28")


def test_verdict_rules():
    good, bad = {"Sharpe": 1.2, "MDD": -0.15}, {"Sharpe": 1.0, "MDD": -0.25}
    assert verdict(good, bad, "2028-01-01", "2029-10-31", True).startswith("進度")
    assert verdict(good, bad, "2029-10-31", "2029-10-31", False).startswith("無法判定")
    assert verdict(good, bad, "2029-10-31", "2029-10-31", True) == "通過"
    assert verdict({"Sharpe": 1.3, "MDD": -0.30}, bad, "2029-10-31", "2029-10-31", True) == "不通過"
    assert verdict({"Sharpe": 1.0, "MDD": -0.10}, bad, "2029-10-31", "2029-10-31", True) == "不通過"   # Sharpe tie fails

"""End-to-end smoke test on synthetic data: all strategies, metrics, attribution, charts, report."""
import pandas as pd
import pytest
from synth import make_market
from twbt.signals import Signals
from twbt.engine import Engine
from twbt.metrics import summarize, attribution_2x2
from twbt.report import plot_curves, write_report


def test_full_pipeline_synthetic(tmp_path):
    m, cfg = make_market()
    sig = Signals(m, cfg)
    res = {(st, sc): Engine(m, sig, cfg, st, sc).run() for sc in cfg["costs"]["slippage_scenarios"] for st in "ABCDE"}
    rows = [summarize(r, 1e6, res[("A", sc)].nav, sig.regime) for (st, sc), r in res.items()]
    met = pd.DataFrame(rows)
    a = met[met.scenario == "mid"].set_index("strategy")
    att = {sc: {k: attribution_2x2(met[met.scenario == sc].set_index("strategy")[k].to_dict()) for k in ["CAGR", "Sharpe", "MDD"]}
           for sc in cfg["costs"]["slippage_scenarios"]}
    f = att["mid"]["CAGR"]
    assert f["filter_effect"] + f["selection_effect"] == pytest.approx(f["total"])
    # higher slippage must not help
    assert (met[met.scenario == "high"].set_index("strategy").final_nav
            <= met[met.scenario == "low"].set_index("strategy").final_nav + 1e-6).all()
    # A has exposure ~1, B under weak filter would be lower; C/D satellite trades exist
    assert a.loc["C", "sat_trades"] > 0
    bias = pd.DataFrame(dict(signal_date=sig.monthly_days, pass_bcd=1, pass_bcd_delisted=0,
                             pass_bcd_delisted_no_revenue=0, pass_bcd_any_no_revenue=0))
    plot_curves(res, cfg, tmp_path)
    write_report(cfg, "x" * 64, m, sig, res, met, att, bias, tmp_path / "r.md")
    assert (tmp_path / "equity_drawdown_mid.png").exists()
    assert "策略 D 在開發期" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_filter_scales_exposure():
    m, cfg = make_market()
    m.taiex[:] = pd.Series(range(len(m.taiex), 0, -1), index=m.taiex.index).astype(float)   # falling -> weak
    sig = Signals(m, cfg)
    b = Engine(m, sig, cfg, "B", "mid").run()
    assert b.exposure.iloc[5:].max() < 0.35
    d = Engine(m, sig, cfg, "D", "mid").run()
    core = d.trades[d.trades.stock_id == "0050"]
    first = core.iloc[0]
    assert first.notional / 1e6 == pytest.approx(0.6 * 0.3, abs=0.01)

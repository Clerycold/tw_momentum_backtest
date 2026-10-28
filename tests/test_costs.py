import pytest
from twbt.costs import CostModel


def test_400k_round_trip_is_2340():
    # buy fee 570 + sell fee 570 + securities tax 1,200
    assert CostModel().round_trip_cost_ex_slippage(400_000) == pytest.approx(2340.0)


def test_fee_minimum_20():
    assert CostModel().fee(1000) == 20


def test_etf_tax_and_slippage():
    c = CostModel(slippage_stock=0.005)
    assert c.tax(100_000, is_etf=True) == pytest.approx(100)
    assert c.slippage(is_etf=True) == 0.0005
    assert c.slippage(is_etf=False, adv=1e9) == 0.005


def test_fee_discount():
    assert CostModel(fee_discount=0.6).fee(400_000) == pytest.approx(342.0)


def test_config_scenarios():
    from twbt.config import load_config
    c = load_config()["costs"]
    assert [CostModel.from_config(c, s).slippage(False, 1e8) for s in ("low", "mid", "high")] == [0.001, 0.003, 0.005]

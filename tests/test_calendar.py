import pandas as pd
from twbt.tcal import revenue_available_date, add_available_date, week_last_trading_days


def cal(*ds):
    return pd.DatetimeIndex(pd.to_datetime(list(ds)))


def test_on_trading_day():
    assert revenue_available_date(2019, 1, cal("2019-02-11", "2019-02-12")) == pd.Timestamp("2019-02-11")


def test_weekend_rolls_forward():
    # 2018-02-11 is a Sunday
    assert revenue_available_date(2018, 1, cal("2018-02-09", "2018-02-12")) == pd.Timestamp("2018-02-12")


def test_holiday_block_rolls_forward():
    # 10/11 and 10/12 closed -> next trading day 10/15
    assert revenue_available_date(2018, 9, cal("2018-10-09", "2018-10-15")) == pd.Timestamp("2018-10-15")


def test_december_revenue_goes_to_january():
    # 2020-01-11 is a Saturday
    assert revenue_available_date(2019, 12, cal("2020-01-10", "2020-01-13")) == pd.Timestamp("2020-01-13")


def test_vectorised_matches_scalar():
    d = pd.bdate_range("2019-01-01", "2019-12-31")
    rev = pd.DataFrame({"revenue_year": [2019] * 11 + [2018], "revenue_month": list(range(1, 12)) + [12]})
    out = add_available_date(rev, d)
    for _, r in out.iterrows():
        assert r.available_date == revenue_available_date(r.revenue_year, r.revenue_month, d)
        assert r.available_date.weekday() < 5 and r.available_date.day >= 11


def test_week_last_days():
    d = cal("2021-03-29", "2021-03-30", "2021-03-31", "2021-04-01", "2021-04-06")
    assert week_last_trading_days(d) == {pd.Timestamp("2021-04-01"), pd.Timestamp("2021-04-06")}

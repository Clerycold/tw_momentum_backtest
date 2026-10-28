import pandas as pd
from twbt.notify import filter_state, build_message

EXP = {True: 1.0, False: 0.3}


def _state(last_two):
    idx = pd.bdate_range("2026-01-01", periods=205)
    tx = pd.Series(100.0, index=idx)
    tx.iloc[-2:] = last_two
    return filter_state(tx, 200)


def test_state_uses_trailing_ma_only():
    st = _state([100.0, 110.0])
    assert len(st) == 6 and st.strong.iloc[-1] and not st.strong.iloc[-2]   # 100 is not > its own MA


def test_change_messages_carry_the_action():
    up = build_message(_state([100.0, 110.0]), EXP, None, "change")
    assert "轉為進攻" in up and "30% → 100%" in up and "明天開盤" in up
    st = _state([100.0, 110.0]).assign(strong=lambda d: [True] * (len(d) - 1) + [False])
    down = build_message(st, EXP, None, "change")
    assert "轉為防守" in down and "100% → 30%" in down


def test_brief_and_dividend():
    msg = build_message(_state([110.0, 111.0]), EXP, {"cash": 1.0}, "weekly")
    assert "每週訊號簡報" in msg and "已持續 2 個交易日" in msg and "無須動作" in msg and "除息" in msg

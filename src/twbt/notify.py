"""Daily market-filter signal (rule B) -> Telegram text. Bot settings are read from stock_mailer's .env, never copied."""
from __future__ import annotations
import os
import pandas as pd, requests

MAILER_ENV = os.environ.get("MAILER_ENV", r"C:\Users\Administrator\Desktop\claudeP\everyday\stock_mailer\.env")


def filter_state(taiex: pd.Series, ma_days: int) -> pd.DataFrame:
    ma = taiex.rolling(ma_days, min_periods=ma_days).mean()
    return pd.DataFrame({"close": taiex, "ma": ma, "gap": taiex / ma - 1, "strong": taiex > ma}).dropna()


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def build_message(st: pd.DataFrame, exposure: dict, div: dict | None, kind: str) -> str:
    """kind: 'change' (state flipped at the last close), 'weekly' (end-of-week brief), 'daily'."""
    last, prev = st.iloc[-1], st.iloc[-2]
    d = st.index[-1].strftime("%Y-%m-%d")
    now = exposure[bool(last.strong)]
    line = f"加權指數 {last.close:,.0f}｜200 日線 {last.ma:,.0f}｜差距 <b>{pct(last.gap)}</b>"
    if kind == "change":
        if last.strong:
            head = f"🟢 <b>轉為進攻：0050 {exposure[False]:.0%} → {now:.0%}</b>"
            todo = "明天開盤把 0050 買回到總資金的 100%。"
        else:
            head = f"🔴 <b>轉為防守：0050 {exposure[True]:.0%} → {now:.0%}</b>"
            todo = f"明天開盤賣出 0050，只留總資金的 {now:.0%}，其餘放現金。"
        out = [head, f"依 {d} 收盤", line, "", f"👉 {todo}",
               "<i>規則：收盤看訊號、次日開盤執行。指數在均線附近可能來回切換，照規則執行才和回測一致。</i>"]
    else:
        streak = int((st.strong[::-1] == st.strong.iloc[-1]).cumprod().sum())   # days in the current state
        title = "📅 <b>每週訊號簡報</b>" if kind == "weekly" else "📈 <b>每日訊號</b>"
        if last.strong:
            dist = f"大盤再跌約 {(1 - last.ma / last.close) * 100:.1f}% 會轉為防守"
        else:
            dist = f"大盤再漲約 {(last.ma / last.close - 1) * 100:.1f}% 會轉為進攻"
        out = [f"{title}　{d}", f"狀態：<b>0050 {now:.0%}</b>（{'進攻' if last.strong else '防守'}，已持續 {streak} 個交易日）",
               line, dist + "。", "無須動作。"]
    if div:
        out += ["", f"💰 0050 今天除息，每股 {div['cash']:.2f} 元。股利入帳後再投入 0050"
                    + ("（目前防守，留在現金即可）。" if not last.strong else "。")]
    return "\n".join(out)


def stale_message(last_date: pd.Timestamp, today: pd.Timestamp) -> str:
    return (f"⚠ <b>資產配置訊號：資料沒有更新</b>\n最新資料停在 {last_date:%Y-%m-%d}，今天 {today:%Y-%m-%d}。"
            "\n可能是 FinMind 尚未更新或額度用完；今天的訊號無法確認，請明天再看一次。")


def send_telegram(text: str, dry_run: bool = False) -> None:
    if dry_run:
        print("[dry-run] Telegram:\n" + text)
        return
    from dotenv import dotenv_values
    cfg = dotenv_values(MAILER_ENV)
    tok, chat = (cfg.get("TELEGRAM_BOT_TOKEN") or "").strip(), (cfg.get("TELEGRAM_CHAT_ID") or "").strip()
    if not tok or not chat:
        raise RuntimeError("沒有設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=(5, 15),
                          json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    except requests.RequestException as e:   # the exception text contains the URL, i.e. the bot token
        raise RuntimeError(f"Telegram 連線失敗：{type(e).__name__}") from None
    if not r.json().get("ok"):
        raise RuntimeError(f"Telegram 回應錯誤：{r.json().get('description')}")

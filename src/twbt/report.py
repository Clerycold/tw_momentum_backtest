"""Charts and markdown report for the development run."""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# categorical slots 1-5 of the reference palette (light), fixed order per strategy
COLORS = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a", "D": "#eda100", "E": "#e87ba4"}
LABELS = {"A": "A 0050 買進持有", "B": "B 0050+濾網", "C": "C 核心+衛星", "D": "D 核心+衛星+濾網", "E": "E 純衛星"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _style(ax):
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def plot_curves(results, cfg, out: Path):
    init = cfg["backtest"]["initial_capital"]
    for sc in cfg["costs"]["slippage_scenarios"]:
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True, gridspec_kw={"height_ratios": [3, 1.6]})
        for st in cfg["backtest"]["strategies"]:
            nav = results[(st, sc)].nav / init
            dd = nav / nav.cummax() - 1
            a1.plot(nav.index, nav, color=COLORS[st], lw=2, label=LABELS[st])
            a1.annotate(f"{LABELS[st].split()[0]} {nav.iloc[-1]:.2f}x", (nav.index[-1], nav.iloc[-1]),
                        xytext=(6, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
            a2.plot(dd.index, dd * 100, color=COLORS[st], lw=1.5)
        a1.set_yscale("log")
        # plain "1.5x" tick labels: the default log formatter uses mathtext minus glyphs missing from CJK fonts
        a1.yaxis.set_major_locator(matplotlib.ticker.LogLocator(base=10, subs=(0.5, 0.6, 0.7, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)))
        a1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}x"))
        a1.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        a1.set_ylabel("淨值（倍，對數）", color=MUTED)
        a1.set_title(f"權益曲線與回撤（{cfg['periods']['dev_start'][:4]}–{cfg['periods']['dev_end'][:4]}，扣除成本，滑價情境 {sc}）", color=INK, loc="left", fontsize=12)
        a1.legend(frameon=False, fontsize=9, loc="upper left")
        a2.set_ylabel("回撤 %", color=MUTED)
        _style(a1); _style(a2)
        fig.tight_layout()
        fig.savefig(out / f"equity_drawdown_{sc}.png", dpi=140)
        plt.close(fig)


def _fmt_table(df, cols, pct=(), dec=()):
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    lines = []
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (float, np.floating)):
                cells.append("—" if pd.isna(v) else f"{v*100:.2f}%" if c in pct else f"{v:,.2f}" if c in dec else f"{v:,.0f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return head + "\n".join(lines) + "\n"


def write_report(cfg, cfg_hash, mkt, sig, results, metrics, attrib, bias, path: Path, variant: str = ""):
    sc_list = list(cfg["costs"]["slippage_scenarios"])
    crit = cfg["success_criterion"]
    m = metrics.set_index(["strategy", "scenario"])
    d, a = m.loc[(crit["strategy"], crit["slippage_scenario"])], m.loc[(crit["benchmark"], crit["slippage_scenario"])]
    sharpe_ok, mdd_ok = d.Sharpe > a.Sharpe, abs(d.MDD) <= abs(a.MDD)
    verdict = "成立" if (sharpe_ok and mdd_ok) else "不成立"

    phase = cfg.get("_phase", "開發期")
    ps, pe = cfg["periods"]["dev_start"], cfg["periods"]["dev_end"]
    L = []
    L.append(f"# {phase}回測報告：{ps} ~ {pe}" + (f"（{variant}）" if variant else "") + "\n")
    if variant == "v2_corrected" or phase == "樣本外":
        L.append("> 資料修正：(1) 移除興櫃期間 K 線（以價格是否落在上市櫃跳動單位、且開收盤介於高低價之間偵測上市日，"
                 "對證交所官方上市日期驗證 103/109 完全一致），整段期間仍為興櫃者排除；(2) 以證交所／櫃買中心官方減資與除權息紀錄"
                 "補足 FinMind 缺漏的公司行為。詳見 docs/flag_review.md。策略參數未變更。\n")
    L.append(f"- config SHA256：`{cfg_hash}`" + cfg.get("_lock_note", "（第一次執行時鎖定，存於 `logs/config_lock.json`）"))
    L.append(cfg.get("_oos_note", "- 樣本外（2022-01-01 起）：鎖定，未執行、未查看"))
    L.append(f"- 初始資金：{cfg['backtest']['initial_capital']:,} 元；所有數字皆已扣除手續費、證交稅與滑價\n")

    L.append("## 1. 預先宣告判準的結果\n")
    L.append(f"判準（跑之前已寫入 config）：mid 滑價下，扣除成本後 Sharpe(D) > Sharpe(A)，且 |MDD(D)| ≤ |MDD(A)|。\n")
    L.append("| 項目 | D | A | 是否通過 |\n|---|---|---|---|")
    L.append(f"| Sharpe | {d.Sharpe:.3f} | {a.Sharpe:.3f} | {'✅' if sharpe_ok else '❌'} |")
    L.append(f"| MDD | {d.MDD*100:.2f}% | {a.MDD*100:.2f}% | {'✅' if mdd_ok else '❌'} |")
    L.append(f"\n**結論：策略 D 在{phase}{verdict}。** 其他指標只作診斷，不影響這個判定。\n")

    L.append("## 2. 主要指標（所有組合 × 所有滑價情境）\n")
    for sc in sc_list:
        x = metrics[metrics.scenario == sc]
        L.append(f"### 滑價情境：{sc}（普通股單邊 {cfg['costs']['slippage_scenarios'][sc]*100:.1f}%，ETF {cfg['costs']['slippage_etf']*100:.2f}%）\n")
        L.append(_fmt_table(x, ["strategy", "CAGR", "MDD", "Sharpe", "excess_CAGR_vs_A", "final_nav"],
                            pct=("CAGR", "MDD", "excess_CAGR_vs_A"), dec=("Sharpe",)))
        L.append(f"![equity](equity_drawdown_{sc}.png)\n")

    L.append("## 3. 2×2 歸因\n")
    L.append("A = 都沒有、B = 只有濾網、C = 只有選股（衛星）、D = 兩者都有。")
    L.append("- 濾網貢獻 = [(B−A) + (D−C)] / 2：在「有衛星」與「沒衛星」兩種情況下，加上濾網的平均效果")
    L.append("- 選股貢獻 = [(C−A) + (D−B)] / 2：在「有濾網」與「沒濾網」兩種情況下，加入衛星的平均效果")
    L.append("- 交互作用 = (D−C) − (B−A)：濾網在有衛星時的效果，比沒衛星時多（或少）多少\n")
    for sc in sc_list:
        L.append(f"**{sc}**\n\n| 指標 | 濾網貢獻 | 選股貢獻 | 交互作用 | D−A 合計 |\n|---|---|---|---|---|")
        for k, v in attrib[sc].items():
            f = (lambda z: f"{z*100:+.2f}%") if k in ("CAGR", "MDD") else (lambda z: f"{z:+.3f}")
            L.append(f"| {k} | {f(v['filter_effect'])} | {f(v['selection_effect'])} | {f(v['interaction'])} | {f(v['total'])} |")
        L.append("")
    L.append("注意：MDD 是負數，MDD 的歸因為正代表回撤變小（改善）。濾網貢獻 + 選股貢獻 = D−A 合計；交互作用是另外的診斷量，不再加進合計。\n")

    L.append("## 4. 診斷指標（不用於判定）\n")
    diag = ["strategy", "scenario", "turnover", "cost_total", "cost_share_of_gross", "avg_exposure",
            "bull_ann_ret", "bear_ann_ret", "sideways_ann_ret"]
    L.append(_fmt_table(metrics, diag, pct=("cost_share_of_gross", "avg_exposure", "bull_ann_ret", "bear_ann_ret", "sideways_ann_ret"),
                        dec=("turnover",)))
    L.append("- turnover：年化換手率 =（買進＋賣出成交金額）/ 2 / 平均淨值 / 年數")
    L.append("- cost_share_of_gross：交易成本 /（期末淨值 − 初始資金 + 交易成本）")
    rg = sig.regime.loc[cfg["periods"]["dev_start"]:cfg["periods"]["dev_end"]].value_counts()
    L.append(f"- 多空盤整劃分（TAIEX 收盤相對 200 日線，且 200 日線 20 日斜率同向）：多頭 {rg.get('bull',0)} 天、空頭 {rg.get('bear',0)} 天、盤整 {rg.get('sideways',0)} 天；每日報酬依前一日收盤的狀態歸類，數字為該狀態下的年化報酬\n")
    sat = metrics[metrics.strategy.isin(["C", "D", "E"])]
    L.append("### 衛星交易統計（完整進出為一筆，期末未平倉以最後收盤價計）\n")
    L.append(_fmt_table(sat, ["strategy", "scenario", "sat_trades", "sat_avg_hold_days", "win_rate", "profit_factor", "top5_share_of_profit", "blocked_orders"],
                        pct=("win_rate", "top5_share_of_profit"), dec=("sat_avg_hold_days", "profit_factor")))
    L.append("- sat_avg_hold_days 以交易日計；blocked_orders = 開盤漲停買不到 + 開盤跌停賣不掉的次數\n")

    L.append("## 5. 存活者偏差的規模（決策 1a）\n")
    b = bias[bias.signal_date >= cfg["periods"]["dev_start"]]
    L.append(f"在 {len(b)} 個月度訊號日中，平均每次有 {b.pass_bcd.mean():.1f} 檔股票同時符合 b（站上 60 日線）、c（RS 前 20%）、d（成交金額）。")
    L.append(f"其中「之後在{phase}內下市」者平均 {b.pass_bcd_delisted.mean():.2f} 檔，這些股票中缺營收資料者平均 {b.pass_bcd_delisted_no_revenue.mean():.2f} 檔；"
             f"最多的一個月為 {b.pass_bcd_delisted_no_revenue.max()} 檔。")
    L.append(f"相對地，所有「符合 b/c/d 但缺營收」的股票（含存活股）平均 {b.pass_bcd_any_no_revenue.mean():.2f} 檔。")
    L.append("解讀：這是偏差的**上界**——即使營收資料完整，它們還要通過條件 a 並排進前 8 名才會被選入。明細在 `survivorship_bias_check.csv`。\n")

    L.append("## 6. 資料假設與限制\n")
    st = cfg["data"]
    L.append(f"""**資料來源與範圍**
- FinMind Free 等級；日 K 自 {st['price_start']}、月營收自 {st['revenue_start']}（暖機），回測期間 {cfg['periods']['dev_start']} ~ {cfg['periods']['dev_end']}；下載程式強制結束日 ≤ {pe}
- 股票池：{mkt.close.shape[1]-1} 檔上市櫃 4 位數普通股（含{phase}內下市者 {sum(1 for _, (_, lb) in mkt.delist.items() if pd.Timestamp(ps) <= lb <= pd.Timestamp(pe))} 檔），排除 ETF / ETN / 權證 / 特別股 / DR / 興櫃。每天只有「當天有有效 K 線」的股票可交易與排名
- 收盤價為 0 的資料列（停牌）視為無交易
- **全額交割股無法辨識，未排除**（Free 等級無資料；使用者同意）

**月營收 point-in-time**
- FinMind `date` 欄位是「營收月份 +1 個月的 1 號」，不是公告日；`create_time` 全空 → 一律以次月 {st['revenue_available_day']} 日為可用日，遇非交易日順延
- 訊號日 = 可用日當天收盤，次一交易日開盤調倉；程式在每次執行時斷言「所有用到的營收可用日 ≤ 訊號日」（另有 pytest）
- 最新可用營收月份若落後訊號月份超過 {st['max_revenue_staleness_months']} 個月，視為資料中斷，條件 a 不成立
- 無法得知營收是首次公告值還是更正值
- **下市股的營收大量缺漏**（抽樣 20 檔僅 4 檔完整）→ 存活者偏差，規模見第 5 節（使用者決策 1a：接受並量化）

**價格還原**
- `TaiwanStockPriceAdj` 不可用，以 DividendResult（除權息參考價）、SplitPrice / ParValueChange（分割、面額變更）自行計算還原因子；還原價只用於均線與報酬率，成交與漲跌停一律用原始價
- 共 {len(mkt.events)} 個公司行為事件
- 減資無資料：偵測到 {len(mkt.flags)} 個「無已知事件可解釋、且超過漲跌幅限制」的跳動，清單在 `flagged_price_jumps_for_review.csv` 待人工核對。處理方式：還原因子取 開盤/前收；持有中則以開盤價等值調整股數；之後 {cfg['capital_action_detection']['signal_blackout_days']} 個交易日不得作為新進場標的
- 現金股利（「息」）在除息日入帳為現金；「權」「權息」因資料未拆分現金與股票部分，以參考價等值調整股數（零股部分以參考價折現）。股利所得稅、二代健保補充保費未計

**執行假設**
- 訊號日收盤產生訊號，次一交易日開盤成交；先賣後買，現金不足時等比例縮減買單
- **股數取整數股**（不限 1,000 股整張）。2020-10-26 前盤中無法零股交易，實際可行性較低；整數股假設在本資金規模下對 0050 影響小，對高價衛星股可能造成實際權重偏離
- 漲跌停：開盤 ≥ 參考價 × 上限視為買不到，≤ 參考價 × 下限視為賣不掉、延後一日；2015-06-01 前用 ±7%（1.065 / 0.935），之後 ±10%（1.095 / 0.905）（使用者決策 2）。參考價 = 前一有效收盤，除權息 / 分割日用公告參考價
- 0050 核心買不到時隔日重試；衛星新進場買不到則該格留現金至下次月調倉
- 衛星每檔固定 1/8 衛星資金，不足 8 檔的空位留現金
- 月調倉時，既有部位偏離目標權重超過 {cfg['satellite']['rebalance_tolerance']*100:.0f}% 才調整；濾網狀態改變時所有部位等比例縮放到新目標
- 每週最後一個交易日檢查衛星是否跌破 60 日線（月調倉日當天以月調倉規則為準）
- A、B 的 0050 現金股利於次一交易日再投入；C、D 的股利留在現金，月調倉時一併調整
- 下市股：在最後一根有效 K 線當天以收盤價（扣滑價與成本）強制出場。部分股票停止交易數月後才下市，這個假設偏樂觀（實際資金可能被卡住）
- 同產業最多 3 檔：產業為 TaiwanStockInfo 的當前分類（無歷史分類），去除「電子工業」大類並合併新舊名稱；無分類者各自視為獨立產業

**成本**
- 手續費 0.1425% × 折扣 {cfg['costs']['fee_discount']}，單筆最低 {cfg['costs']['fee_min']} 元；賣出證交稅普通股 0.3%、ETF 0.1%
- 滑價依情境 low / mid / high = 0.1% / 0.3% / 0.5%（ETF 固定 0.05%）；依 20 日均量分級的倍數已參數化，預設全部為 1.0
- 單元測試：40 萬元普通股完整買賣一次，未計滑價成本 = 2,340 元

**指標**
- Sharpe：日報酬、無風險利率 {cfg['backtest']['risk_free']}、年化 √{cfg['backtest']['trading_days_per_year']}
- 超額報酬 = 策略 CAGR − 同情境 A 的 CAGR
""")
    L.append("## 7. 輸出檔案\n")
    sfx = "oos" if cfg.get("_phase") == "樣本外" else "dev_2015_2021"
    L.append(f"- `trades_{sfx}.csv`：每筆成交明細（所有策略 × 情境）")
    L.append(f"- `satellite_roundtrips_{sfx}.csv`：衛星完整進出")
    L.append(f"- `metrics_{sfx}.csv`：完整指標表")
    L.append("- `selection_revenue_audit.csv`：每次選股用到的營收月份與可用日（前視偏誤稽核）")
    L.append("- `flagged_price_jumps_for_review.csv`、`survivorship_bias_check.csv`")
    L.append("- `equity_drawdown_{low,mid,high}.png`")
    path.write_text("\n".join(L), encoding="utf-8")

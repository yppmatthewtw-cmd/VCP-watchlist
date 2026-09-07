#!/usr/bin/env python3
"""Revenue / profitability workbook for the Combined Watchlist R14 universe,
in the layout of the uploaded AI_Growth_Breakeven_Watchlist_R7 workbook.

Source: data/yahoo/fundamentals_<date>.json.gz — quarterly income statements
pulled from Yahoo Finance on a GitHub Actions runner (the research container's
egress proxy blocks Yahoo). Every number in the workbook is a reported income
statement line item; nothing is estimated except the analyst columns, which are
labelled as such.

R7 splits each quarter's profit cell into 淨利 / 經常 / 一次. The same split is
kept here and made fully data-driven:
  淨利 = Net Income Common Stockholders (GAAP)
  經常 = Operating Income (falls back to Pretax Income minus unusual items for
         banks/insurers, where Yahoo reports no operating line) — R7's
         "經常 = 營運利潤 / 可持續部分"
  一次 = Total Unusual Items net of Tax Effect Of Unusual Items
"""
import gzip, json, os, sys
from datetime import datetime, timedelta, timezone

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from exchanges import tv_url

SRC = sys.argv[1] if len(sys.argv) > 1 else "data/yahoo/fundamentals_2026-09-06.json.gz"
META = json.load(open("data/yahoo/r14_meta.json"))
FUND = json.load(gzip.open(SRC, "rt"))
BASIS = "2026-09-04"          # Combined Watchlist R14 price basis

HEAD_FILL = PatternFill("solid", fgColor="FF1F4E78")
HEAD_FONT = Font(b=True, sz=9.5, color="FFFFFFFF")
BODY_FONT = Font(sz=9.5)
MONO = Border(*[Side(style="thin", color="FFD0D0D0")] * 4)
TITLE_FONT = Font(b=True, sz=12)
GRADE_FILL = {"A": PatternFill("solid", fgColor="FFDFF3E3"),
              "B": PatternFill("solid", fgColor="FFEAF2FB"),
              "C": PatternFill("solid", fgColor="FFFDF3DC"),
              "D": PatternFill("solid", fgColor="FFFBE4E2"),
              "—": PatternFill("solid", fgColor="FFF2F2F2")}
SYM = {"USD": "$", "CAD": "C$", "EUR": "€", "GBP": "£", "NOK": "kr", "SEK": "kr",
       "TWD": "NT$", "ILS": "₪", "BRL": "R$", "ZAR": "R", "MXN": "MX$", "JPY": "¥"}


def g(rec, *keys):
    for k in keys:
        if rec.get(k) is not None:
            return rec[k]
    return None


def m(v):
    """income-statement value -> millions"""
    return None if v is None else v / 1e6


def q_metrics(q):
    """One quarter -> revenue, operating (recurring), net, unusual, margins."""
    rev = m(g(q, "Total Revenue", "Operating Revenue"))
    op = m(g(q, "Operating Income", "Total Operating Income As Reported"))
    net = m(g(q, "Net Income Common Stockholders", "Net Income",
              "Net Income From Continuing Operation Net Minority Interest"))
    unusual = m(g(q, "Total Unusual Items", "Total Unusual Items Excluding Goodwill",
                  "Special Income Charges"))
    taxeff = m(g(q, "Tax Effect Of Unusual Items"))
    if unusual is not None and taxeff is not None:
        unusual -= taxeff                                  # after-tax one-off
    src = "營運"
    if op is None:                                         # banks / insurers / REITs
        pre = m(g(q, "Pretax Income"))
        if pre is not None:
            op = pre - (unusual or 0)
            src = "稅前剔一次性"
    gross = m(g(q, "Gross Profit"))
    return {"period": q.get("period"), "rev": rev, "op": op, "net": net,
            "unusual": unusual, "gross": gross, "op_src": src}


def money(v, cur):
    if v is None:
        return "—"
    s = SYM.get(cur, cur + " ")
    a = abs(v)
    if a >= 1000:
        return f"{'-' if v < 0 else '+'}{s}{a/1000:,.2f}B"
    return f"{'-' if v < 0 else '+'}{s}{a:,.1f}M"


def profit_cell(qm, cur):
    """R7's three-line profit cell: 淨利 / 經常 / 一次."""
    if qm is None:
        return "—"
    lines = [f"淨利 {money(qm['net'], cur)}"]
    if qm["op"] is not None:
        tag = "經常" if qm["op_src"] == "營運" else "經常*"
        lines.append(f"{tag} {money(qm['op'], cur)}")
    else:
        lines.append("經常 —")
    u = qm["unusual"]
    if u is None or (qm["rev"] and abs(u) < 0.01 * abs(qm["rev"])) or (qm["rev"] is None and abs(u) < 1):
        lines.append("一次: 無重大")
    else:
        pct = f"（營收 {abs(u)/qm['rev']*100:.0f}%）" if qm["rev"] else ""
        lines.append(f"一次: {money(u, cur)}{pct}")
    return "\n".join(lines)


def grade_of(qs):
    """Mechanical grade in R7's spirit — recurring (operating) profitability."""
    if not qs or qs[0]["rev"] is None:
        return "—", "無足夠財報數據"
    ops = [q["op"] for q in qs[:4]]
    nets = [q["net"] for q in qs[:4]]
    q0, older = qs[0], qs[min(3, len(qs) - 1)]
    if all(o is not None and o > 0 for o in ops) and (nets[0] or 0) > 0:
        return "A", "四季營運皆正、最新季淨利為正 — 經常性已盈利"
    if (q0["op"] or 0) > 0 or (nets[0] or 0) > 0:
        if (q0["op"] or 0) > 0 and (nets[0] or 0) <= 0:
            return "B", "最新季營運為正但淨利為負（利息／一次性／稅拖累）"
        if (q0["op"] or 0) <= 0 < (nets[0] or 0):
            return "B", "最新季淨利為正但營運仍虧 — 靠營運外項目"
        return "B", "最新季已盈利，惟四季未全正 — 盈利未穩定"
    if older["op"] is not None and (q0["op"] or 0) > older["op"]:
        return "C", "仍虧損，但營運虧損較 Q-3 收窄"
    return "D", "營運仍虧損且未見收窄"


def track_text(qs):
    ops = [q["op"] for q in qs[:4]][::-1]                  # Q-3 -> Q0
    if any(o is None for o in ops) or len(ops) < 2:
        return "—（缺營運利潤，見經常*註）"
    arrow = " → ".join(f"{o:+,.0f}" for o in ops)
    pos = [o > 0 for o in ops]
    if all(pos):
        shape = "四季皆正"
    elif pos[-1] and not pos[0]:
        shape = "由虧轉正"
    elif not pos[-1] and pos[0]:
        shape = "由正轉虧"
    elif not any(pos):
        shape = "四季皆虧（收窄）" if ops[-1] > ops[0] else "四季皆虧（擴大）"
    else:
        shape = "反覆"
    return f"{shape}：{arrow}（百萬）"


rows = []
for t, meta in META.items():
    f = FUND.get(t, {})
    qs = [q_metrics(q) for q in f.get("quarters", [])]
    qs = [q for q in qs if q["rev"] is not None or q["net"] is not None]
    info = f.get("info", {})
    cur = info.get("financialCurrency") or info.get("currency") or "USD"
    q0 = qs[0] if qs else None
    yoy = None
    if len(qs) >= 5 and q0 and q0["rev"] and qs[4]["rev"]:
        yoy = (q0["rev"] / qs[4]["rev"] - 1) * 100
    rev_est = (f.get("rev_est") or {}).get("+1q", {})
    eps_est = (f.get("eps_est") or {}).get("+1q", {})
    grade, verdict = grade_of(qs)
    rows.append({
        "t": t, "name": info.get("longName") or meta["name"], "sector": meta["sector"],
        "industry": info.get("industry") or "", "mcap": (meta["mcap"] or 0) / 1e9, "cur": cur,
        "periods": " / ".join(q["period"] for q in qs[:4][::-1]) if qs else "—",
        "rev": [qs[i]["rev"] if i < len(qs) else None for i in (3, 2, 1, 0)],
        "yoy": yoy,
        "rev_est": (rev_est.get("avg") or 0) / 1e6 or None,
        "rev_est_g": (rev_est.get("growth") or 0) * 100 or None,
        "prof": [profit_cell(qs[i] if i < len(qs) else None, cur) for i in (3, 2, 1, 0)],
        "eps_est": eps_est.get("avg"), "eps_n": eps_est.get("numberOfAnalysts"),
        "op_m": (q0["op"] / q0["rev"] * 100) if q0 and q0["op"] is not None and q0["rev"] else None,
        "net_m": (q0["net"] / q0["rev"] * 100) if q0 and q0["net"] is not None and q0["rev"] else None,
        "gross_m": (q0["gross"] / q0["rev"] * 100) if q0 and q0["gross"] is not None and q0["rev"] else None,
        "unusual": q0["unusual"] if q0 else None, "unusual_rev": (q0["rev"] if q0 else None),
        "track": track_text(qs) if qs else "—",
        "grade": grade, "verdict": verdict,
        "asof": qs[0]["period"] if qs else "—",
        "next": (f.get("next_earnings") or "")[:10],
        "q0": q0,
    })

order = {"A": 0, "B": 1, "C": 2, "D": 3, "—": 4}
rows.sort(key=lambda r: (order[r["grade"]], -(r["mcap"] or 0)))

wb = openpyxl.Workbook()

# ---------------------------------------------------------------- 說明
ws = wb.active
ws.title = "說明"
stamp = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M HKT")
n_by = {k: sum(1 for r in rows if r["grade"] == k) for k in ("A", "B", "C", "D", "—")}
lines = [
    ("Combined Watchlist R14 — 274 隻美股「營收及營利」總表", TITLE_FONT),
    (f"編製 {stamp}｜格式沿用 AI_Growth_Breakeven_Watchlist_R7｜價格基準 2026-09-04 收盤", None),
    ("", None),
    ("【本表是甚麼】", Font(b=True, sz=10)),
    ("• 對象＝Combined Watchlist R14 的全部 274 隻股票（VCP 167＋Weinstein 167＋Pre-breakout 116，去重後 274）。", None),
    ("• 內容＝每隻最近四個季度的營收與營利（淨利／經常／一次），加最新一季的三個利潤率、分析師下季預測、盈利狀態分級。", None),
    ("", None),
    ("【數據來源與方法】", Font(b=True, sz=10)),
    ("• 全部財務數字取自 Yahoo Finance 的季度損益表（income statement）原始項目，由 GitHub Actions runner 以 yfinance 拉取後提交至", None),
    ("  data/yahoo/fundamentals_2026-09-06.json.gz（研究容器的 egress proxy 封鎖 Yahoo，故與 R14 價格數據同樣改由 runner 抓取）。", None),
    ("• 單位一律「百萬」，幣別看【幣別】欄（financialCurrency）— 外國發行人／ADR 的財報幣別未必是美元。", None),
    ("• 季度以財報期末日期標示（【季度對照】欄），非日曆季 — 各公司財政年度不同，比較前請先看該欄。", None),
    ("", None),
    ("【營利三行的定義 — 沿用 R7】", Font(b=True, sz=10)),
    ("• 淨利 = Net Income Common Stockholders（GAAP 帳面）。", None),
    ("• 經常 = Operating Income（營運利潤，即 R7 的「可持續部分」）。", None),
    ("• 經常* = 該公司 Yahoo 不提供營運利潤（銀行／保險／部分 REIT），改以「稅前利潤 − 一次性項目」代替，已用星號標示。", None),
    ("• 一次 = Total Unusual Items 扣除 Tax Effect Of Unusual Items（稅後一次性項目）。金額小於營收 1% 者標「無重大」。", None),
    ("• ⚠ 與 R7 的重要分別：R7 的 42 隻是逐隻人手查證財報原文與新聞後拆解一次性項目；本表 274 隻是機器抽取 Yahoo 的", None),
    ("  Unusual Items 欄位，只能捕捉「公司自己在損益表分類為非經常」的項目（減值、重組、訴訟和解、資產出售等）。", None),
    ("  股權酬勞（SBC）、公允值重估、匯兌等仍計在經常內；要達到 R7 的拆解深度必須逐隻人手核實。", None),
    ("", None),
    ("【分級規則（機械判定，非人手核實）】", Font(b=True, sz=10)),
    (f"• A（{n_by['A']} 隻）四季營運利潤皆為正，且最新季淨利為正 — 經常性已盈利。", None),
    (f"• B（{n_by['B']} 隻）最新季已盈利，但四季未全正，或淨利與營運方向不一致（靠營運外項目／被利息拖累）。", None),
    (f"• C（{n_by['C']} 隻）最新季營運仍虧損，但較 Q-3 收窄。", None),
    (f"• D（{n_by['D']} 隻）營運仍虧損且未見收窄。", None),
    (f"• —（{n_by['—']} 隻）Yahoo 無足夠季度損益表數據（多為外國發行人或半年度披露者）。", None),
    ("", None),
    ("【分頁】", Font(b=True, sz=10)),
    ("• 營收營利表：主表，274 隻，按級別 A→D、再按市值排序；欄標題可篩選、可排序。", None),
    ("• 一次性項目：最新一季一次性項目金額達營收 2% 或 5,000 萬以上者，按絕對金額排序。", None),
    ("• 軌跡排隊：按四季營運利潤方向分組（四季皆正／由虧轉正／由正轉虧／虧損收窄／虧損擴大）。", None),
    ("• 分級彙總：各級數量（COUNTIF 連動主表）與代號一覽。", None),
    ("• 圖表連結：274 隻 TradingView 連結，與 Combined Watchlist 同一 layout。", None),
    ("", None),
    ("【免責】本表為公開資料整理與研究參考，非投資建議。財務數據以各公司正式公告為準；Yahoo 的損益表分類偶有錯漏，", None),
    ("  下判斷前請以公司財報原文覆核。", None),
]
for i, (txt, font) in enumerate(lines, 1):
    c = ws.cell(row=i, column=1, value=txt)
    c.font = font or Font(sz=9.5)
    c.alignment = Alignment(wrap_text=False, vertical="center")
ws.column_dimensions["A"].width = 118

# ---------------------------------------------------------------- 主表
ws = wb.create_sheet("營收營利表")
HDR = [("#", 4), ("美股 Ticker\n(按=開圖)", 11), ("公司", 26), ("板塊", 13), ("行業", 22),
       ("市值\n(十億美元)", 9), ("幣別", 7), ("季度對照 (Q-3 → Q0)\n財報期末日", 25),
       ("營收 Q-3\n(百萬)", 11), ("營收 Q-2\n(百萬)", 11), ("營收 Q-1\n(百萬)", 11),
       ("營收 Q0 最新\n(百萬)", 12), ("營收按年\nQ0 vs 去年同期 %", 12),
       ("下季營收預測\n(百萬・分析師平均)", 13),
       ("營利 Q-3\n淨利｜經常｜一次", 17), ("營利 Q-2\n淨利｜經常｜一次", 17),
       ("營利 Q-1\n淨利｜經常｜一次", 17), ("營利 Q0 (最新)\n淨利｜經常｜一次", 17),
       ("下季 EPS 預測\n(分析師平均)", 12), ("營業利潤率\nQ0 %", 10), ("淨利率\nQ0 %", 10),
       ("毛利率\nQ0 %", 10), ("【一次性項目】\nQ0 金額・佔營收", 26),
       ("【經常性軌跡】\n四季營運利潤 Q-3→Q0 (百萬)", 34), ("判斷結論 (盈利狀態)", 30),
       ("級", 5), ("資料截至\n(最新季 / 下次財報)", 14)]
for j, (h, w) in enumerate(HDR, 1):
    c = ws.cell(row=1, column=j, value=h)
    c.font, c.fill = HEAD_FONT, HEAD_FILL
    c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    ws.column_dimensions[get_column_letter(j)].width = w
ws.row_dimensions[1].height = 51.75

for i, r in enumerate(rows, 2):
    vals = [i - 1, r["t"], r["name"], r["sector"], r["industry"], r["mcap"] or None, r["cur"],
            r["periods"], *r["rev"], r["yoy"], r["rev_est"],
            *r["prof"], r["eps_est"],
            r["op_m"], r["net_m"], r["gross_m"],
            (money(r["unusual"], r["cur"]) + (f"・營收 {abs(r['unusual'])/r['unusual_rev']*100:.1f}%"
                                              if r["unusual"] and r["unusual_rev"] else ""))
            if r["unusual"] and r["unusual_rev"] and abs(r["unusual"]) >= 0.01 * r["unusual_rev"] else "無重大",
            r["track"], r["verdict"], r["grade"],
            f"{r['asof']}" + (f" / {r['next']}" if r["next"] else "")]
    for j, v in enumerate(vals, 1):
        c = ws.cell(row=i, column=j, value=v)
        c.font, c.border = BODY_FONT, MONO
        if j in (9, 10, 11, 12, 14):
            c.number_format = "#,##0.0"
            c.alignment = Alignment(horizontal="right")
        elif j in (13, 20, 21, 22):
            c.number_format = '#,##0.0"%"'
            c.alignment = Alignment(horizontal="right")
        elif j == 6:
            c.number_format = "#,##0.0"
            c.alignment = Alignment(horizontal="right")
        elif j == 19:
            c.number_format = "#,##0.00"
            c.alignment = Alignment(horizontal="right")
        elif j in (15, 16, 17, 18):
            c.alignment = Alignment(wrap_text=True, vertical="top")
        elif j in (23, 24, 25):
            c.alignment = Alignment(wrap_text=True, vertical="top")
        elif j in (1, 7, 26):
            c.alignment = Alignment(horizontal="center")
        else:
            c.alignment = Alignment(vertical="top")
    tk = ws.cell(row=i, column=2)
    tk.hyperlink, tk.font = tv_url(r["t"]), Font(sz=9.5, b=True, color="FF1F4E78", u="single")
    gc = ws.cell(row=i, column=26)
    gc.fill, gc.font = GRADE_FILL[r["grade"]], Font(sz=9.5, b=True)
    ws.row_dimensions[i].height = 46
ws.freeze_panes = "C2"
ws.auto_filter.ref = f"A1:{get_column_letter(len(HDR))}{len(rows)+1}"

# ---------------------------------------------------------------- 一次性項目
ws = wb.create_sheet("一次性項目")
one = [r for r in rows if r["unusual"] and r["unusual_rev"]
       and (abs(r["unusual"]) >= 0.02 * r["unusual_rev"] or abs(r["unusual"]) >= 50)]
one.sort(key=lambda r: -abs(r["unusual"]))
ws["A1"] = "最新一季（Q0）帳上一次性 / 非經常項目 — 金額達營收 2% 或 5,000 萬以上者"
ws["A1"].font = TITLE_FONT
ws["A2"] = ("正數＝令帳面淨利「好看」的一次性收益（資產出售、和解收益、稅務優惠）；負數＝一次性支出（減值、重組、訴訟）。"
            "看到「轉正」頭條前，先看這一欄。金額為稅後（已扣 Tax Effect Of Unusual Items）。")
ws["A2"].font = Font(sz=9.5)
h2 = [("代號", 9), ("公司", 26), ("板塊", 14), ("Q0 期末", 11), ("一次性項目\n(稅後・百萬)", 14),
      ("佔營收 %", 10), ("Q0 淨利\n(百萬)", 12), ("Q0 營運利潤\n(百萬)", 13),
      ("剔一次性後淨利\n(百萬)", 15), ("方向", 24), ("級", 5)]
for j, (h, w) in enumerate(h2, 1):
    c = ws.cell(row=4, column=j, value=h)
    c.font, c.fill = HEAD_FONT, HEAD_FILL
    c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    ws.column_dimensions[get_column_letter(j)].width = w
ws.row_dimensions[4].height = 34
for i, r in enumerate(one, 5):
    q0 = r["q0"]
    ex = (q0["net"] - r["unusual"]) if q0 and q0["net"] is not None else None
    direction = ("帳面被一次性收益美化" if r["unusual"] > 0 else "帳面被一次性支出壓低")
    if ex is not None and q0["net"] is not None and (ex > 0) != (q0["net"] > 0):
        direction += "（剔除後盈虧號相反）"
    for j, v in enumerate([r["t"], r["name"], r["sector"], r["asof"], r["unusual"],
                           r["unusual"] / r["unusual_rev"] * 100, q0["net"] if q0 else None,
                           q0["op"] if q0 else None, ex, direction, r["grade"]], 1):
        c = ws.cell(row=i, column=j, value=v)
        c.font, c.border = BODY_FONT, MONO
        if j in (5, 7, 8, 9):
            c.number_format = "#,##0.0"
        elif j == 6:
            c.number_format = '#,##0.0"%"'
        elif j in (10,):
            c.alignment = Alignment(wrap_text=True)
    ws.cell(row=i, column=1).font = Font(sz=9.5, b=True)
ws.freeze_panes = "A5"

# ---------------------------------------------------------------- 軌跡排隊
ws = wb.create_sheet("軌跡排隊")
groups = {}
for r in rows:
    key = r["track"].split("：")[0]
    groups.setdefault(key, []).append(r["t"])
ws["A1"] = "按四季營運利潤（經常性口徑）方向分組 — 與帳面淨利分級的差異就是拆解的價值"
ws["A1"].font = TITLE_FONT
order2 = ["四季皆正", "由虧轉正", "反覆", "由正轉虧", "四季皆虧（收窄）", "四季皆虧（擴大）", "—"]
for j, (h, w) in enumerate([("軌跡", 18), ("數量", 7), ("代號", 150)], 1):
    c = ws.cell(row=3, column=j, value=h)
    c.font, c.fill = HEAD_FONT, HEAD_FILL
    c.alignment = Alignment(horizontal="center")
    ws.column_dimensions[get_column_letter(j)].width = w
row = 4
for k in order2:
    v = groups.get(k) or groups.get(k.replace("—", "—（缺營運利潤，見經常*註）"))
    if k == "—":
        v = [t for key, ts in groups.items() if key.startswith("—") for t in ts]
    if not v:
        continue
    ws.cell(row=row, column=1, value=k).font = Font(sz=9.5, b=True)
    ws.cell(row=row, column=2, value=len(v)).font = BODY_FONT
    c = ws.cell(row=row, column=3, value="、".join(sorted(v)))
    c.font, c.alignment = BODY_FONT, Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[row].height = 14 * max(1, len(v) // 22 + 1)
    row += 1

# ---------------------------------------------------------------- 分級彙總
ws = wb.create_sheet("分級彙總")
ws["A1"] = "分級彙總 — 機械判定（數量由 COUNTIF 連動「營收營利表」Z 欄）"
ws["A1"].font = TITLE_FONT
defs = {"A": "四季營運利潤皆正且最新季淨利為正（經常性已盈利）",
        "B": "最新季已盈利，但四季未全正或淨利與營運方向不一致",
        "C": "營運仍虧損，但較 Q-3 收窄",
        "D": "營運仍虧損且未見收窄",
        "—": "Yahoo 無足夠季度損益表數據"}
for j, (h, w) in enumerate([("級", 6), ("定義", 46), ("數量", 8), ("佔比", 8), ("Tickers", 120)], 1):
    c = ws.cell(row=3, column=j, value=h)
    c.font, c.fill = HEAD_FONT, HEAD_FILL
    c.alignment = Alignment(horizontal="center")
    ws.column_dimensions[get_column_letter(j)].width = w
for i, k in enumerate(["A", "B", "C", "D", "—"], 4):
    ts = [r["t"] for r in rows if r["grade"] == k]
    ws.cell(row=i, column=1, value=k).font = Font(sz=9.5, b=True)
    ws.cell(row=i, column=1).fill = GRADE_FILL[k]
    ws.cell(row=i, column=2, value=defs[k]).font = BODY_FONT
    ws.cell(row=i, column=3, value=f'=COUNTIF(營收營利表!Z:Z,"{k}")').font = BODY_FONT
    p = ws.cell(row=i, column=4, value=len(ts) / len(rows))
    p.font, p.number_format = BODY_FONT, "0.0%"
    c = ws.cell(row=i, column=5, value="、".join(sorted(ts)))
    c.font, c.alignment = BODY_FONT, Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[i].height = 14 * max(1, len(ts) // 18 + 1)
r0 = 10
ws.cell(row=r0, column=1, value="板塊 × 級別（隻數）").font = Font(b=True, sz=10)
secs = sorted({r["sector"] for r in rows})
for j, k in enumerate(["A", "B", "C", "D", "—"], 2):
    c = ws.cell(row=r0 + 1, column=j, value=k)
    c.font, c.fill, c.alignment = HEAD_FONT, HEAD_FILL, Alignment(horizontal="center")
ws.cell(row=r0 + 1, column=1, value="板塊").font = HEAD_FONT
ws.cell(row=r0 + 1, column=1).fill = HEAD_FILL
for i, s in enumerate(secs, r0 + 2):
    ws.cell(row=i, column=1, value=s or "（未分類）").font = BODY_FONT
    for j, k in enumerate(["A", "B", "C", "D", "—"], 2):
        n = sum(1 for r in rows if r["sector"] == s and r["grade"] == k)
        c = ws.cell(row=i, column=j, value=n or None)
        c.font, c.alignment = BODY_FONT, Alignment(horizontal="center")

# ---------------------------------------------------------------- 圖表連結
ws = wb.create_sheet("圖表連結")
ws["A1"] = f"{len(rows)} 隻 TradingView 圖表連結一覽 — 點 B 欄開圖（layout 沿用 Combined Watchlist）"
ws["A1"].font = TITLE_FONT
for j, (h, w) in enumerate([("#", 5), ("美股", 10), ("公司", 28), ("級", 5), ("純文字 URL", 62)], 1):
    c = ws.cell(row=3, column=j, value=h)
    c.font, c.fill, c.alignment = HEAD_FONT, HEAD_FILL, Alignment(horizontal="center")
    ws.column_dimensions[get_column_letter(j)].width = w
for i, r in enumerate(rows, 4):
    link = tv_url(r["t"])
    for j, v in enumerate([i - 3, r["t"], r["name"], r["grade"], link], 1):
        c = ws.cell(row=i, column=j, value=v)
        c.font = BODY_FONT
    b = ws.cell(row=i, column=2)
    b.hyperlink, b.font = link, Font(sz=9.5, b=True, color="FF1F4E78", u="single")
ws.freeze_panes = "A4"

stampf = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%m.%d_%H.%M")
out = f"Combined Watchlist R14 營收營利表_R0 (Opus5;high)_({stampf}).xlsx"
wb.save(out)
print(f"{out}: {len(rows)} tickers | grades",
      {k: sum(1 for r in rows if r["grade"] == k) for k in ("A", "B", "C", "D", "—")},
      f"| one-off rows {len(one)}")

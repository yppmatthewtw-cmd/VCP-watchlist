#!/usr/bin/env python3
"""Generate the Weinstein Stage watchlist (Markdown + CSV + HTML) from a stage scan JSON.

Same format family as the VCP watchlist: tier sections, TradingView links,
score bars, light/dark themes.

Usage: python make_stage.py scan_stage_R0_2026-08-22.json [--rev R0] [--model "..."]
"""

from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
from datetime import datetime, timedelta, timezone

from exchanges import EXCHANGE, tv_url

TIERS = {
    "2A_初升段": ("2A", "Stage 2A｜剛突破・初升段（首選）",
                  "剛脫離第一階段基底：站上 200 日（≈30 週）均線、距 52 週高點 ≤12%、近 6 個月啟動明顯升勢（+12% 以上）但 1 年漲幅未過度延伸（≤100%）— Weinstein 最佳買進區。"),
    "2B_主升段": ("2B", "Stage 2B｜主升段・已延伸",
                  "確立的第二階段升勢，但漲幅已大（1 年 >100%）或升勢年齡不明 — 可持有，新買點等回測 30 週線。"),
    "1轉2_轉強觀察": ("1→2", "Stage 1→2｜轉強觀察",
                     "自第一階段基底翻揚初期：已站回長期均線或動能轉正，但距高點仍有距離 — 等待放量突破基底上緣確認。"),
    "3_做頭疑慮": ("3", "Stage 3｜做頭疑慮（線下）",
                  "大漲後動能轉弱、距高點拉開 — 升勢可能進入尾聲，不宜新倉。"),
    "41_弱勢打底": ("4/1", "Stage 4／1｜下跌或打底（線下）",
                   "跌勢未止或仍在第一階段基底中，暫不列入。"),
}
ORDER = ["2A_初升段", "2B_主升段", "1轉2_轉強觀察", "3_做頭疑慮", "41_弱勢打底"]
ONLINE = {"2A_初升段", "2B_主升段", "1轉2_轉強觀察"}


def esc(s):
    return html_mod.escape(str(s), quote=True)


def fmt_pct(v):
    return "" if v is None else f"{v:+.1f}%"


def link_md(t):
    return f"[{t}]({tv_url(t)})"


def render_md(scan, rev, model, now_hkt, now_utc):
    rows = scan["rows"]
    notes = {n["ticker"]: n for n in scan.get("notes", [])}
    by = {c: [] for c in ORDER}
    for r in rows:
        by.setdefault(r["stage"], []).append(r)

    L = [
        f"# Weinstein Stage 2A Watchlist {rev}",
        "",
        f"**產生時間：** {now_hkt.strftime('%Y.%m.%d %H:%M')} HKT（{now_utc.strftime('%H:%M')} UTC）｜"
        f"**模型：** {model}｜**版本：** {rev}",
        "",
        f"**資料基準：** 美股 2026-08-21 收盤。依 Stan Weinstein 階段分析分級，重點在 **Stage 2A** — "
        "剛脫離第一階段基底、初入第二階段的年輕升勢。每檔代號連結 TradingView 圖，請以 30 週均線（週線圖）確認階段。",
        "",
        "> 本表為選股輔助工具，非投資建議。階段判定由量化代理規則產生，最終以週線圖 30 週均線形態確認。",
        "",
    ]
    if scan.get("market"):
        L += ["## 市場背景", "", scan["market"], ""]

    for cat in ORDER:
        cat_rows = sorted(by.get(cat, []), key=lambda r: -r.get("score", 0))
        if not cat_rows:
            continue
        tier, title, desc = TIERS[cat]
        L += [f"## {title}", "", desc, ""]
        if cat == "41_弱勢打底":
            L.append("、".join(f"{link_md(r['ticker'])}（距高 -{r['off_high_pct']:.0f}%）" for r in cat_rows))
            L.append("")
            continue
        L.append("| 代號 | 名稱 | 收盤 | 52W高 | 距高 | 6月 | 1年 | 高於200日線 | 分數 | 備註 |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in cat_rows:
            t = r["ticker"]
            note = notes.get(t, {}).get("note", "")
            ma = "✓" if r.get("above_ma200") else ("✗" if r.get("above_ma200") is False else "–")
            L.append(
                f"| {link_md(t)} | {esc((r.get('name') or '')[:22])} | {r['price']:,.2f} | {r['year_high']:,.2f} "
                f"| -{r['off_high_pct']:.1f}% | {fmt_pct(r.get('chg_6m'))} | {fmt_pct(r.get('chg_1y'))} "
                f"| {ma} | {r.get('score', '')} | {esc(note)} |")
        L.append("")

    online = sum(len(by.get(c, [])) for c in ONLINE)
    L += [
        f"**線上（2A + 2B + 1→2）合計 {online} 檔；全宇宙 {len(rows)} 檔。**",
        "",
        "## 階段判定方法",
        "",
        "1. **長期趨勢**：股價高於 200 日（≈30 週）均線（74 檔原 AI 宇宙用實際均線；其餘以搜尋所得的 200 日線位置或 52 週區間位置代理）。",
        "2. **升勢年齡**：6 個月漲幅 ≥12% 視為升勢已啟動；1 年漲幅 ≤100% 視為未過度延伸 → 兩者兼備即為「年輕升勢」（2A 的核心）。",
        "3. **距高點**：≤12% 為 2A／2B 區；12–35% 且動能轉正為 1→2 轉強觀察。",
        "4. **做頭警示**：大漲後（1 年 >100%）距高拉開且 3 個月動能轉負 → Stage 3 疑慮。",
        "5. Weinstein 原法以「30 週均線走平轉揚＋放量突破」認定 2A — 量能與週線形態請開圖確認。",
        "",
        "**分數**（0–100）：長期趨勢 25 ＋ 升勢年齡 25 ＋ 未延伸 15 ＋ 距高點 20 ＋ 52 週位置 5 ＋ 200 日線距離甜蜜區 10。",
        "",
        "_資料來源：網路搜尋報價（8/21 收盤）；圖表連結：TradingView。非投資建議。_",
        "",
    ]
    return "\n".join(L)


def render_html(scan, rev, model, now_hkt):
    rows = scan["rows"]
    notes = {n["ticker"]: n for n in scan.get("notes", [])}
    by = {c: [] for c in ORDER}
    for r in rows:
        by.setdefault(r["stage"], []).append(r)
    counts = {c: len(by.get(c, [])) for c in ORDER}
    online = sum(counts[c] for c in ONLINE)

    def row_html(r):
        t = r["ticker"]
        note = esc(notes.get(t, {}).get("note", ""))
        ex = EXCHANGE.get(t, "").upper()
        ma = r.get("above_ma200")
        ma_td = ('<td class="num up">✓</td>' if ma else
                 '<td class="num dn">✗</td>' if ma is False else '<td class="num">–</td>')
        c6, c1y = r.get("chg_6m"), r.get("chg_1y")
        def pct_td(v):
            if v is None:
                return '<td class="num">–</td>'
            cls = "up" if v > 0 else "dn" if v < 0 else ""
            return f'<td class="num {cls}">{v:+.1f}%</td>'
        score = r.get("score", 0)
        return (f'<tr><td class="tk"><a href="{tv_url(t)}" target="_blank" rel="noopener">{t}'
                f'<small>{ex}</small></a></td>'
                f'<td class="nm">{esc((r.get("name") or "")[:26])}</td>'
                f'<td class="num">{r["price"]:,.2f}</td>'
                f'<td class="num">{r["year_high"]:,.2f}</td>'
                f'<td class="num pivot">-{r["off_high_pct"]:.1f}%</td>'
                f'{pct_td(c6)}{pct_td(c1y)}{ma_td}'
                f'<td class="num"><span class="scorebar"><i style="width:{min(score, 100):.0f}%"></i>'
                f'<b>{score:g}</b></span></td>'
                f'<td class="note">{note}</td></tr>')

    sections = []
    for cat in ORDER:
        cat_rows = sorted(by.get(cat, []), key=lambda r: -r.get("score", 0))
        if not cat_rows:
            continue
        tier, title, desc = TIERS[cat]
        tid = tier.replace("/", "").replace("→", "")
        if cat == "41_弱勢打底":
            chips = "".join(
                f'<a class="dchip" href="{tv_url(r["ticker"])}" target="_blank" rel="noopener">'
                f'{r["ticker"]}<small>−{r["off_high_pct"]:.0f}%</small></a>'
                for r in sorted(cat_rows, key=lambda r: r["off_high_pct"]))
            body = f'<div class="dwrap">{chips}</div>'
        else:
            trs = "\n".join(row_html(r) for r in cat_rows)
            body = (f'<div class="tblwrap"><table><thead><tr><th>代號</th><th>名稱</th>'
                    '<th class="num">收盤</th><th class="num">52W高</th><th class="num">距高</th>'
                    '<th class="num">6月</th><th class="num">1年</th><th class="num">200日線上</th>'
                    f'<th class="num">分數</th><th>備註</th></tr></thead><tbody>{trs}</tbody></table></div>')
        sections.append(
            f'<section class="tier tier-{tid.lower()}" id="tier-{tid.lower()}">'
            f'<header class="tier-head"><span class="badge b-{tid.lower()}">{tier}</span>'
            f'<div><h2>{esc(title)}</h2><p>{esc(desc)}</p></div>'
            f'<span class="count">{len(cat_rows)} 檔</span></header>{body}</section>')

    return f"""<title>Weinstein Stage 2A Watchlist {rev}</title>
<style>
:root {{
  --bg: #F6F5F2; --panel: #FFFFFF; --ink: #21262B; --muted: #626C76; --line: #DFDDD6;
  --accent: #1F7A63; --accent-soft: #DFEEE8;
  --up: #1F7A63; --dn: #BE4A38;
  --head: #EEECE6; --hover: #F1F0EA;
  --t2a: #1F7A63; --t2b: #2C6E9E; --t12: #B07B24; --t3: #A05A2C; --t41: #8B95A0;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #10151A; --panel: #171E25; --ink: #E3E8EC; --muted: #8B98A5; --line: #28323C;
    --accent: #4CC2A2; --accent-soft: #17362E;
    --up: #4CC2A2; --dn: #E0705F;
    --head: #1C252E; --hover: #1E2832;
    --t2a: #4CC2A2; --t2b: #5CA3D6; --t12: #E5B15C; --t3: #D08A5A; --t41: #5D6B7A;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #10151A; --panel: #171E25; --ink: #E3E8EC; --muted: #8B98A5; --line: #28323C;
  --accent: #4CC2A2; --accent-soft: #17362E;
  --up: #4CC2A2; --dn: #E0705F;
  --head: #1C252E; --hover: #1E2832;
  --t2a: #4CC2A2; --t2b: #5CA3D6; --t12: #E5B15C; --t3: #D08A5A; --t41: #5D6B7A;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 "Avenir Next", "Segoe UI", "PingFang TC", "Microsoft JhengHei", system-ui, sans-serif; }}
.wrap {{ max-width: 1200px; margin: 0 auto; padding: 28px 20px 60px; }}
.masthead {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px 18px;
  border-bottom: 3px solid var(--ink); padding-bottom: 14px; }}
.masthead h1 {{ font-size: 28px; margin: 0; letter-spacing: -0.01em; text-wrap: balance; }}
.masthead h1 em {{ font-style: normal; color: var(--accent); }}
.meta {{ color: var(--muted); font-size: 13px; }}
.meta b {{ color: var(--ink); font-weight: 600; }}
.summary {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 18px 0 6px; }}
.summary a {{ text-decoration: none; color: inherit; }}
.stat {{ display: flex; align-items: center; gap: 9px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 6px; padding: 8px 14px; }}
.stat .dot {{ width: 10px; height: 10px; border-radius: 2px; }}
.stat b {{ font-size: 20px; font-variant-numeric: tabular-nums; }}
.stat span {{ color: var(--muted); font-size: 12.5px; }}
.market {{ background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--accent);
  border-radius: 6px; padding: 14px 18px; margin: 16px 0 4px; font-size: 14px; color: var(--muted); }}
.market strong {{ color: var(--ink); }}
.tier {{ margin-top: 34px; }}
.tier-head {{ display: flex; align-items: flex-start; gap: 14px; margin-bottom: 10px; }}
.tier-head h2 {{ margin: 0; font-size: 19px; }}
.tier-head p {{ margin: 2px 0 0; color: var(--muted); font-size: 13.5px; max-width: 70ch; }}
.tier-head .count {{ margin-left: auto; color: var(--muted); font-size: 13px; white-space: nowrap; padding-top: 4px; }}
.badge {{ flex: none; min-width: 34px; height: 34px; border-radius: 6px; display: grid; place-items: center;
  font-weight: 700; font-size: 14px; color: var(--bg); padding: 0 6px; }}
.b-2a {{ background: var(--t2a); }} .b-2b {{ background: var(--t2b); }}
.b-12 {{ background: var(--t12); }} .b-3 {{ background: var(--t3); }} .b-41 {{ background: var(--t41); }}
.tblwrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }}
table {{ border-collapse: collapse; width: 100%; min-width: 900px; font-size: 13.5px; }}
th {{ background: var(--head); text-align: left; padding: 8px 10px; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); white-space: nowrap; }}
td {{ padding: 8px 10px; border-top: 1px solid var(--line); vertical-align: top; }}
tbody tr:hover {{ background: var(--hover); }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums;
  font-family: "SF Mono", "Cascadia Mono", Consolas, ui-monospace, monospace; font-size: 12.5px; white-space: nowrap; }}
td.tk {{ white-space: nowrap; }}
td.tk a {{ display: inline-block; font-weight: 700; color: var(--accent); text-decoration: none;
  border-bottom: 1px solid transparent; }}
td.tk a small {{ display: block; font-size: 9.5px; font-weight: 600; letter-spacing: 0.06em; color: var(--muted); }}
td.tk a:hover, td.tk a:focus-visible {{ border-bottom-color: var(--accent); outline: none; }}
td.nm {{ color: var(--muted); font-size: 12.5px; white-space: nowrap; }}
td.up {{ color: var(--up); }} td.dn {{ color: var(--dn); }}
td.pivot {{ color: var(--t12); font-weight: 600; }}
td.note {{ min-width: 200px; max-width: 380px; color: var(--muted); font-size: 12.5px; line-height: 1.45; white-space: normal; }}
.scorebar {{ display: inline-flex; align-items: center; gap: 7px; min-width: 92px; }}
.scorebar i {{ display: block; height: 5px; border-radius: 3px; background: var(--accent); min-width: 3px; max-width: 60px; flex: none; }}
.scorebar b {{ font-size: 12.5px; }}
.dwrap {{ display: flex; flex-wrap: wrap; gap: 7px; }}
.dchip {{ display: inline-flex; gap: 6px; align-items: baseline; background: var(--panel);
  border: 1px solid var(--line); border-radius: 5px; padding: 4px 10px; text-decoration: none;
  color: var(--muted); font-size: 12.5px; font-weight: 600; }}
.dchip small {{ color: var(--dn); font-weight: 400; font-variant-numeric: tabular-nums; }}
.dchip:hover, .dchip:focus-visible {{ border-color: var(--accent); color: var(--ink); outline: none; }}
.method {{ margin-top: 40px; border-top: 1px solid var(--line); padding-top: 18px;
  color: var(--muted); font-size: 13.5px; max-width: 78ch; }}
.method h3 {{ color: var(--ink); font-size: 15px; margin: 0 0 8px; }}
.method ol {{ padding-left: 20px; margin: 8px 0; }}
.method li {{ margin: 4px 0; }}
.disclaimer {{ margin-top: 14px; font-size: 12.5px; color: var(--muted);
  border-left: 3px solid var(--dn); padding-left: 12px; }}
a {{ color: var(--accent); }}
@media (max-width: 640px) {{ .masthead h1 {{ font-size: 23px; }} .tier-head .count {{ display: none; }} }}
</style>
<div class="wrap">
<header class="masthead">
  <h1>Weinstein Stage 2A Watchlist <em>{rev}</em></h1>
  <span class="meta"><b>美股全市場 · {len(rows)} 檔</b> ｜ 數據基準 2026-08-21 收盤 ｜ 產生
  {now_hkt.strftime('%Y.%m.%d %H:%M')} HKT ｜ {esc(model)}</span>
</header>
<nav class="summary">
  <a href="#tier-2a"><span class="stat"><span class="dot" style="background:var(--t2a)"></span><b>{counts['2A_初升段']}</b><span>2A・剛突破初升段</span></span></a>
  <a href="#tier-2b"><span class="stat"><span class="dot" style="background:var(--t2b)"></span><b>{counts['2B_主升段']}</b><span>2B・主升段延伸</span></span></a>
  <a href="#tier-12"><span class="stat"><span class="dot" style="background:var(--t12)"></span><b>{counts['1轉2_轉強觀察']}</b><span>1→2・轉強觀察</span></span></a>
  <a href="#tier-3"><span class="stat"><span class="dot" style="background:var(--t3)"></span><b>{counts['3_做頭疑慮']}</b><span>3・做頭疑慮</span></span></a>
  <a href="#tier-41"><span class="stat"><span class="dot" style="background:var(--t41)"></span><b>{counts['41_弱勢打底']}</b><span>4/1・弱勢打底</span></span></a>
</nav>
<p class="market"><strong>市場背景</strong> — {esc(scan.get('market', ''))}</p>
{''.join(sections)}
<footer class="method">
<h3>階段判定方法（Weinstein 階段分析）</h3>
<ol>
<li><b>長期趨勢</b>：股價高於 200 日（≈30 週）均線 — 74 檔原宇宙用實際均線，其餘以搜尋所得 200 日線位置或 52 週區間位置代理。</li>
<li><b>升勢年齡</b>：6 個月 ≥+12% 視為升勢啟動；1 年 ≤+100% 視為未過度延伸 → 兩者兼備＝年輕升勢（2A 核心）。</li>
<li><b>距高點</b>：≤12% 為 2A／2B；12–35% 且動能轉正為 1→2。</li>
<li><b>做頭警示</b>：1 年 &gt;100% 大漲後距高拉開且動能轉負 → Stage 3。</li>
<li>Weinstein 原法要求「30 週均線走平轉揚＋<b>放量</b>突破」— 量能與週線形態請點代號開 TradingView 圖確認（週線 + 30 週 SMA）。</li>
</ol>
<p><b>分數</b>（0–100）：長期趨勢 25 ＋ 升勢年齡 25 ＋ 未延伸 15 ＋ 距高點 20 ＋ 52 週位置 5 ＋ 200 日線距離甜蜜區 10。</p>
<p>線上（2A＋2B＋1→2）合計 <b>{online}</b> 檔。資料：網路搜尋報價（8/21 收盤）；圖表：TradingView。</p>
<p class="disclaimer">本表為技術面選股輔助工具，非投資建議。階段由量化代理規則判定，最終以週線圖 30 週均線形態與量能確認。</p>
</footer>
</div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_json")
    ap.add_argument("--rev", default="R0")
    ap.add_argument("--model", default="Fable5;ultracode")
    args = ap.parse_args()

    scan = json.load(open(args.scan_json))
    now_utc = datetime.now(timezone.utc)
    now_hkt = now_utc + timedelta(hours=8)
    stamp = now_hkt.strftime("%m.%d_%H.%M")
    base = f"Weinstein Stage2A watchlist (Github)_{args.rev} ({args.model})_({stamp})"

    open(f"{base}.md", "w").write(render_md(scan, args.rev, args.model, now_hkt, now_utc))
    open(f"{base}.html", "w").write(render_html(scan, args.rev, args.model, now_hkt))

    rows = scan["rows"]
    cols = ["ticker", "name", "stage", "score", "price", "year_high", "year_low",
            "off_high_pct", "above_low_pct", "chg_6m", "chg_1y", "above_ma200", "as_of"]
    with open(f"{base}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda r: -r.get("score", 0)):
            w.writerow(r)

    print(f"{base}.md")
    print(f"{base}.csv")
    print(f"{base}.html")


if __name__ == "__main__":
    main()

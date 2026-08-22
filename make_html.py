#!/usr/bin/env python3
"""Generate a self-contained HTML version of the VCP watchlist from scan JSON.

Usage: python make_html.py scan_R0_2026-08-15.json [--rev R0] [--model "Fable5;ultracode"] [--out FILE]
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timedelta, timezone

from exchanges import EXCHANGE, missing, tv_url

TIERS = {
    "A_VCP待突破": ("A", "VCP 緊縮・等待突破",
                    "趨勢模板通過、距 52 週高點 ≤10%、近 1 個月波動收斂 ±7% 內 — 最接近 Minervini VCP 買點。"),
    "E_突破延伸中": ("E", "已突破・延伸中",
                    "貼著 52 週新高且近 1 個月大漲 — 突破已發動，勿追高，等回測樞紐區或新的緊縮。"),
    "B_上升結構": ("B", "上升結構（一底高於一底 / 上升三角形候選）",
                  "站上 50/200 日線、距高點 ≤20%、3 個月動能為正 — 開圖確認低點墊高與上緣壓力線。"),
    "C_基底修復中": ("C", "基底修復中（觀察）",
                    "仍在 200 日線上方但距高點較深，基底右側尚未完成。"),
    "D_趨勢弱": ("D", "趨勢偏弱（暫不列入)",
               "跌破主要均線或距高點過深，暫不符合進場條件。"),
}
ORDER = ["A_VCP待突破", "E_突破延伸中", "B_上升結構", "C_基底修復中", "D_趨勢弱"]


def esc(s):  # noqa: D103
    return html.escape(str(s), quote=True)


def pct(v, arrow=False):
    if v is None:
        return "<td></td>"
    cls = "up" if v > 0 else "dn" if v < 0 else "flat"
    return f'<td class="num {cls}">{v:+.1f}%</td>'


def row_html(r, notes):
    t = r["ticker"]
    price = r.get("price") or 0
    pivot = r.get("year_high") or 0
    to_pivot = (pivot - price) / price * 100 if price else 0
    score = r.get("score", 0)
    n = notes.get(t, {})
    note = esc(n.get("note", ""))
    ed = n.get("earnings_date", "")
    ed_chip = f'<span class="chip chip-cal">財報 {esc(ed[5:].replace("-", "/"))}</span>' if ed else ""
    vol = r.get("vol_ratio")
    vol_cls = "dry" if isinstance(vol, (int, float)) and vol < 0.7 else ""
    ex = EXCHANGE.get(t, "").upper()
    return f"""<tr>
<td class="tk"><a href="{tv_url(t)}" target="_blank" rel="noopener">{t}<small>{ex}</small></a></td>
<td class="nm">{esc((r.get('name') or '')[:30])}</td>
<td class="num">{price:,.2f}</td>
<td class="num">{pivot:,.2f}</td>
<td class="num pivot">+{to_pivot:.1f}%</td>
{pct(r.get('chg_1m'))}
{pct(r.get('chg_3m'))}
{pct(r.get('chg_6m'))}
{pct(r.get('chg_1y'))}
<td class="num {vol_cls}">{vol if vol is not None else ''}</td>
<td class="num"><span class="scorebar"><i style="width:{min(score,100):.0f}%"></i><b>{score:g}</b></span></td>
<td class="note">{note} {ed_chip}</td>
</tr>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_json")
    ap.add_argument("--rev", default="R0")
    ap.add_argument("--model", default="Fable5;ultracode")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    scan = json.load(open(args.scan_json))
    rows = scan.get("rows", [])
    notes = {n["ticker"]: n for n in scan.get("notes", [])}

    unmapped = missing(r["ticker"] for r in rows)
    if unmapped:
        print(f"WARNING: no exchange mapping for {', '.join(unmapped)} "
              "— links fall back to bare symbol")
    now_utc = datetime.now(timezone.utc)
    now_hkt = now_utc + timedelta(hours=8)
    stamp = now_hkt.strftime("%m.%d_%H.%M")
    out = args.out or f"VCP watchlist (Github)_{args.rev} ({args.model})_({stamp}).html"
    data_date = rows[0].get("as_of", "")[:10] if rows else ""

    by = {c: [] for c in ORDER}
    for r in rows:
        by.setdefault(r.get("category", "D_趨勢弱"), []).append(r)
    counts = {c: len(by.get(c, [])) for c in ORDER}

    sections = []
    for cat in ORDER:
        tier, title, desc = TIERS[cat]
        cat_rows = sorted(by.get(cat, []), key=lambda r: -r.get("score", 0))
        if not cat_rows:
            continue
        if cat == "D_趨勢弱":
            chips = "".join(
                f'<a class="dchip" href="{tv_url(r["ticker"])}" target="_blank" '
                f'rel="noopener">{r["ticker"]}<small>−{r["off_high_pct"]:.0f}%</small></a>'
                for r in sorted(cat_rows, key=lambda r: r["off_high_pct"]))
            body = f'<div class="dwrap">{chips}</div>'
        else:
            trs = "\n".join(row_html(r, notes) for r in cat_rows)
            body = f"""<div class="tblwrap"><table>
<thead><tr><th>代號</th><th>名稱</th><th class="num">收盤</th><th class="num">樞紐<small>52W高</small></th>
<th class="num">距樞紐</th><th class="num">1月</th><th class="num">3月</th><th class="num">6月</th>
<th class="num">1年</th><th class="num">量比</th><th class="num">分數</th><th>備註</th></tr></thead>
<tbody>{trs}</tbody></table></div>"""
        sections.append(f"""<section class="tier tier-{tier.lower()}" id="tier-{tier.lower()}">
<header class="tier-head"><span class="badge">{tier}</span>
<div><h2>{esc(title)}</h2><p>{esc(desc)}</p></div>
<span class="count">{len(cat_rows)} 檔</span></header>
{body}</section>""")

    doc = f"""<title>VCP Watchlist {args.rev}</title>
<style>
:root {{
  --bg: #F5F6F4; --panel: #FFFFFF; --ink: #1B2430; --muted: #5D6B7A; --line: #DDE2E0;
  --accent: #B07B24; --accent-soft: #F3E8D3;
  --up: #17835C; --dn: #C24A3F; --dry: #B07B24;
  --head: #EDEFEA; --hover: #F0F3EE;
  --tier-a: #17835C; --tier-e: #B07B24; --tier-b: #2C6E9E; --tier-c: #5D6B7A; --tier-d: #8B95A0;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #0E1216; --panel: #151B21; --ink: #E4E9EC; --muted: #8B98A5; --line: #26303A;
    --accent: #E5B15C; --accent-soft: #2A2418;
    --up: #3FB68B; --dn: #E0705F; --dry: #E5B15C;
    --head: #1A222A; --hover: #1C242D;
    --tier-a: #3FB68B; --tier-e: #E5B15C; --tier-b: #5CA3D6; --tier-c: #8B98A5; --tier-d: #5D6B7A;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #0E1216; --panel: #151B21; --ink: #E4E9EC; --muted: #8B98A5; --line: #26303A;
  --accent: #E5B15C; --accent-soft: #2A2418;
  --up: #3FB68B; --dn: #E0705F; --dry: #E5B15C;
  --head: #1A222A; --hover: #1C242D;
  --tier-a: #3FB68B; --tier-e: #E5B15C; --tier-b: #5CA3D6; --tier-c: #8B98A5; --tier-d: #5D6B7A;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 "Avenir Next", "Segoe UI", "PingFang TC", "Microsoft JhengHei", system-ui, sans-serif;
}}
.wrap {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 60px; }}
.masthead {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px 18px; border-bottom: 3px solid var(--ink); padding-bottom: 14px; }}
.masthead h1 {{ font-size: 30px; margin: 0; letter-spacing: -0.01em; text-wrap: balance; }}
.masthead h1 em {{ font-style: normal; color: var(--accent); }}
.meta {{ color: var(--muted); font-size: 13px; }}
.meta b {{ color: var(--ink); font-weight: 600; }}
.summary {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 18px 0 6px; }}
.summary a {{ text-decoration: none; color: inherit; }}
.stat {{ display: flex; align-items: center; gap: 9px; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 8px 14px; }}
.stat .dot {{ width: 10px; height: 10px; border-radius: 2px; }}
.stat b {{ font-size: 20px; font-variant-numeric: tabular-nums; }}
.stat span {{ color: var(--muted); font-size: 12.5px; }}
.market {{ background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 6px; padding: 14px 18px; margin: 16px 0 4px; font-size: 14px; color: var(--muted); }}
.market strong {{ color: var(--ink); }}
.tier {{ margin-top: 34px; }}
.tier-head {{ display: flex; align-items: flex-start; gap: 14px; margin-bottom: 10px; }}
.tier-head h2 {{ margin: 0; font-size: 19px; }}
.tier-head p {{ margin: 2px 0 0; color: var(--muted); font-size: 13.5px; max-width: 68ch; }}
.tier-head .count {{ margin-left: auto; color: var(--muted); font-size: 13px; white-space: nowrap; padding-top: 4px; }}
.badge {{ flex: none; width: 34px; height: 34px; border-radius: 6px; display: grid; place-items: center; font-weight: 700; font-size: 17px; color: var(--bg); }}
.tier-a .badge {{ background: var(--tier-a); }} .tier-e .badge {{ background: var(--tier-e); }}
.tier-b .badge {{ background: var(--tier-b); }} .tier-c .badge {{ background: var(--tier-c); }}
.tier-d .badge {{ background: var(--tier-d); }}
.tblwrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }}
table {{ border-collapse: collapse; width: 100%; min-width: 980px; font-size: 13.5px; }}
th {{ background: var(--head); text-align: left; padding: 8px 10px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); white-space: nowrap; }}
th small {{ display: block; font-size: 10px; letter-spacing: 0; text-transform: none; }}
td {{ padding: 8px 10px; border-top: 1px solid var(--line); vertical-align: top; }}
tbody tr:hover {{ background: var(--hover); }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; font-family: "SF Mono", "Cascadia Mono", Consolas, ui-monospace, monospace; font-size: 12.5px; white-space: nowrap; }}
td.tk {{ white-space: nowrap; }}
td.tk a {{ display: inline-block; font-weight: 700; color: var(--accent); text-decoration: none; border-bottom: 1px solid transparent; }}
td.tk a small {{ display: block; font-size: 9.5px; font-weight: 600; letter-spacing: 0.06em; color: var(--muted); border: 0; }}
td.tk a:hover, td.tk a:focus-visible {{ border-bottom-color: var(--accent); outline: none; }}
td.nm {{ color: var(--muted); font-size: 12.5px; white-space: nowrap; }}
td.up {{ color: var(--up); }} td.dn {{ color: var(--dn); }} td.flat {{ color: var(--muted); }}
td.pivot {{ color: var(--accent); font-weight: 600; }}
td.dry {{ color: var(--dry); font-weight: 600; }}
td.note {{ min-width: 260px; max-width: 420px; color: var(--muted); font-size: 12.5px; line-height: 1.45; }}
.chip-cal {{ display: inline-block; background: var(--accent-soft); color: var(--accent); border-radius: 4px; padding: 1px 7px; font-size: 11.5px; font-weight: 600; white-space: nowrap; }}
.scorebar {{ display: inline-flex; align-items: center; gap: 7px; min-width: 92px; }}
.scorebar i {{ display: block; height: 5px; border-radius: 3px; background: var(--accent); min-width: 3px; max-width: 60px; flex: none; }}
.scorebar b {{ font-size: 12.5px; }}
.dwrap {{ display: flex; flex-wrap: wrap; gap: 7px; }}
.dchip {{ display: inline-flex; gap: 6px; align-items: baseline; background: var(--panel); border: 1px solid var(--line); border-radius: 5px; padding: 4px 10px; text-decoration: none; color: var(--muted); font-size: 12.5px; font-weight: 600; }}
.dchip small {{ color: var(--dn); font-weight: 400; font-variant-numeric: tabular-nums; }}
.dchip:hover, .dchip:focus-visible {{ border-color: var(--accent); color: var(--ink); outline: none; }}
.method {{ margin-top: 40px; border-top: 1px solid var(--line); padding-top: 18px; color: var(--muted); font-size: 13.5px; max-width: 78ch; }}
.method h3 {{ color: var(--ink); font-size: 15px; margin: 0 0 8px; }}
.method ol {{ padding-left: 20px; margin: 8px 0; }}
.method li {{ margin: 4px 0; }}
.disclaimer {{ margin-top: 14px; font-size: 12.5px; color: var(--muted); border-left: 3px solid var(--dn); padding-left: 12px; }}
a {{ color: var(--accent); }}
@media (max-width: 640px) {{ .masthead h1 {{ font-size: 24px; }} .tier-head .count {{ display: none; }} }}
</style>
<div class="wrap">
<header class="masthead">
  <h1>VCP Watchlist <em>{args.rev}</em></h1>
  <span class="meta"><b>美股全市場 · {len(rows)} 檔</b> ｜ 數據基準 {data_date} 收盤 ｜ 產生 {now_hkt.strftime('%Y.%m.%d %H:%M')} HKT ｜ {esc(args.model)}</span>
</header>
<nav class="summary">
  <a href="#tier-a"><span class="stat"><span class="dot" style="background:var(--tier-a)"></span><b>{counts['A_VCP待突破']}</b><span>A・VCP 待突破</span></span></a>
  <a href="#tier-e"><span class="stat"><span class="dot" style="background:var(--tier-e)"></span><b>{counts['E_突破延伸中']}</b><span>E・突破延伸中</span></span></a>
  <a href="#tier-b"><span class="stat"><span class="dot" style="background:var(--tier-b)"></span><b>{counts['B_上升結構']}</b><span>B・上升結構</span></span></a>
  <a href="#tier-c"><span class="stat"><span class="dot" style="background:var(--tier-c)"></span><b>{counts['C_基底修復中']}</b><span>C・基底修復</span></span></a>
  <a href="#tier-d"><span class="stat"><span class="dot" style="background:var(--tier-d)"></span><b>{counts['D_趨勢弱']}</b><span>D・趨勢弱</span></span></a>
</nav>
<p class="market"><strong>市場背景</strong> — {esc(scan.get('market', ''))}</p>
{''.join(sections)}
<footer class="method">
<h3>篩選方法</h3>
<ol>
<li><b>趨勢模板</b>：站上 50/200 日均線、50MA &gt; 200MA、高於 52 週低點 ≥30%、距 52 週高點 ≤25%。</li>
<li><b>緊縮度</b>：近 1 個月漲跌幅收斂 ±7% 內且貼近高點 → 基底右側收緊（VCP 特徵）。</li>
<li><b>量能</b>：現量低於 50 日均量（量比 &lt; 1）→ 突破前典型量縮，表中金色標示 &lt; 0.7。</li>
<li><b>動能</b>：6 個月 / 1 年漲幅確認主升趨勢仍在。</li>
<li>「一底高於一底」「上升三角形」為結構推斷 — 點代號開 TradingView 圖確認低點墊高與上緣壓力線。</li>
</ol>
<p><b>分數</b>（0–100）：均線結構 30 ＋ 距樞紐 15 ＋ 月線緊縮 15 ＋ 中長期動能 20 ＋ 量縮 10 ＋ 貼緊樞紐加成 5。</p>
<p>資料來源：<a href="https://bigdata.com" target="_blank" rel="noopener">Bigdata.com</a> 報價與價格統計；新聞驗證：網路搜尋。TSM 已換算為 ADR 價格。圖表連結：TradingView（<code>?symbol=交易所:代號</code>，代號下方標示 NASDAQ / NYSE）。</p>
<p class="disclaimer">本表為技術面選股輔助工具，非投資建議。財報日前後（NVDA/CRWD 8/26、PANW 8/17、MDB 9/1）波動風險高，形態最終以圖表確認為準。</p>
</footer>
</div>"""

    with open(out, "w") as f:
        f.write(doc)
    print(out)


if __name__ == "__main__":
    main()

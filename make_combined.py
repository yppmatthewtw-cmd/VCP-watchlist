#!/usr/bin/env python3
"""Generate the combined VCP watchlist: tier tables with per-update trajectory built in.

Merges what used to be two documents — the tier watchlist (make_html.py) and the
tier-trajectory history (make_history.py) — into one file. Each row carries its
tier path across every snapshot, and tickers that fell off the watchlist get
their own "below the line" section instead of being buried in C/D.

Reads the latest scan_R*.json as the current state and all snapshots for history.
It creates no new snapshot — this is a presentation revision of existing data.

Usage: python make_combined.py [--rev R7] [--model "Opus5;high"] [--updates 10]
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import html as html_mod
import json
import re
from datetime import datetime, timedelta, timezone

from exchanges import EXCHANGE, tv_url

TIERS = {
    "A_VCP待突破": ("A", "VCP 緊縮・等待突破",
                    "趨勢模板通過、距 52 週高點 ≤10%、近 1 個月波動收斂 ±7% 內 — 最接近 Minervini VCP 買點。"),
    "E_突破延伸中": ("E", "已突破・延伸中",
                    "貼著 52 週新高且近 1 個月大漲 — 突破已發動，勿追高，等回測樞紐區或新的緊縮。"),
    "B_上升結構": ("B", "上升結構（一底高於一底 / 上升三角形候選）",
                  "站上 50/200 日線、距高點 ≤20%、3 個月動能為正 — 開圖確認低點墊高與上緣壓力線。"),
    "C_基底修復中": ("C", "基底修復中（觀察）",
                    "仍在 200 日線上方但距高點較深，基底右側尚未完成。"),
    "D_趨勢弱": ("D", "趨勢偏弱（暫不列入）",
               "跌破主要均線或距高點過深，暫不符合進場條件。"),
}
ORDER = ["A_VCP待突破", "E_突破延伸中", "B_上升結構", "C_基底修復中", "D_趨勢弱"]
LETTER_OF = {k: v[0] for k, v in TIERS.items()}
RANK_OF = {"A": 0, "E": 1, "B": 2, "C": 3, "D": 4}
ABOVE = {"A", "E", "B"}


def esc(s):
    return html_mod.escape(str(s), quote=True)


def load_snapshots(limit):
    snaps = []
    for path in glob.glob("scan_R*.json"):
        m = re.match(r"scan_(R\d+)_", path)
        if not m:
            continue
        scan = json.load(open(path))
        rows = scan.get("rows", [])
        if not rows:
            continue
        dates = collections.Counter((r.get("as_of") or "")[:10] for r in rows)
        snaps.append((m.group(1), dates.most_common(1)[0][0],
                      {r["ticker"]: r for r in rows}, scan))
    snaps.sort(key=lambda s: (s[1], int(s[0][1:])))
    return snaps[-limit:]


def build_tracks(snaps):
    tickers = sorted({t for _, _, rows, _ in snaps for t in rows})
    out = {}
    for t in tickers:
        letters, scores, seen_rows = [], [], []
        for _, _, rows, _ in snaps:
            r = rows.get(t)
            letters.append(LETTER_OF.get(r["category"]) if r else None)
            scores.append(r.get("score") if r else None)
            seen_rows.append(r)
        present = [l for l in letters if l]
        out[t] = {
            "letters": letters, "scores": scores,
            "row": next((r for r in reversed(seen_rows) if r), None),
            "now": letters[-1],
            "ever_above": any(l in ABOVE for l in present),
            "first_idx": next((i for i, l in enumerate(letters) if l), 0),
        }
    return out


def move_of(info):
    seq = [l for l in info["letters"] if l]
    if len(seq) < 2:
        return 0
    return RANK_OF[seq[-2]] - RANK_OF[seq[-1]]


def arrow_txt(mv):
    return "▲" if mv > 0 else ("▼" if mv < 0 else "＝")


# --------------------------------------------------------------------------- MD
def render_md(snaps, tracks, scan, rev, model, now_hkt, now_utc):
    rows = scan["rows"]
    notes = {n["ticker"]: n for n in scan.get("notes", [])}
    n_snap = len(snaps)
    heads = " | ".join(f"{r}<br><small>{d[5:].replace('-', '/')}</small>" for r, d, _, _ in snaps)

    groups = collections.defaultdict(list)
    dropped = []
    for r in rows:
        t = r["ticker"]
        info = tracks.get(t)
        letter = LETTER_OF[r["category"]]
        if letter in ABOVE:
            groups[r["category"]].append(r)
        elif info and info["ever_above"]:
            dropped.append(r)
        else:
            groups[r["category"]].append(r)

    def table(items):
        out = [f"| 代號 | 名稱 | {heads} | 變化 | 收盤 | 距樞紐 | 1月 | 3月 | 分數 | 備註 |",
               "|---|---|" + "---|" * n_snap + "---|---|---|---|---|---|"]
        for r in items:
            t = r["ticker"]
            info = tracks.get(t, {"letters": [None] * n_snap, "scores": [None] * n_snap})
            cells = []
            for j, l in enumerate(info["letters"]):
                s = info["scores"][j]
                cells.append("–" if not l else (f"**{l}**{'' if s is None else f' {s:g}'}"
                                                if l in ABOVE else f"{l}{'' if s is None else f' {s:g}'}"))
            price = r.get("price") or 0
            pivot = r.get("year_high") or 0
            to_p = (pivot - price) / price * 100 if price else 0
            c1, c3 = r.get("chg_1m"), r.get("chg_3m")
            note = esc(notes.get(t, {}).get("note", ""))[:90]
            ed = notes.get(t, {}).get("earnings_date", "")
            if ed:
                note = f"{note} 財報:{ed[5:]}"
            out.append(
                f"| [{t}]({tv_url(t)}) | {esc((r.get('name') or '')[:18])} | {' | '.join(cells)} "
                f"| {arrow_txt(move_of(info)) if info.get('letters') else '＝'} | {price:,.2f} | +{to_p:.1f}% "
                f"| {'–' if c1 is None else f'{c1:+.1f}%'} | {'–' if c3 is None else f'{c3:+.1f}%'} "
                f"| {r.get('score', '')} | {note} |")
        return out + [""]

    L = [
        f"# VCP Watchlist {rev}｜清單 × 分級軌跡（合併版）",
        "",
        f"**產生時間：** {now_hkt.strftime('%Y.%m.%d %H:%M')} HKT（{now_utc.strftime('%H:%M')} UTC）｜"
        f"**模型：** {model}｜**版本：** {rev}",
        "",
        f"**資料基準：** 美股 2026-08-21 收盤，全市場 {len(rows)} 檔。本版把「當期分級清單」與「歷次分級軌跡」"
        f"合併為單一文件 — 每一列同時顯示該檔的即時數據與過去 {n_snap} 次掃描的級別變化。"
        "數據與 R6 相同（本版為呈現方式改版，非新一輪掃描）。",
        "",
        "> 本表為選股輔助工具，非投資建議。形態最終以圖表確認為準。",
        "",
        "### 各期掃描概況",
        "",
        "| 版本 | 數據日期 | A | E | B | C | D | 合計 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for rev_, d, snap_rows, _ in snaps:
        c = collections.Counter(LETTER_OF[r["category"]] for r in snap_rows.values())
        L.append(f"| {rev_} | {d} | {c['A']} | {c['E']} | {c['B']} | {c['C']} | {c['D']} | {sum(c.values())} |")
    L.append("")

    if scan.get("market"):
        L += ["### 市場背景", "", scan["market"], ""]

    L += ["**讀表：** 軌跡欄每格為該期級別與分數，粗體＝當期位於線上（A／E／B）；"
          "變化欄 ▲ 升級、▼ 降級、＝ 持平（比較最近兩次有數據的掃描）；「–」表示該期尚未納入宇宙。", ""]

    for cat in ["A_VCP待突破", "E_突破延伸中", "B_上升結構"]:
        items = sorted(groups.get(cat, []), key=lambda r: -r.get("score", 0))
        if not items:
            continue
        tier, title, desc = TIERS[cat]
        L += [f"## ▲ 線上｜{title}", "", desc, ""] + table(items)

    if dropped:
        L += ["---", "", "## ▼ 線下｜曾入選後跌出", "",
              f"共 {len(dropped)} 檔。這些股票在先前掃描中曾列於 A／E／B，目前已跌出觀察名單 — "
              "若基底重新收緊可望回歸，是下一輪 A 級的主要來源。", ""]
        L += table(sorted(dropped, key=lambda r: -r.get("score", 0)))

    for cat in ["C_基底修復中", "D_趨勢弱"]:
        items = sorted(groups.get(cat, []), key=lambda r: -r.get("score", 0))
        if not items:
            continue
        tier, title, desc = TIERS[cat]
        L += [f"## ▽ 線下｜{title}（未曾入選）", "", desc, ""]
        if cat == "D_趨勢弱":
            L.append("、".join(
                f"[{r['ticker']}]({tv_url(r['ticker'])})（{'→'.join(l or '–' for l in tracks[r['ticker']]['letters'])}"
                f"，距高 -{r['off_high_pct']:.0f}%）" for r in items))
            L.append("")
        else:
            L += table(items)

    online = sum(len(groups.get(c, [])) for c in ["A_VCP待突破", "E_突破延伸中", "B_上升結構"])
    L += [
        f"**線上合計 {online} 檔｜曾入選後跌出 {len(dropped)} 檔｜全宇宙 {len(rows)} 檔。**",
        "",
        "## 篩選方法",
        "",
        "1. **趨勢模板**：站上 50/200 日均線、50MA > 200MA、高於 52 週低點 ≥30%、距 52 週高點 ≤25%。",
        "2. **緊縮度**：近 1 個月漲跌幅收斂 ±7% 內且貼近高點 → 基底右側收緊（VCP 特徵）。",
        "3. **量能**：現量低於 50 日均量 → 突破前典型量縮。",
        "4. **動能**：6 個月 / 1 年漲幅確認主升趨勢仍在。",
        "5. 「一底高於一底」「上升三角形」為結構推斷 — 點代號開 TradingView 圖確認低點墊高與上緣壓力線。",
        "",
        "**分數**（0–100）：均線結構 30 ＋ 距樞紐 15 ＋ 月線緊縮 15 ＋ 中長期動能 20 ＋ 量縮 10 ＋ 貼緊樞紐加成 5。",
        "",
        "_資料來源：Bigdata.com 與網路搜尋報價；圖表連結：TradingView。非投資建議。_",
        "",
    ]
    return "\n".join(L)


# ------------------------------------------------------------------------- HTML
def render_html(snaps, tracks, scan, rev, model, now_hkt):
    rows = scan["rows"]
    notes = {n["ticker"]: n for n in scan.get("notes", [])}
    n_snap = len(snaps)

    groups = collections.defaultdict(list)
    dropped = []
    for r in rows:
        t = r["ticker"]
        info = tracks.get(t)
        if LETTER_OF[r["category"]] in ABOVE:
            groups[r["category"]].append(r)
        elif info and info["ever_above"]:
            dropped.append(r)
        else:
            groups[r["category"]].append(r)
    counts = {c: len(groups.get(c, [])) for c in ORDER}
    online = counts["A_VCP待突破"] + counts["E_突破延伸中"] + counts["B_上升結構"]

    snap_heads = "".join(
        f'<th class="st">{r}<small>{d[5:].replace("-", "/")}</small></th>' for r, d, _, _ in snaps)
    thead = (f'<thead><tr><th>代號</th><th>名稱</th>{snap_heads}<th class="tr">變化</th>'
             '<th class="num">收盤</th><th class="num">距樞紐</th><th class="num">1月</th>'
             '<th class="num">3月</th><th class="num">量比</th><th class="num">分數</th>'
             '<th>備註</th></tr></thead>')

    def pct_td(v):
        if v is None:
            return '<td class="num">–</td>'
        cls = "up" if v > 0 else "dn" if v < 0 else ""
        return f'<td class="num {cls}">{v:+.1f}%</td>'

    def row_html(r):
        t = r["ticker"]
        info = tracks.get(t, {"letters": [None] * n_snap, "scores": [None] * n_snap})
        cells = ""
        for j, l in enumerate(info["letters"]):
            s = info["scores"][j]
            if not l:
                cells += '<td class="st none">–</td>'
            else:
                sc = "" if s is None else f'<i>{s:g}</i>'
                cells += f'<td class="st t{l}"><b>{l}</b>{sc}</td>'
        mv = move_of(info)
        arrow = ('<span class="mv up">▲</span>' if mv > 0 else
                 '<span class="mv dn">▼</span>' if mv < 0 else '<span class="mv fl">＝</span>')
        price = r.get("price") or 0
        pivot = r.get("year_high") or 0
        to_p = (pivot - price) / price * 100 if price else 0
        vol = r.get("vol_ratio")
        vol_cls = "dry" if isinstance(vol, (int, float)) and vol < 0.7 else ""
        vol_txt = "–" if vol is None else f"{vol}"
        note = esc(notes.get(t, {}).get("note", ""))
        ed = notes.get(t, {}).get("earnings_date", "")
        ed_chip = f'<span class="chip-cal">財報 {esc(ed[5:].replace("-", "/"))}</span>' if ed else ""
        ex = EXCHANGE.get(t, "").upper()
        return (f'<tr><td class="tk"><a href="{tv_url(t)}" target="_blank" rel="noopener">{t}'
                f'<small>{ex}</small></a></td>'
                f'<td class="nm">{esc((r.get("name") or "")[:20])}</td>{cells}'
                f'<td class="tr">{arrow}</td>'
                f'<td class="num">{price:,.2f}</td>'
                f'<td class="num pivot">+{to_p:.1f}%</td>'
                f'{pct_td(r.get("chg_1m"))}{pct_td(r.get("chg_3m"))}'
                f'<td class="num {vol_cls}">{vol_txt}</td>'
                f'<td class="num"><span class="scorebar"><i style="width:{min(r.get("score", 0), 100):.0f}%"></i>'
                f'<b>{r.get("score", 0):g}</b></span></td>'
                f'<td class="note">{note} {ed_chip}</td></tr>')

    def table(items):
        trs = "\n".join(row_html(r) for r in items)
        return f'<div class="tblwrap"><table>{thead}<tbody>{trs}</tbody></table></div>'

    sections = []
    for cat in ["A_VCP待突破", "E_突破延伸中", "B_上升結構"]:
        items = sorted(groups.get(cat, []), key=lambda r: -r.get("score", 0))
        if not items:
            continue
        tier, title, desc = TIERS[cat]
        sections.append(
            f'<section class="tier tier-{tier.lower()}" id="tier-{tier.lower()}">'
            f'<header class="tier-head"><span class="badge">{tier}</span>'
            f'<div><h2>▲ 線上｜{esc(title)}</h2><p>{esc(desc)}</p></div>'
            f'<span class="count">{len(items)} 檔</span></header>{table(items)}</section>')

    if dropped:
        sections.append(
            '<div class="divider"><hr><span>以下為線下</span><hr></div>'
            '<section class="tier tier-drop" id="tier-drop">'
            '<header class="tier-head"><span class="badge b-drop">▼</span>'
            '<div><h2>線下｜曾入選後跌出</h2><p>先前掃描曾列於 A／E／B，目前已跌出觀察名單 — '
            '若基底重新收緊可望回歸，是下一輪 A 級的主要來源。</p></div>'
            f'<span class="count">{len(dropped)} 檔</span></header>'
            f'{table(sorted(dropped, key=lambda r: -r.get("score", 0)))}</section>')

    for cat in ["C_基底修復中", "D_趨勢弱"]:
        items = sorted(groups.get(cat, []), key=lambda r: -r.get("score", 0))
        if not items:
            continue
        tier, title, desc = TIERS[cat]
        if cat == "D_趨勢弱":
            chips = "".join(
                f'<a class="dchip" href="{tv_url(r["ticker"])}" target="_blank" rel="noopener">'
                f'{r["ticker"]}<small>{"".join(l or "–" for l in tracks[r["ticker"]]["letters"])}'
                f' · −{r["off_high_pct"]:.0f}%</small></a>'
                for r in sorted(items, key=lambda r: r["off_high_pct"]))
            body = f'<div class="dwrap">{chips}</div>'
        else:
            body = table(items)
        sections.append(
            f'<section class="tier tier-{tier.lower()}" id="tier-{tier.lower()}">'
            f'<header class="tier-head"><span class="badge">{tier}</span>'
            f'<div><h2>▽ 線下｜{esc(title)}（未曾入選）</h2><p>{esc(desc)}</p></div>'
            f'<span class="count">{len(items)} 檔</span></header>{body}</section>')

    summary_rows = ""
    for rev_, d, snap_rows, _ in snaps:
        c = collections.Counter(LETTER_OF[r["category"]] for r in snap_rows.values())
        cur = ' class="cur"' if rev_ == snaps[-1][0] else ""
        summary_rows += (f'<tr{cur}><td class="tk">{rev_}</td><td class="nm">{d}</td>'
                         + "".join(f'<td class="num t{k}b">{c[k]}</td>' for k in "AEBCD")
                         + f'<td class="num">{sum(c.values())}</td></tr>')

    return f"""<title>VCP Watchlist {rev}</title>
<style>
:root {{
  --bg:#F5F6F4; --panel:#FFFFFF; --ink:#1B2430; --muted:#5D6B7A; --line:#DDE2E0;
  --accent:#B07B24; --accent-soft:#F3E8D3; --up:#17835C; --dn:#C24A3F; --dry:#B07B24;
  --head:#EDEFEA; --hover:#F0F3EE;
  --tA:#17835C; --tE:#B07B24; --tB:#2C6E9E; --tC:#7A8794; --tD:#A8B0B8; --tDrop:#C24A3F;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#0E1216; --panel:#151B21; --ink:#E4E9EC; --muted:#8B98A5; --line:#26303A;
    --accent:#E5B15C; --accent-soft:#2A2418; --up:#3FB68B; --dn:#E0705F; --dry:#E5B15C;
    --head:#1A222A; --hover:#1C242D;
    --tA:#3FB68B; --tE:#E5B15C; --tB:#5CA3D6; --tC:#6B7885; --tD:#4A555F; --tDrop:#E0705F;
  }}
}}
:root[data-theme="dark"] {{
  --bg:#0E1216; --panel:#151B21; --ink:#E4E9EC; --muted:#8B98A5; --line:#26303A;
  --accent:#E5B15C; --accent-soft:#2A2418; --up:#3FB68B; --dn:#E0705F; --dry:#E5B15C;
  --head:#1A222A; --hover:#1C242D;
  --tA:#3FB68B; --tE:#E5B15C; --tB:#5CA3D6; --tC:#6B7885; --tD:#4A555F; --tDrop:#E0705F;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.55 "Avenir Next","Segoe UI","PingFang TC","Microsoft JhengHei",system-ui,sans-serif; }}
.wrap {{ max-width:1340px; margin:0 auto; padding:28px 20px 60px; }}
.masthead {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:10px 18px;
  border-bottom:3px solid var(--ink); padding-bottom:14px; }}
.masthead h1 {{ font-size:29px; margin:0; letter-spacing:-0.01em; text-wrap:balance; }}
.masthead h1 em {{ font-style:normal; color:var(--accent); }}
.meta {{ color:var(--muted); font-size:13px; }}
.meta b {{ color:var(--ink); font-weight:600; }}
.lede {{ margin:16px 0 0; color:var(--muted); font-size:13.5px; max-width:80ch; }}
.lede b {{ color:var(--ink); }}
.summary {{ display:flex; gap:10px; flex-wrap:wrap; margin:16px 0 6px; }}
.summary a {{ text-decoration:none; color:inherit; }}
.stat {{ display:flex; align-items:center; gap:9px; background:var(--panel);
  border:1px solid var(--line); border-radius:6px; padding:8px 14px; }}
.stat .dot {{ width:10px; height:10px; border-radius:2px; }}
.stat b {{ font-size:20px; font-variant-numeric:tabular-nums; }}
.stat span {{ color:var(--muted); font-size:12.5px; }}
h3.sec {{ font-size:15px; margin:28px 0 8px; }}
.market {{ background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--accent);
  border-radius:6px; padding:14px 18px; margin:14px 0 4px; font-size:14px; color:var(--muted); }}
.market strong {{ color:var(--ink); }}
.tier {{ margin-top:32px; }}
.tier-head {{ display:flex; align-items:flex-start; gap:14px; margin-bottom:10px; }}
.tier-head h2 {{ margin:0; font-size:19px; }}
.tier-head p {{ margin:2px 0 0; color:var(--muted); font-size:13.5px; max-width:72ch; }}
.tier-head .count {{ margin-left:auto; color:var(--muted); font-size:13px; white-space:nowrap; padding-top:4px; }}
.badge {{ flex:none; width:34px; height:34px; border-radius:6px; display:grid; place-items:center;
  font-weight:700; font-size:17px; color:var(--bg); }}
.tier-a .badge {{ background:var(--tA); }} .tier-e .badge {{ background:var(--tE); }}
.tier-b .badge {{ background:var(--tB); }} .tier-c .badge {{ background:var(--tC); }}
.tier-d .badge {{ background:var(--tD); }} .badge.b-drop {{ background:var(--tDrop); }}
.divider {{ display:flex; align-items:center; gap:14px; margin:44px 0 0; }}
.divider hr {{ flex:1; border:0; border-top:2px dashed var(--accent); margin:0; }}
.divider span {{ color:var(--accent); font-size:13px; font-weight:700; letter-spacing:0.08em; }}
.tblwrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--panel); }}
table {{ border-collapse:collapse; width:100%; min-width:1080px; font-size:13.5px; }}
th {{ background:var(--head); text-align:left; padding:7px 9px; font-size:11.5px;
  text-transform:uppercase; letter-spacing:0.04em; color:var(--muted); white-space:nowrap; }}
th small {{ display:block; font-size:10px; letter-spacing:0; text-transform:none; font-weight:400; }}
td {{ padding:7px 9px; border-top:1px solid var(--line); vertical-align:top; }}
tbody tr:hover {{ background:var(--hover); }}
td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums;
  font-family:"SF Mono","Cascadia Mono",Consolas,ui-monospace,monospace; font-size:12.5px; white-space:nowrap; }}
td.tk {{ white-space:nowrap; }}
td.tk a {{ display:inline-block; font-weight:700; color:var(--accent); text-decoration:none;
  border-bottom:1px solid transparent; }}
td.tk a small {{ display:block; font-size:9.5px; font-weight:600; letter-spacing:0.06em; color:var(--muted); }}
td.tk a:hover, td.tk a:focus-visible {{ border-bottom-color:var(--accent); outline:none; }}
td.nm {{ color:var(--muted); font-size:12.5px; white-space:nowrap; }}
th.st, td.st {{ text-align:center; }}
td.st {{ font-variant-numeric:tabular-nums; white-space:nowrap; }}
td.st b {{ display:inline-block; width:19px; height:19px; line-height:19px; border-radius:4px;
  color:var(--bg); font-size:11.5px; }}
td.st i {{ display:block; font-style:normal; font-size:10px; color:var(--muted); margin-top:1px; }}
td.st.none {{ color:var(--muted); }}
td.tA b {{ background:var(--tA); }} td.tE b {{ background:var(--tE); }}
td.tB b {{ background:var(--tB); }} td.tC b {{ background:var(--tC); }} td.tD b {{ background:var(--tD); }}
td.tAb {{ color:var(--tA); font-weight:700; }} td.tEb {{ color:var(--tE); font-weight:700; }}
td.tBb {{ color:var(--tB); font-weight:700; }} td.tCb, td.tDb {{ color:var(--muted); }}
tr.cur td {{ background:var(--accent-soft); font-weight:600; }}
td.tr, th.tr {{ text-align:center; }}
.mv {{ font-size:13px; }} .mv.up {{ color:var(--up); }} .mv.dn {{ color:var(--dn); }}
.mv.fl {{ color:var(--muted); }}
td.up {{ color:var(--up); }} td.dn {{ color:var(--dn); }}
td.pivot {{ color:var(--accent); font-weight:600; }} td.dry {{ color:var(--dry); font-weight:600; }}
td.note {{ min-width:200px; max-width:330px; color:var(--muted); font-size:12px;
  line-height:1.45; white-space:normal; }}
.chip-cal {{ display:inline-block; background:var(--accent-soft); color:var(--accent); border-radius:4px;
  padding:1px 7px; font-size:11px; font-weight:600; white-space:nowrap; }}
.scorebar {{ display:inline-flex; align-items:center; gap:7px; min-width:88px; }}
.scorebar i {{ display:block; height:5px; border-radius:3px; background:var(--accent);
  min-width:3px; max-width:56px; flex:none; }}
.scorebar b {{ font-size:12.5px; }}
.dwrap {{ display:flex; flex-wrap:wrap; gap:7px; }}
.dchip {{ display:inline-flex; flex-direction:column; background:var(--panel); border:1px solid var(--line);
  border-radius:5px; padding:4px 10px; text-decoration:none; color:var(--muted); font-size:12.5px; font-weight:700; }}
.dchip small {{ font-weight:400; font-size:10px; letter-spacing:0.04em; }}
.dchip:hover, .dchip:focus-visible {{ border-color:var(--accent); color:var(--ink); outline:none; }}
.method {{ margin-top:40px; border-top:1px solid var(--line); padding-top:18px;
  color:var(--muted); font-size:13.5px; max-width:80ch; }}
.method h3 {{ color:var(--ink); font-size:15px; margin:0 0 8px; }}
.method ol {{ padding-left:20px; margin:8px 0; }} .method li {{ margin:4px 0; }}
.disclaimer {{ margin-top:14px; font-size:12.5px; border-left:3px solid var(--dn); padding-left:12px; }}
a {{ color:var(--accent); }}
@media (max-width:640px) {{ .masthead h1 {{ font-size:23px; }} .tier-head .count {{ display:none; }} }}
</style>
<div class="wrap">
<header class="masthead">
  <h1>VCP Watchlist <em>{rev}</em></h1>
  <span class="meta"><b>美股全市場 · {len(rows)} 檔</b>｜數據基準 2026-08-21 收盤｜
  追蹤 {n_snap} 次更新｜產生 {now_hkt.strftime('%Y.%m.%d %H:%M')} HKT｜{esc(model)}</span>
</header>
<p class="lede">本版把<b>當期分級清單</b>與<b>歷次分級軌跡</b>合併為單一文件 —
每一列同時顯示該檔的即時數據與過去 {n_snap} 次掃描的級別變化。
<b>線上</b>＝目前列於觀察名單（A／E／B）；<b>線下</b>分為「曾入選後跌出」（重點覆盤對象）與「未曾入選」。
數據與 R6 相同，本版為呈現方式改版而非新一輪掃描。</p>
<nav class="summary">
  <a href="#tier-a"><span class="stat"><span class="dot" style="background:var(--tA)"></span><b>{counts['A_VCP待突破']}</b><span>A・VCP 待突破</span></span></a>
  <a href="#tier-e"><span class="stat"><span class="dot" style="background:var(--tE)"></span><b>{counts['E_突破延伸中']}</b><span>E・突破延伸中</span></span></a>
  <a href="#tier-b"><span class="stat"><span class="dot" style="background:var(--tB)"></span><b>{counts['B_上升結構']}</b><span>B・上升結構</span></span></a>
  <a href="#tier-drop"><span class="stat"><span class="dot" style="background:var(--tDrop)"></span><b>{len(dropped)}</b><span>▼ 曾入選後跌出</span></span></a>
  <a href="#tier-c"><span class="stat"><span class="dot" style="background:var(--tC)"></span><b>{counts['C_基底修復中']}</b><span>C・基底修復</span></span></a>
  <a href="#tier-d"><span class="stat"><span class="dot" style="background:var(--tD)"></span><b>{counts['D_趨勢弱']}</b><span>D・趨勢弱</span></span></a>
</nav>

<h3 class="sec">各期掃描概況</h3>
<div class="tblwrap"><table style="min-width:520px">
<thead><tr><th>版本</th><th>數據日期</th><th class="num">A</th><th class="num">E</th><th class="num">B</th>
<th class="num">C</th><th class="num">D</th><th class="num">合計</th></tr></thead>
<tbody>{summary_rows}</tbody></table></div>

<p class="market"><strong>市場背景</strong> — {esc(scan.get('market', ''))}</p>
<p class="lede"><b>讀表：</b>軌跡各格為該期級別與分數（有色方塊＝該期在線上）；變化欄 ▲ 升級、▼ 降級、＝ 持平
（比較最近兩次有數據的掃描）；「–」表示該期尚未納入宇宙。</p>
{''.join(sections)}
<footer class="method">
<h3>篩選方法</h3>
<ol>
<li><b>趨勢模板</b>：站上 50/200 日均線、50MA &gt; 200MA、高於 52 週低點 ≥30%、距 52 週高點 ≤25%。</li>
<li><b>緊縮度</b>：近 1 個月漲跌幅收斂 ±7% 內且貼近高點 → 基底右側收緊（VCP 特徵）。</li>
<li><b>量能</b>：現量低於 50 日均量（量比 &lt; 1）→ 突破前典型量縮，金色標示 &lt; 0.7；「–」為新增股票尚無量能基準。</li>
<li><b>動能</b>：6 個月 / 1 年漲幅確認主升趨勢仍在。</li>
<li>「一底高於一底」「上升三角形」為結構推斷 — 點代號開 TradingView 圖確認低點墊高與上緣壓力線。</li>
</ol>
<p><b>分數</b>（0–100）：均線結構 30 ＋ 距樞紐 15 ＋ 月線緊縮 15 ＋ 中長期動能 20 ＋ 量縮 10 ＋ 貼緊樞紐加成 5。</p>
<p>線上合計 <b>{online}</b> 檔；曾入選後跌出 <b>{len(dropped)}</b> 檔；全宇宙 <b>{len(rows)}</b> 檔。
資料來源：<a href="https://bigdata.com" target="_blank" rel="noopener">Bigdata.com</a> 與網路搜尋報價；圖表：TradingView。</p>
<p class="disclaimer">本表為技術面選股輔助工具，非投資建議。分級由量化規則產生，形態最終以圖表確認為準。</p>
</footer>
</div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="R7")
    ap.add_argument("--model", default="Opus5;high")
    ap.add_argument("--updates", type=int, default=10)
    args = ap.parse_args()

    snaps = load_snapshots(args.updates)
    if not snaps:
        raise SystemExit("no scan_R*.json snapshots found")
    tracks = build_tracks(snaps)
    scan = snaps[-1][3]

    now_utc = datetime.now(timezone.utc)
    now_hkt = now_utc + timedelta(hours=8)
    stamp = now_hkt.strftime("%m.%d_%H.%M")
    base = f"VCP watchlist (Github)_{args.rev} ({args.model})_({stamp})"

    open(f"{base}.md", "w").write(render_md(snaps, tracks, scan, args.rev, args.model, now_hkt, now_utc))
    open(f"{base}.html", "w").write(render_html(snaps, tracks, scan, args.rev, args.model, now_hkt))

    rows = scan["rows"]
    snap_revs = [s[0] for s in snaps]
    with open(f"{base}.csv", "w", newline="") as fh:
        cols = (["ticker", "name", "category", "score", "price", "year_high", "off_high_pct",
                 "chg_1m", "chg_3m", "chg_6m", "chg_1y", "vol_ratio", "as_of"]
                + [f"tier_{r}" for r in snap_revs])
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda r: -r.get("score", 0)):
            info = tracks.get(r["ticker"], {"letters": []})
            row = dict(r)
            for rev_, l in zip(snap_revs, info["letters"]):
                row[f"tier_{rev_}"] = l or ""
            w.writerow(row)

    print(f"{base}.md")
    print(f"{base}.csv")
    print(f"{base}.html")
    print(f"snapshots: {', '.join(f'{r}({d})' for r, d, _, _ in snaps)}")


if __name__ == "__main__":
    main()

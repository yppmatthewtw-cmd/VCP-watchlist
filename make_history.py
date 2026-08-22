#!/usr/bin/env python3
"""Generate the VCP watchlist history tracker (Markdown + HTML).

Reads every scan_R*.json snapshot, lines them up chronologically (most recent
10), and shows each ticker's tier trajectory across updates. Tickers currently
in tiers A/E/B sit above the line; everything else sits below it, split into
those that dropped out of the watchlist and those that never qualified.

Usage: python make_history.py [--rev R3] [--model "Opus5;high"] [--updates 10]
"""

from __future__ import annotations

import argparse
import collections
import glob
import html
import json
import re
from datetime import datetime, timedelta, timezone

from exchanges import EXCHANGE, tv_url

# tier key -> (letter, rank, label). Lower rank = stronger setup.
TIERS = {
    "A_VCP待突破":  ("A", 0, "VCP 緊縮待突破"),
    "E_突破延伸中": ("E", 1, "已突破延伸中"),
    "B_上升結構":   ("B", 2, "上升結構"),
    "C_基底修復中": ("C", 3, "基底修復中"),
    "D_趨勢弱":     ("D", 4, "趨勢偏弱"),
}
ABOVE = {"A", "E", "B"}   # 線上：觀察名單
LETTER_OF = {k: v[0] for k, v in TIERS.items()}
RANK_OF = {v[0]: v[1] for v in TIERS.values()}


def esc(s):
    return html.escape(str(s), quote=True)


def load_snapshots(limit: int):
    """Return [(rev, data_date, {ticker: row}), ...] oldest first."""
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
        data_date = dates.most_common(1)[0][0]
        snaps.append((m.group(1), data_date, {r["ticker"]: r for r in rows}, scan))
    snaps.sort(key=lambda s: (s[1], s[0]))
    return snaps[-limit:]


def build(snaps):
    """ticker -> {letters: [...], scores: [...], row: latest_row, first_seen: idx}"""
    tickers = sorted({t for _, _, rows, _ in snaps for t in rows})
    track = {}
    for t in tickers:
        letters, scores, rows_seen = [], [], []
        for _, _, rows, _ in snaps:
            r = rows.get(t)
            letters.append(LETTER_OF.get(r["category"]) if r else None)
            scores.append(r.get("score") if r else None)
            rows_seen.append(r)
        latest = next((r for r in reversed(rows_seen) if r), None)
        seen = [l for l in letters if l]
        track[t] = {
            "letters": letters,
            "scores": scores,
            "row": latest,
            "now": letters[-1],
            "best": min((RANK_OF[l] for l in seen), default=9),
            "ever_above": any(l in ABOVE for l in seen),
        }
    return track


def classify_group(info):
    now = info["now"]
    if now and now in ABOVE:
        return "watch"
    return "dropped" if info["ever_above"] else "never"


def move_of(info):
    """Compare the two most recent snapshots where the ticker appeared."""
    seq = [l for l in info["letters"] if l]
    if len(seq) < 2:
        return 0
    return RANK_OF[seq[-2]] - RANK_OF[seq[-1]]  # >0 = upgraded


def traj_str(letters):
    return " → ".join(l or "–" for l in letters)


# --------------------------------------------------------------------------- MD
def render_md(snaps, track, rev, model, stamp_txt):
    heads = [f"{rev_}<br><small>{d[5:].replace('-', '/')}</small>" for rev_, d, _, _ in snaps]
    n = len(snaps)
    groups = collections.defaultdict(list)
    for t, info in track.items():
        groups[classify_group(info)].append((t, info))

    def sort_watch(item):
        t, i = item
        return (RANK_OF[i["now"]], -(i["row"].get("score") or 0))

    def sort_drop(item):
        t, i = item
        return (i["best"], -(i["row"].get("score") or 0))

    L = [
        f"# VCP Watchlist 歷史追蹤 {rev}",
        "",
        f"**產生時間：** {stamp_txt}｜**模型：** {model}｜**追蹤更新次數：** {n}（最多保留最近 10 次）",
        "",
        "本表把歷次掃描並排，顯示每檔的分級軌跡。**線上**＝目前列於觀察名單（A／E／B 級）；"
        "**線下**＝目前不符合進場條件，其中「曾入選後跌出」是重點覆盤對象。",
        "",
        "| 級別 | 意義 |",
        "|---|---|",
        "| **A** | VCP 緊縮待突破（趨勢模板通過＋距高 ≤10%＋月線收斂 ±7%） |",
        "| **E** | 已突破延伸中（貼頂且月線大漲，勿追高） |",
        "| **B** | 上升結構（一底高於一底／上升三角形候選） |",
        "| C | 基底修復中（線下） |",
        "| D | 趨勢偏弱（線下） |",
        "",
        "### 各期掃描概況",
        "",
        "| 版本 | 數據日期 | A | E | B | C | D |",
        "|---|---|---|---|---|---|---|",
    ]
    for rev_, d, rows, _ in snaps:
        c = collections.Counter(LETTER_OF[r["category"]] for r in rows.values())
        L.append(f"| {rev_} | {d} | {c['A']} | {c['E']} | {c['B']} | {c['C']} | {c['D']} |")
    L.append("")

    def table(items, note=""):
        out = [f"| 代號 | 名稱 | {' | '.join(heads)} | 軌跡 | 現價 | 距樞紐 | 1月 |",
               "|---|---|" + "---|" * n + "---|---|---|---|"]
        for t, i in items:
            r = i["row"]
            cells = []
            for j, l in enumerate(i["letters"]):
                s = i["scores"][j]
                cells.append(f"**{l}** {s:g}" if l and l in ABOVE else (f"{l} {s:g}" if l else "–"))
            price = r.get("price") or 0
            pivot = r.get("year_high") or 0
            to_p = (pivot - price) / price * 100 if price else 0
            mv = move_of(i)
            arrow = "▲" if mv > 0 else ("▼" if mv < 0 else "＝")
            out.append(
                f"| [{t}]({tv_url(t)}) | {esc((r.get('name') or '')[:20])} | {' | '.join(cells)} "
                f"| {arrow} {traj_str(i['letters'])} | {price:,.2f} | +{to_p:.1f}% "
                f"| {(('%+.1f%%' % r['chg_1m']) if r.get('chg_1m') is not None else '–')} |")
        return out + [""]

    L += ["## ▲ 線上｜目前觀察名單", "",
          f"共 {len(groups['watch'])} 檔。分數為各期 VCP 評分（0–100）。", ""]
    L += table(sorted(groups["watch"], key=sort_watch))

    L += ["---", "", "## ▼ 線下｜曾入選後跌出", "",
          f"共 {len(groups['dropped'])} 檔。這些股票在先前掃描中曾列於 A／E／B，"
          "目前已跌出觀察名單——若基底重新收緊可望回歸，值得持續留意。", ""]
    L += table(sorted(groups["dropped"], key=sort_drop))

    never = sorted(groups["never"], key=lambda x: x[0])
    L += ["## ▽ 線下｜未曾入選", "",
          f"共 {len(never)} 檔，掃描期間從未達到 A／E／B。", "",
          "、".join(f"[{t}]({tv_url(t)})（{traj_str(i['letters'])}）" for t, i in never), ""]

    L += ["## 讀表方式", "",
          "1. **軌跡欄**的箭頭比較最近兩次有數據的掃描：▲ 升級、▼ 降級、＝ 持平。",
          "2. 粗體級別代表該期位於線上（觀察名單內）。",
          "3. 連續維持 A 級且分數上升者，是基底最扎實的一批；A→B→A 來回擺盪多因單日急漲跌，需開圖確認。",
          "4. 「曾入選後跌出」若在下一期回到 A/B，通常代表洗盤後再度收緊——是 VCP 的典型行為。",
          "",
          "_資料來源：Bigdata.com 與網路搜尋報價；圖表連結：TradingView。非投資建議。_", ""]
    return "\n".join(L)


# ------------------------------------------------------------------------- HTML
def render_html(snaps, track, rev, model, stamp_txt):
    n = len(snaps)
    groups = collections.defaultdict(list)
    for t, info in track.items():
        groups[classify_group(info)].append((t, info))

    def cell(l, s):
        if not l:
            return '<td class="st none">–</td>'
        return f'<td class="st t{l}"><b>{l}</b><i>{s:g}</i></td>' if s is not None \
            else f'<td class="st t{l}"><b>{l}</b></td>'

    def rows_html(items):
        out = []
        for t, i in items:
            r = i["row"]
            price = r.get("price") or 0
            pivot = r.get("year_high") or 0
            to_p = (pivot - price) / price * 100 if price else 0
            mv = move_of(i)
            arrow = f'<span class="mv up">▲</span>' if mv > 0 else (
                f'<span class="mv dn">▼</span>' if mv < 0 else '<span class="mv fl">＝</span>')
            c1 = r.get("chg_1m")
            if c1 is None:
                c1_td = '<td class="num">–</td></tr>'
            else:
                c1_cls = "up" if c1 > 0 else "dn" if c1 < 0 else ""
                c1_td = f'<td class="num {c1_cls}">{c1:+.1f}%</td></tr>'
            ex = EXCHANGE.get(t, "").upper()
            cells = "".join(cell(l, i["scores"][j]) for j, l in enumerate(i["letters"]))
            out.append(
                f'<tr><td class="tk"><a href="{tv_url(t)}" target="_blank" rel="noopener">'
                f'{t}<small>{ex}</small></a></td>'
                f'<td class="nm">{esc((r.get("name") or "")[:22])}</td>{cells}'
                f'<td class="tr">{arrow}</td>'
                f'<td class="num">{price:,.2f}</td>'
                f'<td class="num pivot">+{to_p:.1f}%</td>' + c1_td)
        return "\n".join(out)

    heads = "".join(
        f'<th class="st">{rev_}<small>{d[5:].replace("-", "/")}</small></th>'
        for rev_, d, _, _ in snaps)
    thead = (f'<thead><tr><th>代號</th><th>名稱</th>{heads}'
             '<th class="tr">變化</th><th class="num">現價</th>'
             '<th class="num">距樞紐</th><th class="num">1月</th></tr></thead>')

    def table(items):
        return (f'<div class="tblwrap"><table>{thead}<tbody>{rows_html(items)}</tbody></table></div>')

    watch = sorted(groups["watch"], key=lambda x: (RANK_OF[x[1]["now"]], -(x[1]["row"].get("score") or 0)))
    dropped = sorted(groups["dropped"], key=lambda x: (x[1]["best"], -(x[1]["row"].get("score") or 0)))
    never = sorted(groups["never"], key=lambda x: x[0])

    summary_rows = ""
    for rev_, d, rows, _ in snaps:
        c = collections.Counter(LETTER_OF[r["category"]] for r in rows.values())
        summary_rows += (f'<tr><td class="tk">{rev_}</td><td class="nm">{d}</td>'
                         + "".join(f'<td class="num t{k}b">{c[k]}</td>' for k in "AEBCD")
                         + f'<td class="num">{sum(c.values())}</td></tr>')

    never_chips = "".join(
        f'<a class="dchip" href="{tv_url(t)}" target="_blank" rel="noopener">{t}'
        f'<small>{traj_str(i["letters"])}</small></a>' for t, i in never)

    return f"""<title>VCP 分級軌跡追蹤</title>
<style>
:root {{
  --bg:#F5F6F4; --panel:#FFF; --ink:#1B2430; --muted:#5D6B7A; --line:#DDE2E0;
  --accent:#B07B24; --accent-soft:#F3E8D3; --up:#17835C; --dn:#C24A3F;
  --head:#EDEFEA; --hover:#F0F3EE;
  --tA:#17835C; --tE:#B07B24; --tB:#2C6E9E; --tC:#7A8794; --tD:#A8B0B8;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#0E1216; --panel:#151B21; --ink:#E4E9EC; --muted:#8B98A5; --line:#26303A;
    --accent:#E5B15C; --accent-soft:#2A2418; --up:#3FB68B; --dn:#E0705F;
    --head:#1A222A; --hover:#1C242D;
    --tA:#3FB68B; --tE:#E5B15C; --tB:#5CA3D6; --tC:#6B7885; --tD:#4A555F;
  }}
}}
:root[data-theme="dark"] {{
  --bg:#0E1216; --panel:#151B21; --ink:#E4E9EC; --muted:#8B98A5; --line:#26303A;
  --accent:#E5B15C; --accent-soft:#2A2418; --up:#3FB68B; --dn:#E0705F;
  --head:#1A222A; --hover:#1C242D;
  --tA:#3FB68B; --tE:#E5B15C; --tB:#5CA3D6; --tC:#6B7885; --tD:#4A555F;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.55 "Avenir Next","Segoe UI","PingFang TC","Microsoft JhengHei",system-ui,sans-serif; }}
.wrap {{ max-width:1240px; margin:0 auto; padding:28px 20px 60px; }}
.masthead {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:10px 18px;
  border-bottom:3px solid var(--ink); padding-bottom:14px; }}
.masthead h1 {{ font-size:29px; margin:0; letter-spacing:-0.01em; }}
.masthead h1 em {{ font-style:normal; color:var(--accent); }}
.meta {{ color:var(--muted); font-size:13px; }}
.lede {{ margin:16px 0 0; color:var(--muted); font-size:14px; max-width:76ch; }}
.lede b {{ color:var(--ink); }}
.legend {{ display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 4px; }}
.lg {{ display:inline-flex; align-items:center; gap:7px; background:var(--panel);
  border:1px solid var(--line); border-radius:6px; padding:5px 11px; font-size:12.5px; color:var(--muted); }}
.lg b {{ width:20px; height:20px; border-radius:4px; display:grid; place-items:center;
  color:var(--bg); font-size:12px; }}
h2 {{ font-size:19px; margin:34px 0 4px; display:flex; align-items:center; gap:10px; }}
h2 span.n {{ color:var(--muted); font-size:13px; font-weight:400; }}
h2 .rule {{ flex:1; height:1px; background:var(--line); }}
.sec-note {{ margin:0 0 12px; color:var(--muted); font-size:13.5px; max-width:76ch; }}
.divider {{ display:flex; align-items:center; gap:14px; margin:42px 0 0; }}
.divider hr {{ flex:1; border:0; border-top:2px dashed var(--accent); margin:0; }}
.divider span {{ color:var(--accent); font-size:13px; font-weight:700; letter-spacing:0.08em; }}
.tblwrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--panel); }}
table {{ border-collapse:collapse; width:100%; font-size:13.5px; }}
th {{ background:var(--head); text-align:left; padding:7px 10px; font-size:11.5px;
  text-transform:uppercase; letter-spacing:0.04em; color:var(--muted); white-space:nowrap; }}
th small {{ display:block; font-size:10px; letter-spacing:0; text-transform:none; font-weight:400; }}
td {{ padding:7px 10px; border-top:1px solid var(--line); white-space:nowrap; }}
tbody tr:hover {{ background:var(--hover); }}
td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums;
  font-family:"SF Mono","Cascadia Mono",Consolas,ui-monospace,monospace; font-size:12.5px; }}
td.nm {{ color:var(--muted); font-size:12.5px; }}
td.tk a {{ display:inline-block; font-weight:700; color:var(--accent); text-decoration:none;
  border-bottom:1px solid transparent; }}
td.tk a small {{ display:block; font-size:9.5px; font-weight:600; letter-spacing:0.06em; color:var(--muted); }}
td.tk a:hover, td.tk a:focus-visible {{ border-bottom-color:var(--accent); outline:none; }}
th.st, td.st {{ text-align:center; }}
td.st {{ font-variant-numeric:tabular-nums; }}
td.st b {{ display:inline-block; width:19px; height:19px; line-height:19px; border-radius:4px;
  color:var(--bg); font-size:11.5px; }}
td.st i {{ display:block; font-style:normal; font-size:10.5px; color:var(--muted); margin-top:1px; }}
td.st.none {{ color:var(--muted); }}
.tA b, td.tA b {{ background:var(--tA); }} .tE b, td.tE b {{ background:var(--tE); }}
.tB b, td.tB b {{ background:var(--tB); }} .tC b, td.tC b {{ background:var(--tC); }}
.tD b, td.tD b {{ background:var(--tD); }}
td.tAb {{ color:var(--tA); font-weight:700; }} td.tEb {{ color:var(--tE); font-weight:700; }}
td.tBb {{ color:var(--tB); font-weight:700; }} td.tCb, td.tDb {{ color:var(--muted); }}
td.tr, th.tr {{ text-align:center; }}
.mv {{ font-size:13px; }} .mv.up {{ color:var(--up); }} .mv.dn {{ color:var(--dn); }}
.mv.fl {{ color:var(--muted); }}
td.up {{ color:var(--up); }} td.dn {{ color:var(--dn); }} td.pivot {{ color:var(--accent); font-weight:600; }}
.dwrap {{ display:flex; flex-wrap:wrap; gap:7px; }}
.dchip {{ display:inline-flex; flex-direction:column; background:var(--panel);
  border:1px solid var(--line); border-radius:5px; padding:4px 10px; text-decoration:none;
  color:var(--muted); font-size:12.5px; font-weight:700; }}
.dchip small {{ font-weight:400; font-size:10.5px; letter-spacing:0.02em; }}
.dchip:hover, .dchip:focus-visible {{ border-color:var(--accent); color:var(--ink); outline:none; }}
.method {{ margin-top:40px; border-top:1px solid var(--line); padding-top:18px;
  color:var(--muted); font-size:13.5px; max-width:78ch; }}
.method h3 {{ color:var(--ink); font-size:15px; margin:0 0 8px; }}
.method ol {{ padding-left:20px; }} .method li {{ margin:4px 0; }}
.disclaimer {{ margin-top:14px; font-size:12.5px; border-left:3px solid var(--dn); padding-left:12px; }}
a {{ color:var(--accent); }}
@media (max-width:640px) {{ .masthead h1 {{ font-size:23px; }} }}
</style>
<div class="wrap">
<header class="masthead">
  <h1>VCP 分級軌跡 <em>{rev}</em></h1>
  <span class="meta">追蹤 {n} 次更新（最多保留最近 10 次）｜產生 {stamp_txt}｜{esc(model)}</span>
</header>
<p class="lede">把歷次掃描並排，看每檔股票的<b>分級變化軌跡</b>。<b>線上</b>＝目前列於觀察名單（A／E／B 級）；
<b>線下</b>＝目前不符合進場條件，其中「曾入選後跌出」是重點覆盤對象——若基底重新收緊，往往是下一輪 A 級的來源。</p>
<div class="legend">
  <span class="lg tA"><b>A</b> VCP 緊縮待突破</span>
  <span class="lg tE"><b>E</b> 已突破延伸中</span>
  <span class="lg tB"><b>B</b> 上升結構</span>
  <span class="lg tC"><b>C</b> 基底修復中（線下）</span>
  <span class="lg tD"><b>D</b> 趨勢偏弱（線下）</span>
</div>

<h2>各期掃描概況<span class="rule"></span></h2>
<div class="tblwrap"><table>
<thead><tr><th>版本</th><th>數據日期</th><th class="num">A</th><th class="num">E</th>
<th class="num">B</th><th class="num">C</th><th class="num">D</th><th class="num">合計</th></tr></thead>
<tbody>{summary_rows}</tbody></table></div>

<h2>▲ 線上｜目前觀察名單 <span class="n">{len(watch)} 檔</span><span class="rule"></span></h2>
<p class="sec-note">依目前級別與分數排序。每格顯示該期級別與 VCP 評分（0–100）。</p>
{table(watch)}

<div class="divider"><hr><span>以下為線下</span><hr></div>

<h2>▼ 線下｜曾入選後跌出 <span class="n">{len(dropped)} 檔</span><span class="rule"></span></h2>
<p class="sec-note">這些股票在先前掃描中曾列於 A／E／B，目前已跌出觀察名單。持續留意基底是否重新收緊。</p>
{table(dropped)}

<h2>▽ 線下｜未曾入選 <span class="n">{len(never)} 檔</span><span class="rule"></span></h2>
<p class="sec-note">掃描期間從未達到 A／E／B 級。括號內為歷期軌跡。</p>
<div class="dwrap">{never_chips}</div>

<footer class="method">
<h3>讀表方式</h3>
<ol>
<li><b>變化欄</b>比較最近兩次有數據的掃描：▲ 升級、▼ 降級、＝ 持平。</li>
<li>連續維持 A 級且分數上升者，基底最扎實；A→B→A 來回擺盪多因單日急漲跌，需開圖確認。</li>
<li>「曾入選後跌出」若在下一期回到 A／B，通常代表洗盤後再度收緊——VCP 的典型行為。</li>
<li>點代號開 TradingView 圖確認低點墊高與上緣壓力線。</li>
</ol>
<p>資料來源：<a href="https://bigdata.com" target="_blank" rel="noopener">Bigdata.com</a> 與網路搜尋報價；圖表連結：TradingView。</p>
<p class="disclaimer">本表為技術面選股輔助工具，非投資建議。分級由量化規則產生，形態最終以圖表確認為準。</p>
</footer>
</div>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="R3")
    ap.add_argument("--model", default="Opus5;high")
    ap.add_argument("--updates", type=int, default=10)
    args = ap.parse_args()

    snaps = load_snapshots(args.updates)
    if not snaps:
        raise SystemExit("no scan_R*.json snapshots found")
    track = build(snaps)

    now_hkt = datetime.now(timezone.utc) + timedelta(hours=8)
    stamp = now_hkt.strftime("%m.%d_%H.%M")
    stamp_txt = now_hkt.strftime("%Y.%m.%d %H:%M") + " HKT"
    base = f"VCP watchlist (Github)_{args.rev} ({args.model})_({stamp})_history"

    open(f"{base}.md", "w").write(render_md(snaps, track, args.rev, args.model, stamp_txt))
    open(f"{base}.html", "w").write(render_html(snaps, track, args.rev, args.model, stamp_txt))
    print(f"{base}.md")
    print(f"{base}.html")
    print(f"tracked {len(snaps)} updates: " +
          ", ".join(f"{r}({d})" for r, d, _, _ in snaps))


if __name__ == "__main__":
    main()

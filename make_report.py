#!/usr/bin/env python3
"""Generate the VCP watchlist report (Markdown + CSV) from a scan JSON file.

Usage:
    python make_report.py scan.json [--rev R0] [--model "Fable5;ultracode"]

The scan JSON is produced by the AI-universe scan workflow and has keys:
    market: str, rows: [...], notes: [...], failed: [...], discovered: [...]
Each row carries price/MA/52-week stats plus a category and score.
Every ticker is hyperlinked to its TradingView chart:
https://www.tradingview.com/chart/?symbol=<exchange>:<symbol>
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone

from exchanges import missing, tv_url

CATS = {
    "A_VCP待突破": ("A 級｜VCP 緊縮・等待突破", "趨勢模板通過、距 52 週高點 ≤10%、近 1 個月波動收斂（±7% 內）——最接近 Minervini VCP 買點的一批。"),
    "E_突破延伸中": ("E 級｜已突破・延伸中", "已貼著 52 週新高且近 1 個月大漲——突破已發動，勿追高，等回測樞紐區或新的緊縮再進場。"),
    "B_上升結構": ("B 級｜上升結構（一底高於一底 / 上升三角形候選）", "站上 50/200 日線、距高點 ≤20%、3 個月動能為正——結構偏多但基底未完全收緊，開圖確認低點是否墊高、上緣是否走平。"),
    "C_基底修復中": ("C 級｜基底修復中（觀察）", "仍在 200 日線上方但距高點較深，基底右側尚未完成。"),
    "D_趨勢弱": ("D 級｜趨勢偏弱（暫不列入）", "跌破主要均線或距高點過深，暫不符合進場條件。"),
}
CAT_ORDER = ["A_VCP待突破", "E_突破延伸中", "B_上升結構", "C_基底修復中", "D_趨勢弱"]


def link(t: str) -> str:
    return f"[{t}]({tv_url(t)})"


def f1(x, suffix="") -> str:
    return "" if x is None else f"{x:+.1f}{suffix}" if isinstance(x, (int, float)) else str(x)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_json")
    ap.add_argument("--rev", default="R0")
    ap.add_argument("--model", default="Fable5;ultracode")
    ap.add_argument("--out-prefix", default=None)
    args = ap.parse_args()

    with open(args.scan_json) as fh:
        scan = json.load(fh)

    now_utc = datetime.now(timezone.utc)
    now_hkt = now_utc + timedelta(hours=8)
    stamp = now_hkt.strftime("%m.%d_%H.%M")
    base = args.out_prefix or f"VCP watchlist (Github)_{args.rev} ({args.model})_({stamp})"

    rows = scan.get("rows", [])
    notes = {n["ticker"]: n for n in scan.get("notes", [])}

    unmapped = missing(r["ticker"] for r in rows)
    if unmapped:
        print(f"WARNING: no exchange mapping for {', '.join(unmapped)} "
              "— links fall back to bare symbol")

    lines = [
        f"# VCP Watchlist (GitHub) {args.rev}",
        "",
        f"**產生時間：** {now_hkt.strftime('%Y.%m.%d %H:%M')} HKT（{now_utc.strftime('%H:%M')} UTC）｜"
        f"**模型：** {args.model}｜**版本：** {args.rev}",
        "",
        f"**資料基準：** 美股 {rows[0].get('as_of', '')[:10] if rows else ''} 收盤（Bigdata.com 報價：現價、52 週高低、50/200 日均線、多期漲跌幅、量能）。"
        "每檔代號都連結到 TradingView 互動圖，點開即可確認契約形態細節。",
        "",
        "> 本表為選股輔助工具，非投資建議。形態最終仍以圖表確認為準。",
        "",
    ]

    if scan.get("market"):
        lines += ["## 市場背景", "", scan["market"], ""]

    by_cat: dict[str, list[dict]] = {c: [] for c in CAT_ORDER}
    for r in rows:
        by_cat.setdefault(r.get("category", "D_趨勢弱"), []).append(r)

    for cat in CAT_ORDER:
        cat_rows = sorted(by_cat.get(cat, []), key=lambda r: -r.get("score", 0))
        if not cat_rows:
            continue
        title, desc = CATS[cat]
        lines += [f"## {title}", "", desc, ""]
        if cat == "D_趨勢弱":
            lines.append("、".join(f"{link(r['ticker'])}（距高 -{r['off_high_pct']:.0f}%）" for r in cat_rows))
            lines.append("")
            continue
        lines.append("| 代號 | 名稱 | 收盤 | 樞紐(52W高) | 距樞紐 | 1月 | 3月 | 6月 | 1年 | 量比 | 分數 | 備註 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in cat_rows:
            t = r["ticker"]
            pivot = r.get("year_high") or 0
            price = r.get("price") or 0
            to_pivot = (pivot - price) / price * 100 if price else 0
            note = notes.get(t, {}).get("note", "")
            ed = notes.get(t, {}).get("earnings_date", "")
            if ed:
                note = f"{note} 財報:{ed}".strip()
            lines.append(
                f"| {link(t)} | {r.get('name', '')[:24]} | {price:.2f} | {pivot:.2f} | {to_pivot:+.1f}% "
                f"| {f1(r.get('chg_1m'), '%')} | {f1(r.get('chg_3m'), '%')} | {f1(r.get('chg_6m'), '%')} "
                f"| {f1(r.get('chg_1y'), '%')} | {r.get('vol_ratio', '')} | {r.get('score', '')} | {note} |"
            )
        lines.append("")

    if scan.get("failed"):
        lines += ["### 未能取得資料",
                  "、".join(f"{f['ticker']}（{f['error']}）" for f in scan["failed"]), ""]

    lines += [
        "## 篩選方法",
        "",
        "1. **趨勢模板**：股價站上 50 日與 200 日均線、50MA > 200MA、高於 52 週低點 ≥30%、距 52 週高點 ≤25%。",
        "2. **緊縮度**：近 1 個月漲跌幅收斂在 ±7% 以內且貼近高點 → 視為基底右側收緊（VCP / 平台整理特徵）。",
        "3. **量能**：現量低於 50 日均量 → 量縮（VCP 突破前的典型現象）。",
        "4. **動能**：6 個月 / 1 年漲幅確認主升趨勢仍在。",
        "5. 「一底高於一底」與「上升三角形」需開圖確認——B 級為結構候選，請點代號開 TradingView 圖驗證低點墊高與上緣壓力線。",
        "",
        "**分數**（0–100）：均線結構 30 分＋距樞紐 15 分＋月線緊縮 15 分＋中長期動能 20 分＋量縮 10 分＋貼緊樞紐加成 5 分。",
        "",
        "_資料來源：[Bigdata.com](https://bigdata.com) 即時報價與價格統計；新聞驗證：網路搜尋。非投資建議。_",
        "",
    ]

    md_path = f"{base}.md"
    with open(md_path, "w") as fh:
        fh.write("\n".join(lines))

    csv_path = f"{base}.csv"
    if rows:
        cols = ["ticker", "name", "category", "score", "price", "year_high", "year_low",
                "ma50", "ma200", "off_high_pct", "above_low_pct", "chg_5d", "chg_1m",
                "chg_3m", "chg_6m", "chg_1y", "vol_ratio", "as_of"]
        with open(csv_path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in sorted(rows, key=lambda r: -r.get("score", 0)):
                w.writerow(r)

    print(md_path)
    print(csv_path)


if __name__ == "__main__":
    main()

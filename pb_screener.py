#!/usr/bin/env python3
"""Pre-breakout (VCP-style) all-US-market screener.

Screens EVERY US-listed stock (NASDAQ / NYSE / AMEX) for pre-breakout
setups — uptrend, within ~10% of the 52-week high, tight 1-month range,
volume dry-up — and emits scan rows in the same schema the report
generators (make_report.py / make_html.py) consume.

Price history is reconstructed from the nightly snapshots of the public
dataset repo rreichel3/US-Stock-Symbols: each git commit archives the
official NASDAQ screener dump (last close, volume, market cap, sector)
for every US ticker, so the commit history IS a daily close series.

    python pb_screener.py --out scan_rows.json
    python pb_screener.py --dense-since 2026-05-25 --weekly-step 5

Steps:
  1. List ~1 year of commits of the dataset repo (blobless shallow git clone).
  2. Fetch nasdaq/nyse/amex *_full_tickers.json at daily commits for the
     recent window and weekly commits before that (raw.githubusercontent.com).
  3. Rebuild per-ticker close/volume series on a NYSE trading-day calendar
     (forward-filled), with split/reverse-split back-adjustment: an
     overnight gap is treated as a split only if the ratio is within 1.5%
     of a simple ratio AND the pre-gap price makes that ratio plausible
     (forward splits on stocks >= $60, reverse splits on stocks <= $15).
     Ticker renames and irregular ratios (spin-offs, 1:3 / 1:4 reverses)
     still need manual review — see scan_PB-R0's data_note.
  4. Liquidity filter: close >= $10, market cap >= $500M, 50-day average
     dollar volume >= $5M, >= 1 year of history; names that look like
     warrants/units/preferreds/CEFs are dropped.
  5. Trend template, tier assignment and scoring identical to the VCP
     watchlist series (A/E/B/C/D), plus a 1-month close-range floor of
     2.5% on A-tier to reject merger-arb "fake tightness".

The output rows still need news verification (pending acquisitions,
closed-end funds, unconfirmed splits) before publication.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

REPO = "rreichel3/US-Stock-Symbols"
EXCHANGES = ["nasdaq", "nyse", "amex"]
HOLIDAYS = {"2025-09-01", "2025-11-27", "2025-12-25", "2026-01-01", "2026-01-19",
            "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03"}
BAD_NAME = re.compile(r"Warrant|Right(s)? |Unit(s)?(,| )|Preferred|Depositary|% "
                      r"|Notes due|Subordinated|Debenture|ETF|Closed End Fund", re.I)
FWD_SPLITS = [2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 50]
REV_SPLITS = [1 / n for n in (2, 3, 4, 5, 8, 10, 15, 20)]


def http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "pb-screener"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def trading_days(d0: date, d1: date) -> list[str]:
    days, d = [], d0
    while d <= d1:
        if d.weekday() < 5 and d.isoformat() not in HOLIDAYS:
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def list_snapshots(since: date) -> list[tuple[str, str]]:
    """(sha, trading-date) pairs, newest first, one per trading date.

    Uses a blobless shallow clone: commit metadata only, no file contents.
    """
    tmp = tempfile.mkdtemp(prefix="pb-snap-")
    subprocess.run(["git", "clone", "--quiet", "--filter=blob:none",
                    f"--shallow-since={since.isoformat()}",
                    f"https://github.com/{REPO}", tmp], check=True)
    log = subprocess.run(["git", "-C", tmp, "log", "--format=%H %cI"],
                         check=True, capture_output=True, text=True).stdout
    out = []
    for line in log.strip().splitlines():
        sha, iso = line.split()
        dd = date.fromisoformat(iso[:10]) - timedelta(days=1)  # 00:15 UTC commit carries prior close
        while dd.weekday() >= 5:
            dd -= timedelta(days=1)
        out.append((sha, dd.isoformat()))
    seen, uniq = set(), []
    for sha, dd in out:
        if dd not in seen:
            seen.add(dd)
            uniq.append((sha, dd))
    return uniq


def fetch_snapshot(sha: str, ex: str) -> dict[str, tuple[float, int]]:
    url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{ex}/{ex}_full_tickers.json"
    rows = http_json(url)
    out = {}
    for r in rows:
        sym = (r.get("symbol") or "").strip()
        try:
            p = float(r["lastsale"].replace("$", "").replace(",", ""))
            v = int(r.get("volume") or 0)
        except (KeyError, ValueError, AttributeError):
            continue
        if sym and p:
            out[sym] = (p, v)
    return out


def detect_splits(pts: list[tuple[int, float, int]]) -> list[tuple[int, float]]:
    adjs = []
    for i in range(1, len(pts)):
        a, b = pts[i - 1][1], pts[i][1]
        if not a or not b:
            continue
        r = a / b
        if r > 1.8 and a >= 60:
            best = min(FWD_SPLITS, key=lambda x: abs(r / x - 1))
            if abs(r / best - 1) <= 0.015:
                adjs.append((pts[i][0], best))
        elif r < 0.56 and a <= 15:
            best = min(REV_SPLITS, key=lambda x: abs(r / x - 1))
            if abs(r / best - 1) <= 0.015:
                adjs.append((pts[i][0], best))
    return adjs


def analyze(t: str, pts, cal, meta) -> dict | None:
    adjs = detect_splits(pts)
    for cut, f in adjs:
        pts = [(i, p / f if i < cut else p, int(v * f) if i < cut else v) for i, p, v in pts]
    px: list[float | None] = [None] * len(cal)
    vol: list[int | None] = [None] * len(cal)
    for i, p, v in pts:
        px[i], vol[i] = p, v
    last = None
    for i in range(len(cal)):
        if px[i] is None:
            px[i] = last
        else:
            last = px[i]
    c = px[-1]
    if c is None or c < 10 or px[0] is None or meta["mktcap"] < 5e8:
        return None
    dense_vol = [v for v in vol[-62:] if v is not None]
    if len(dense_vol) < 30:
        return None
    v50 = sum(dense_vol[-50:]) / len(dense_vol[-50:])
    v10 = sum(dense_vol[-10:]) / len(dense_vol[-10:])
    if v50 * c < 5e6:
        return None
    valid = [p for p in px if p is not None]
    if len(valid) < 200:
        return None

    hi52, lo52 = max(valid), min(valid)
    ma50 = sum(px[-50:]) / 50
    ma200 = sum(px[-200:]) / 200
    ma200_prev = sum(px[-222:-22]) / 200
    off_high = (hi52 - c) / hi52 * 100
    above_low = (c - lo52) / lo52 * 100

    def chg(n):
        if len(px) <= n or px[-1 - n] is None:
            return None
        return round((px[-1] / px[-1 - n] - 1) * 100, 1)

    c1m, c3m = chg(21), chg(63)
    vol_ratio = round(v10 / v50, 2) if v50 > 0 else None
    last21 = px[-21:]
    rng1m = (max(last21) - min(last21)) / (sum(last21) / 21) * 100

    above50, above200 = c > ma50, c > ma200
    ma_ok, rising = ma50 > ma200, ma200 > ma200_prev
    trend = above50 and above200 and ma_ok and rising and above_low >= 30 and off_high <= 25
    if trend and off_high <= 1.5 and (c1m or 0) >= 10:
        catg = "E_突破延伸中"
    elif trend and off_high <= 10.5 and c1m is not None and abs(c1m) <= 7 and rng1m >= 2.5:
        catg = "A_VCP待突破"
    elif above50 and above200 and ma_ok and off_high <= 20 and (c3m or 0) > 0:
        catg = "B_上升結構"
    elif above200 and off_high <= 40:
        catg = "C_基底修復中"
    else:
        catg = "D_趨勢弱"

    score = 10 * above50 + 10 * above200 + 10 * ma_ok
    score += 15 * max(0, 1 - off_high / 25)
    if c1m is not None:
        score += 15 * max(0, 1 - abs(c1m) / 10)
    score += 10 * min(1, max(0, (chg(126) or 0) / 40)) + 10 * min(1, max(0, (chg(251) or 0) / 60))
    if vol_ratio is not None and vol_ratio < 1:
        score += 10 * min(1, (1 - vol_ratio) / 0.5)
    score += 5 * max(0, 1 - off_high / 3)

    return {"ticker": t, "name": meta["name"][:40], "price": c,
            "year_high": round(hi52, 2), "year_low": round(lo52, 2),
            "ma50": round(ma50, 2), "ma200": round(ma200, 2), "ma_proxy": True,
            "chg_5d": chg(5), "chg_1m": c1m, "chg_3m": c3m,
            "chg_6m": chg(126), "chg_1y": chg(251),
            "volume": dense_vol[-1], "avg_volume": int(v50), "as_of": cal[-1],
            "off_high_pct": round(off_high, 1), "above_low_pct": round(above_low, 1),
            "above_ma50": above50, "above_ma200": above200, "ma50_gt_ma200": ma_ok,
            "vol_ratio": vol_ratio, "score": round(score, 1), "category": catg,
            "range_1m_pct": round(rng1m, 1), "sector": meta["sector"],
            "industry": meta["industry"], "exchange": meta["exchange"],
            "split_adj": bool(adjs)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-breakout all-US-market screener")
    ap.add_argument("--dense-since", default=None,
                    help="daily granularity from this ISO date (default: ~last 90 days)")
    ap.add_argument("--weekly-step", type=int, default=5,
                    help="take every Nth older snapshot (default 5 ~= weekly)")
    ap.add_argument("--out", default="pb_scan_rows.json")
    args = ap.parse_args()

    today = date.today()
    since = today - timedelta(days=385)
    snaps = list_snapshots(since)
    if not snaps:
        print("no snapshots found", file=sys.stderr)
        return 1
    dense_since = args.dense_since or (today - timedelta(days=90)).isoformat()
    chosen = [s for s in snaps if s[1] >= dense_since]
    chosen += [s for s in snaps if s[1] < dense_since][::args.weekly_step]
    print(f"{len(snaps)} snapshots; fetching {len(chosen)} ({len(chosen) * 3} files)...")

    series: dict[str, dict[str, tuple[float, int]]] = {}
    jobs = [(sha, dd, ex) for sha, dd in chosen for ex in EXCHANGES]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for (sha, dd, ex), snap in zip(jobs, pool.map(lambda j: fetch_snapshot(j[0], j[2]), jobs)):
            series.setdefault(dd, {}).update(snap)

    meta = {}
    head = snaps[0][0]
    for ex in EXCHANGES:
        for r in http_json(f"https://raw.githubusercontent.com/{REPO}/{head}/{ex}/{ex}_full_tickers.json"):
            sym = (r.get("symbol") or "").strip()
            try:
                mc = float(r.get("marketCap") or 0)
            except ValueError:
                mc = 0.0
            meta[sym] = {"name": (r.get("name") or "").strip(), "mktcap": mc,
                         "sector": r.get("sector", ""), "industry": r.get("industry", ""),
                         "exchange": ex}

    cal = trading_days(min(date.fromisoformat(d) for d in series),
                       max(date.fromisoformat(d) for d in series))
    idx = {c: i for i, c in enumerate(cal)}
    tickers = sorted({t for m in series.values() for t in m})
    rows = []
    for t in tickers:
        m = meta.get(t)
        if not m or BAD_NAME.search(m["name"]) or any(ch in t for ch in "^/."):
            continue
        pts = [(idx[dd], series[dd][t][0], series[dd][t][1])
               for dd in sorted(series) if t in series[dd] and dd in idx]
        if len(pts) < 40:
            continue
        row = analyze(t, pts, cal, m)
        if row:
            rows.append(row)

    with open(args.out, "w") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    from collections import Counter
    print(f"screened {len(rows)} tickers -> {args.out}")
    print(Counter(r["category"] for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

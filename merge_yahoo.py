#!/usr/bin/env python3
"""Merge the Yahoo daily bars (data/yahoo/eod_*.csv.gz, pulled on the GitHub
Actions runner — the container cannot reach Yahoo) into the official
Nasdaq-screener series (scratchpad/work10/series4.pkl, through 2026-09-03).

Yahoo's `close` is split-adjusted (not dividend-adjusted); the screener series
is as-traded. So, per symbol:
  1. the day-by-day ratio Yahoo/official reveals any split in or before the
     window as a clean ratio (4:1 -> 0.25, 3:2 -> 0.667, 1:3 -> 3); the official
     window is moved onto Yahoo's split-adjusted basis (closes x r, volumes / r);
  2. every common (symbol, day) close is then cross-checked (median, >0.5%);
  3. the 2026-09-04 close/volume (the upstream mirror has not published a 9/4
     close) is appended from Yahoo;
  4. on days the official series only *recovered* (price_change of a later
     snapshot, volume approximated) the volume is replaced by Yahoo's real one;
  5. tickers the official series never had (ADRs / gap series) get a full
     in-window series from Yahoo;
  6. the long Yahoo history (from 2025-09-01) gives a real MA200 / MA50 and
     52-week high/low per symbol on the same basis.

Writes scratchpad/work10/series5.pkl (series4 schema + src / long / split_adj)
and yahoo_crosscheck_R14.json.
"""
import csv, glob, gzip, json, pickle, statistics, sys
from collections import defaultdict
from datetime import date, timedelta

SCRATCH = "/tmp/claude-0/-home-user-VCP-watchlist/ff996f21-17e8-5ead-916f-161009f304a9/scratchpad/work10"
NEW_DAY = "2026-09-04"
FILES = sorted(glob.glob("data/yahoo/eod_*.csv.gz"))
EXTRA = [f for f in sys.argv[1:] if f.endswith(".csv.gz")]   # optional stand-in files (lower priority)
if not FILES and not EXTRA:
    sys.exit("no data/yahoo/eod_*.csv.gz")
CLEAN = [2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 40, 50, 100, 1.5, 1.25, 4 / 3, 2.5]
CLEAN = sorted(CLEAN + [1 / x for x in CLEAN])

d = pickle.load(open(f"{SCRATCH}/series4.pkl", "rb"))
CAL, SER, FILLED = d["cal"], d["series"], d.get("filled", {})
assert CAL[-1] == "2026-09-03", CAL[-1]

Y = {}
for f in EXTRA + FILES:                      # repo files win over stand-ins
    with gzip.open(f, "rt") as fh:
        for r in csv.DictReader(fh):
            try:
                Y.setdefault(r["symbol"], {})[r["date"]] = (float(r["close"]), float(r["volume"] or 0))
            except ValueError:
                pass
    print(f"{f}: cumulative {len(Y)} symbols")


def clean_ratio(r):
    for c in CLEAN:
        if abs(r / c - 1) < 0.006:
            return c
    return None


cal = CAL + [NEW_DAY]
series, src, split_adj = {}, {}, {}
diffs, by_day, bad = [], defaultdict(list), defaultdict(int)
n_ext = n_vol = 0
filled_days = {k: set(v) for k, v in FILLED.items()}
for s, (fi, cs, vs, ff) in SER.items():
    cs, vs = list(cs), list(vs)
    yb = Y.get(s)
    if yb:
        # 1. basis: Yahoo/official ratio per day. A split, spin-off or capital
        # return shows as a level shift that holds for a run of days (a clean
        # ratio for a split); a one-off outlier is a genuine mismatch, left as is.
        rr = []
        for i, c in enumerate(cs):
            dd = CAL[fi + i]
            rr.append(yb[dd][0] / c if (dd in yb and c) else None)
        fac = [1.0] * len(cs)
        i = 0
        while i < len(cs):
            r = rr[i]
            if r is None or abs(r - 1) <= 0.015:
                i += 1; continue
            j = i
            while j + 1 < len(cs) and rr[j + 1] is not None and abs(rr[j + 1] / r - 1) < 0.01:
                j += 1
            if j - i + 1 >= 3:                       # a stable level shift
                lvl = statistics.median(rr[i:j + 1])
                lvl = clean_ratio(lvl) or round(lvl, 6)
                for k in range(i, j + 1):
                    fac[k] = lvl
            i = j + 1
        if any(f != 1.0 for f in fac):
            cs = [c * f for c, f in zip(cs, fac)]
            vs = [v / f for v, f in zip(vs, fac)]
            split_adj[s] = round(fac[0], 6) if fac[0] != 1.0 else round(max(fac, key=lambda x: abs(x - 1)), 6)
        # 2. cross-check on the common basis
        for i, c in enumerate(cs):
            dd = CAL[fi + i]
            if dd in yb and c:
                dv = abs(yb[dd][0] / c - 1) * 100
                diffs.append(dv); by_day[dd].append(dv)
                if dv > 0.5:
                    bad[s] += 1
        # 4. real full-day volume for recovered days
        for k, syms in filled_days.items():
            if s in syms and k in yb and k in CAL:
                j = CAL.index(k) - fi
                if 0 <= j < len(vs) and yb[k][1] > 0:
                    vs[j] = yb[k][1]; n_vol += 1
        # 3. extend to the new day
        if fi + len(cs) == len(CAL) and NEW_DAY in yb:
            cs.append(yb[NEW_DAY][0]); vs.append(yb[NEW_DAY][1])
            n_ext += 1; src[s] = "official+yahoo"
        else:
            src[s] = "official"
    else:
        src[s] = "official"
    series[s] = (fi, cs, vs, ff)

# days on which the official series disagrees with Yahoo for most symbols are the
# upstream mirror's missing-snapshot days that the extractor had to fill; take
# Yahoo's real close and volume there (the way the 10MA-watchlist build does)
day_n, day_bad = defaultdict(int), defaultdict(int)
for s, (fi, cs, vs, ff) in series.items():
    yb = Y.get(s)
    if not yb or src.get(s) != "official+yahoo":
        continue
    for i, c in enumerate(cs[:-1]):
        dd = cal[fi + i]
        if dd in yb and c:
            day_n[dd] += 1
            if abs(yb[dd][0] / c - 1) > 0.005:
                day_bad[dd] += 1
replaced_days = sorted(dd for dd in day_n if day_n[dd] >= 200 and day_bad[dd] / day_n[dd] > 0.5)
n_rep = 0
for s, (fi, cs, vs, ff) in series.items():
    yb = Y.get(s)
    if not yb or src.get(s) != "official+yahoo":
        continue
    for dd in replaced_days:
        j = cal.index(dd) - fi
        if 0 <= j < len(cs) and dd in yb and yb[dd][0] > 0:
            cs[j], vs[j] = yb[dd][0], yb[dd][1]; n_rep += 1
    series[s] = (fi, cs, vs, ff)
print(f"broken official days replaced from Yahoo: {replaced_days} ({n_rep} symbol-days)")
# recompute the cross-check on the repaired series
diffs, by_day, bad = [], defaultdict(list), defaultdict(int)
for s, (fi, cs, vs, ff) in series.items():
    yb = Y.get(s)
    if not yb or src.get(s) != "official+yahoo":
        continue
    for i, c in enumerate(cs[:-1]):
        dd = cal[fi + i]
        if dd in yb and c:
            dv = abs(yb[dd][0] / c - 1) * 100
            diffs.append(dv); by_day[dd].append(dv)
            if dv > 0.5:
                bad[s] += 1

xc = {"replaced_days": replaced_days, "n_symbols": len({s for s in SER if s in Y}), "n_pairs": len(diffs),
      "median_pct": round(statistics.median(diffs), 4) if diffs else None,
      "gt_0_5pct": sum(1 for x in diffs if x > 0.5),
      "per_day": {dd: {"n": len(v), "median_pct": round(statistics.median(v), 4),
                       "gt_0_5pct": sum(1 for x in v if x > 0.5)}
                  for dd, v in by_day.items() if dd >= "2026-08-27"},
      "worst": sorted(bad.items(), key=lambda kv: -kv[1])[:40],
      "split_adj": dict(sorted(split_adj.items()))}
print(f"cross-check: {xc['n_symbols']} symbols, {xc['n_pairs']} pairs, median {xc['median_pct']}%, >0.5%: {xc['gt_0_5pct']}")
print("  per day:", {k: xc["per_day"][k] for k in sorted(xc["per_day"])})
print("  symbols with >0.5% days:", xc["worst"][:15])
print(f"  splits detected (official window moved onto Yahoo basis): {len(split_adj)} {sorted(split_adj.items())[:20]}")
print(f"extended to {NEW_DAY}: {n_ext} symbols | recovered-day volumes replaced: {n_vol}")

# 5. Yahoo-only full series
n_y = 0
for s, yb in Y.items():
    cur = series.get(s)
    if cur and cur[0] + len(cur[1]) == len(cal):
        continue
    if all(dd in yb for dd in cal):
        series[s] = (0, [yb[dd][0] for dd in cal], [yb[dd][1] for dd in cal], 0)
        src[s] = "yahoo"; n_y += 1
print(f"Yahoo-only full series: {n_y}")

# 6. long-history stats (Yahoo close is already on the split-adjusted basis)
long = {}
cut = (date.fromisoformat(cal[-1]) - timedelta(days=365)).isoformat()
for s, yb in Y.items():
    days = sorted(yb)
    closes = [yb[dd][0] for dd in days]
    yr = [c for dd, c in zip(days, closes) if dd > cut]
    if not yr:
        continue
    long[s] = {"n": len(closes), "first_day": days[0], "last_day": days[-1],
               "ma200": round(sum(closes[-200:]) / 200, 4) if len(closes) >= 200 else None,
               "ma50": round(sum(closes[-50:]) / 50, 4) if len(closes) >= 50 else None,
               "hi52": round(max(yr), 4), "lo52": round(min(yr), 4), "days52": len(yr),
               "chg_6m": round((closes[-1] / closes[-127] - 1) * 100, 1) if len(closes) >= 127 else None,
               "chg_1y": round((closes[-1] / closes[-253] - 1) * 100, 1) if len(closes) >= 253 else None}
print(f"long-history stats: {len(long)} symbols, {sum(1 for v in long.values() if v['ma200'])} with >=200 bars")

pickle.dump({"cal": cal, "series": series, "filled": FILLED, "src": src, "long": long, "split_adj": split_adj},
            open(f"{SCRATCH}/series5.pkl", "wb"))
json.dump(xc, open("yahoo_crosscheck_R14.json", "w"), ensure_ascii=False, indent=1)
full = sum(1 for s, (fi, cs, vs, ff) in series.items() if fi + len(cs) == len(cal))
print(f"series5: calendar {cal[0]} -> {cal[-1]} ({len(cal)} days), {len(series)} symbols, {full} complete to {NEW_DAY}")

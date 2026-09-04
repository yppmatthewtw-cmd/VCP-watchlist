#!/usr/bin/env python3
"""R12 snapshot refresh: official 2026-09-02 closes for the whole universe, with
the classification fixes from the 2026-09-02 critical review.

Sources: cert7_2026-09-02.json (official series, 241 tickers) + the 9/1 HEAD
tickers.csv (33 more, mostly foreign issuers). Every row gets the official
close, official 21/63-day momentum, 21-day close range, MA50, market cap and
sector, its 52-week levels lifted to any higher/lower official close in the
series (levels are unified per ticker across the three lists), then is
reclassified with the revised rules:
  VCP  - real MA50 used whenever available (proxy only for the missing MA200);
         a 21-day gain > 15% is an extension (E), never a base (A/B/C);
         A also requires a 21-day close range <= 12%.
  Stage- Stage 3 is tested before 1->2; momentum = 3M > 0 and 1M > -8;
         2A needs 6M in [12,60], not extended and 1M<=20; 2B needs (1Y>100 or
         6M>=40 or 1M>20) or a pullback inside an intact stage 2 (above the
         long-term MA, <=20% off high, 6M>=12); 1->2 capped at 25% off high.
         A missing 6M is filled from the official series' ~5-month span; a
         missing 1Y falls back to "up >150% off the 52-week low" as extension.
GPS is carried as GAP (Gap Inc.'s current ticker). RUSHB/RUSHA 3:2 split
(paid 2026-08-31) is applied to the pre-split levels and to the change deltas.

R16 -> R17, stage R9 -> R10, PB R9 -> R10. Old snapshots are kept untouched.
"""
import csv, io, json, pickle, subprocess
from collections import Counter, defaultdict

SCRATCH = "/tmp/claude-0/-home-user-VCP-watchlist/ff996f21-17e8-5ead-916f-161009f304a9/scratchpad/work10"
ZREPO = "/home/user/zyhe16/top-us-stock-tickers"
AS_OF = "2026-09-02"
ALIAS = {"GPS": "GAP"}
SPLIT_LEVELS = {"RUSHB": ("3:2 2026-08-31", 2 / 3), "RUSHA": ("3:2 2026-08-31", 2 / 3)}

CERT = json.load(open("cert7_2026-09-02.json"))
d = pickle.load(open(f"{SCRATCH}/series4adj.pkl", "rb"))
CAL, SER = d["cal"], d["series"]

blob = subprocess.run(["git", "-C", ZREPO, "show", "HEAD:data/v2/tickers.csv"],
                      capture_output=True, text=True).stdout
META = {}
for row in csv.DictReader(io.StringIO(blob.lstrip("﻿"))):
    s = row["symbol"].strip()
    try:
        META[s] = {"mcap": float(row["market_cap"] or 0), "sector": row["sector"].strip(),
                   "price": float(row["price"] or 0),
                   "pchg": float(row["percent_change"]) if row.get("percent_change") not in (None, "") else None}
    except ValueError:
        pass


def official(t):
    c = CERT.get(t)
    if c and c.get("official_close"):
        return c["official_close"], "series"
    m = META.get(t)
    if m and m["price"] > 0:
        return m["price"], "head"
    return None, None


def ma50_of(t):
    s = SER.get(t)
    if not s:
        return None
    fi, cs, vs, ff = s
    if fi + len(cs) != len(CAL) or len(cs) < 50:
        return None
    return round(sum(cs[-50:]) / 50, 2)


def apply_official(r):
    r = dict(r)
    r["ticker"] = ALIAS.get(r["ticker"], r["ticker"])
    t = r["ticker"]
    split_f = 1.0
    if t in SPLIT_LEVELS and r.get("_split") != SPLIT_LEVELS[t][0]:
        tag, split_f = SPLIT_LEVELS[t]
        for k in ("year_high", "year_low", "ma200", "ma50"):
            if r.get(k):
                r[k] = round(r[k] * split_f, 2)
        r["_split"] = tag
    px, src = official(t)
    if px is None:
        r["stale"] = True
        return r, False, None
    m = META.get(t, {})
    old = (r.get("price") or 0) * split_f          # compare like with like across a split
    delta = (px / old - 1) * 100 if old else 0
    flag = (t, round(delta, 1), src) if old and abs(delta) > 5 else None
    r["price"] = px
    c = CERT.get(t, {})
    # 52-week levels: lift to any official close in the series beyond them
    yh = max(r.get("year_high") or 0, px, c.get("series_high") or 0)
    yl_cands = [v for v in (r.get("year_low"), px, c.get("series_low")) if v]
    r["year_high"], r["year_low"] = yh, min(yl_cands)
    for k, ck in (("chg_1m", "chg_21d"), ("chg_3m", "chg_63d")):
        if c.get(ck) is not None:
            r[k] = c[ck]
        elif r.get(k) is not None:
            r[k] = round(r[k] + delta, 1)
    for k in ("chg_6m", "chg_1y"):
        if r.get(k) is not None:
            r[k] = round(r[k] + delta, 1)
    if c.get("chg_5d") is not None:
        r["chg_5d"] = c["chg_5d"]
    elif r.get("chg_5d") is not None:
        r["chg_5d"] = round(r["chg_5d"] + delta, 2)
    if c.get("chg_1d") is not None:
        r["chg_1d"] = c["chg_1d"]
    elif m.get("pchg") is not None:
        r["chg_1d"] = m["pchg"]
    if c.get("range_1m_pct") is not None:
        r["range_1m_pct"] = c["range_1m_pct"]
    # 6-month momentum is missing on many rows (the original scans never had it).
    # The official series spans ~5 months, so use its full-span change instead of
    # leaving a gap that silently disqualifies the row from 2A/2B.
    if r.get("chg_6m") is None and c.get("chg_full_pct") is not None:
        r["chg_6m"] = c["chg_full_pct"]
        r["c6_src"] = f"official {c.get('full_days', 0)}d span"
    ma = ma50_of(t)
    if ma:
        r["ma50"] = ma
    if m.get("mcap"):
        r["mcap"] = m["mcap"]
    elif c.get("mcap"):
        r["mcap"] = c["mcap"]
    if not r.get("sector") and m.get("sector"):
        r["sector"] = m["sector"]
    if not r.get("name") and t == "GAP":
        r["name"] = "Gap Inc."
    for k in ("px_0902_intraday", "chg_0902_intraday"):
        r.pop(k, None)
    r["as_of"] = AS_OF
    r.pop("stale", None)
    r["_delta"] = round(delta, 2)
    return r, True, flag


# -- classifiers (revised per the 2026-09-02 review) ------------------------
def vcp_classify(r):
    p = r["price"]
    offHigh = (r["year_high"] - p) / r["year_high"] * 100
    aboveLow = (p - r["year_low"]) / r["year_low"] * 100 if r.get("year_low") else 0
    ma50, ma200 = r.get("ma50") or 0, r.get("ma200") or 0
    a50 = (p > ma50) if ma50 > 0 else None
    if ma200 > 0:
        a200 = p > ma200
        cross = (ma50 > ma200) if ma50 > 0 else a200
    else:
        # No 200-day available (the official series spans ~107 sessions). Proxy the
        # long-term trend with "above the 50-day and within 25% of the high"; the
        # >=30%-above-low template rule is scored separately, NOT used as the proxy.
        a200 = cross = (a50 and offHigh <= 25) if a50 is not None else (aboveLow >= 25 and offHigh <= 20)
    if a50 is None:
        a50 = a200
    trendOK = a50 and a200 and cross and aboveLow >= 30 and offHigh <= 25
    c1 = r.get("chg_1m") or 0
    c3 = r.get("chg_3m") if r.get("chg_3m") is not None else c1
    rng = r.get("range_1m_pct")
    tight = abs(c1) <= 7 and (rng is None or rng <= 12)
    extended = c1 > 15
    vr = r.get("vol_ratio", 1) or 1
    s = 10 * a200 + 10 * a50 + 5 * cross + 5 * (aboveLow >= 30)
    s += max(0, 15 * (1 - min(offHigh, 25) / 25)) + max(0, 15 * (1 - min(abs(c1), 15) / 15))
    s += min(10, max(0, r.get("chg_6m") or 0) / 5) + min(10, max(0, r.get("chg_1y") or 0) / 10)
    if vr < 0.95: s += 10
    if offHigh <= 5 and tight: s += 5
    if extended: cat = "E_突破延伸中"                        # a 21-day gain > 15% is never a base
    elif trendOK and offHigh <= 10 and tight: cat = "A_VCP待突破"
    elif offHigh <= 4 and c1 > 8: cat = "E_突破延伸中"
    elif trendOK and offHigh <= 20 and c3 > -5: cat = "B_上升結構"
    elif (a200 or aboveLow >= 20) and offHigh <= 30 and c1 > -10: cat = "C_基底修復中"
    else: cat = "D_趨勢弱"
    r.update(off_high_pct=round(offHigh, 1), above_low_pct=round(aboveLow, 1),
             above_ma50=bool(a50), above_ma200=bool(a200), ma50_gt_ma200=bool(cross),
             ma_proxy=bool(ma200 <= 0), score=round(min(s, 100), 1), category=cat)
    return r


def stage_classify(r):
    p, yh, yl = r["price"], r["year_high"], r.get("year_low") or 0
    offHigh = (yh - p) / yh * 100
    aboveLow = (p - yl) / yl * 100 if yl else 0
    c1, c3, c6, c1y = (r.get(k) for k in ("chg_1m", "chg_3m", "chg_6m", "chg_1y"))
    ma200 = r.get("ma200") or 0
    if ma200 > 0: up = p > ma200
    elif r.get("above_ma200") is not None: up = bool(r["above_ma200"])
    else: up = aboveLow >= 25 and offHigh <= 20
    known = c6 is not None
    # 1-year data is missing on ~30 rows; treat a very large advance off the
    # 52-week low as the extension signal in its place.
    extended = (c1y > 100) if c1y is not None else (aboveLow > 150)
    young = known and 12 <= c6 <= 60 and not extended and (c1 is None or c1 <= 20)
    fading = (c3 is not None and c3 < -12) or (c1 is not None and c1 < -8)
    mom = (c3 is not None and c3 > 0) and (c1 is None or c1 > -8)
    if extended and 15 < offHigh <= 45 and (fading or not mom): st = "3_做頭疑慮"
    elif up and offHigh <= 12 and young and not fading: st = "2A_初升段"
    elif up and offHigh <= 20 and known and (extended or c6 >= 40 or (c1 is not None and c1 > 20)) and not fading: st = "2B_主升段"
    elif up and offHigh <= 20 and known and c6 >= 12: st = "2B_主升段"       # pullback inside an intact stage 2
    elif up and offHigh <= 25 and mom: st = "1轉2_轉強觀察"
    else: st = "41_弱勢打底"
    dist = (p - ma200) / ma200 * 100 if ma200 > 0 else r.get("ma200_dist_pct")
    s = 25 * up + min(25, min(max(c6 or 0, 0), 50) / 2)
    s += max(0, 15 * (1 - min(max(c1y, 0), 150) / 150)) if c1y is not None else 7
    s += max(0, 20 * (1 - min(offHigh, 25) / 25))
    if aboveLow >= 25: s += 5
    if dist is not None and 0 < dist <= 15: s += 10
    elif dist is not None and 15 < dist <= 25: s += 5
    r.update(stage=st, off_high_pct=round(offHigh, 1), above_low_pct=round(aboveLow, 1),
             above_ma200=bool(up), score=round(min(s, 100), 1),
             ma200_dist_pct=round(dist, 1) if dist is not None else None)
    return r


JOBS = [("scan_R16_2026-09-02.json", "scan_R17_2026-09-03.json", "vcp"),
        ("scan_stage_R9_2026-09-02.json", "scan_stage_R10_2026-09-03.json", "stage"),
        ("scan_PB-R9_2026-09-02.json", "scan_PB-R10_2026-09-03.json", "pb")]

# pass 1: official prices + level lifting for every list
staged = []
for src, dst, mode in JOBS:
    scan = json.load(open(src))
    out, flags, n = [], [], 0
    for r in scan["rows"]:
        before = r.get("stage" if mode == "stage" else "category")
        r2, upd, flag = apply_official(r)
        r2["_before"] = before
        n += upd
        if flag: flags.append(flag)
        out.append(r2)
    staged.append((scan, dst, mode, out, n, flags))

# unify the 52-week levels per ticker across the three lists (one 距高 per ticker)
yh = defaultdict(float); yl = {}
for _, _, _, rows, _, _ in staged:
    for r in rows:
        t = r["ticker"]
        yh[t] = max(yh[t], r.get("year_high") or 0)
        if r.get("year_low"):
            yl[t] = min(yl.get(t, r["year_low"]), r["year_low"])

# pass 2: classify with the unified levels
for scan, dst, mode, rows, n, flags in staged:
    key = "stage" if mode == "stage" else "category"
    moved = []
    for r in rows:
        t = r["ticker"]
        if yh[t]: r["year_high"] = yh[t]
        if t in yl: r["year_low"] = yl[t]
        if "stale" in r:
            continue
        r = stage_classify(r) if mode == "stage" else vcp_classify(r)
        if r.get(key) != r["_before"]:
            moved.append((t, r["_before"], r[key]))
        r.pop("_before", None)
    for r in rows: r.pop("_before", None)
    scan.update(rows=rows)
    json.dump(scan, open(dst, "w"), ensure_ascii=False, indent=1)
    print(f"{dst}: {n}/{len(rows)} official | {dict(Counter(r.get(key) for r in rows))}")
    print(f"  >5% corrections: {len(flags)} | reclassified {len(moved)}: {moved[:10]}{' ...' if len(moved) > 10 else ''}")

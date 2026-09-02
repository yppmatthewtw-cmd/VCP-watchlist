#!/usr/bin/env python3
"""R3 snapshot refresh: replace the 8/28 web-search quotes with official closes.

Sources: cert7_2026-08-28.json (official_close from the zyhe16 daily-snapshot
series, 240 tickers) plus the HEAD tickers.csv price for tickers whose series
has gaps (33 more, mostly foreign ADRs). Every covered row gets the official
close, official chg_1m/chg_3m (21/63 trading days) where the series allows,
a recomputed MA50, and market cap / sector metadata, then is reclassified.
Only GPS keeps its prior quote (absent from the snapshot repo).

R12 -> R13, stage R5 -> R6, PB R5 -> R6. Old snapshots are kept untouched.
"""
import csv, io, json, pickle, subprocess
from collections import Counter

SCRATCH = "/tmp/claude-0/-home-user-VCP-watchlist/ff996f21-17e8-5ead-916f-161009f304a9/scratchpad/work10"
ZREPO = "/home/user/zyhe16/top-us-stock-tickers"

CERT = json.load(open("cert7_2026-08-28.json"))
d = pickle.load(open(f"{SCRATCH}/series2adj.pkl", "rb"))  # split-adjusted (see build_r3_data.py)
CAL, SER = d["cal"], d["series"]

blob = subprocess.run(["git", "-C", ZREPO, "show", "HEAD:data/v2/tickers.csv"],
                      capture_output=True, text=True).stdout
META = {}
for row in csv.DictReader(io.StringIO(blob.lstrip("﻿"))):
    s = row["symbol"].strip()
    try:
        META[s] = {"mcap": float(row["market_cap"] or 0), "sector": row["sector"].strip(),
                   "price": float(row["price"] or 0)}
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
    t = r["ticker"]
    r = dict(r)
    px, src = official(t)
    if px is None:
        r["stale"] = True
        return r, False, None
    old = r.get("price") or 0
    delta = (px / old - 1) * 100 if old else 0
    # The official snapshot always wins: every >5% divergence was adjudicated
    # against the series' neighbouring closes (the web quote was stale or bad
    # in each case — AAOI/APLD/AXTI carried 8/27 closes, UNM/OUST/UFPT were
    # known bad quotes, ARM/CCJ/IREN missed the Friday post-close selloff).
    flag = (t, round(delta, 1), src) if old and abs(delta) > 5 else None
    r["price"] = px
    r["year_high"] = max(r.get("year_high") or 0, px)
    r["year_low"] = min(r.get("year_low") or px, px)
    c = CERT.get(t, {})
    for k, ck in (("chg_1m", "chg_21d"), ("chg_3m", "chg_63d")):
        if c.get(ck) is not None:
            r[k] = c[ck]
        elif r.get(k) is not None:
            r[k] = round(r[k] + delta, 1)
    for k in ("chg_6m", "chg_1y"):
        if r.get(k) is not None:
            r[k] = round(r[k] + delta, 1)
    if r.get("chg_5d") is not None:
        r["chg_5d"] = round(r["chg_5d"] + delta, 2)
    ma = ma50_of(t)
    if ma:
        r["ma50"] = ma
    m = META.get(t, {})
    if m.get("mcap"):
        r["mcap"] = m["mcap"]
    elif c.get("mcap"):
        r["mcap"] = c["mcap"]
    if not r.get("sector") and m.get("sector"):
        r["sector"] = m["sector"]
    r["as_of"] = "2026-08-28"
    r.pop("stale", None)
    r["_delta"] = round(delta, 2)
    return r, True, flag


# -- classifiers (same rules as every earlier release) -----------------------
def vcp_classify(r, proxy):
    offHigh = (r["year_high"] - r["price"]) / r["year_high"] * 100
    aboveLow = (r["price"] - r["year_low"]) / r["year_low"] * 100 if r.get("year_low") else 0
    if proxy:
        trendOK = aboveLow >= 30 and offHigh <= 25
        a50 = a200 = cross = trendOK
    else:
        a50 = r.get("ma50", 0) > 0 and r["price"] > r["ma50"]
        a200 = r.get("ma200", 0) > 0 and r["price"] > r["ma200"]
        cross = r.get("ma50", 0) > r.get("ma200", 0)
        trendOK = a50 and a200 and cross and aboveLow >= 30 and offHigh <= 25
    c1 = r.get("chg_1m") or 0
    c3 = r.get("chg_3m") if r.get("chg_3m") is not None else c1
    tight = abs(c1) <= 7
    vr = r.get("vol_ratio", 1) or 1
    s = 10*a200 + 10*a50 + 5*cross + 5*(aboveLow >= 30)
    s += max(0, 15*(1 - min(offHigh, 25)/25)) + max(0, 15*(1 - min(abs(c1), 15)/15))
    s += min(10, max(0, r.get("chg_6m") or 0)/5) + min(10, max(0, r.get("chg_1y") or 0)/10)
    if vr < 0.95: s += 10
    if offHigh <= 5 and tight: s += 5
    if trendOK and offHigh <= 10 and tight: cat = "A_VCP待突破"
    elif offHigh <= 4 and c1 > 8: cat = "E_突破延伸中"
    elif trendOK and offHigh <= 20 and c3 > -5: cat = "B_上升結構"
    elif (a200 or proxy and aboveLow >= 20) and offHigh <= 30 and c1 > -10: cat = "C_基底修復中"
    else: cat = "D_趨勢弱"
    r.update(off_high_pct=round(offHigh, 1), above_low_pct=round(aboveLow, 1),
             above_ma50=bool(a50), above_ma200=bool(a200), ma50_gt_ma200=bool(cross),
             score=round(min(s, 100), 1), category=cat)
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
    young = c6 is not None and c6 >= 12 and (c1y is None or c1y <= 100)
    inferred = (c6 is None and c1y is not None and 10 <= c1y <= 100)
    extended = c1y is not None and c1y > 100
    fading = (c3 is not None and c3 < -12) or (c1 is not None and c1 < -8)
    mom = any(v is not None and v > 0 for v in (c3, c1, c6))
    if up and offHigh <= 12 and (young or inferred) and not fading: st = "2A_初升段"
    elif up and offHigh <= 20 and (extended or c6 is None or c6 >= 0) and not fading: st = "2B_主升段"
    elif up and offHigh <= 35 and mom: st = "1轉2_轉強觀察"
    elif (r.get("above_ma200") is True or up) and 12 < offHigh <= 40 and mom: st = "1轉2_轉強觀察"
    elif extended and 15 < offHigh <= 45 and (fading or not mom): st = "3_做頭疑慮"
    else: st = "41_弱勢打底"
    dist = r.get("ma200_dist_pct")
    if dist is None and ma200 > 0: dist = (p - ma200) / ma200 * 100
    s = 25 * up + min(25, max(0, c6 or 0) / 2)
    s += max(0, 15 * (1 - min(c1y, 150) / 150)) if c1y is not None else 7
    s += max(0, 20 * (1 - min(offHigh, 25) / 25))
    if aboveLow >= 25: s += 5
    if dist is not None and 0 < dist <= 15: s += 10
    elif dist is not None and 15 < dist <= 25: s += 5
    r.update(stage=st, off_high_pct=round(offHigh, 1), above_low_pct=round(aboveLow, 1),
             score=round(min(s, 100), 1),
             ma200_dist_pct=round(dist, 1) if dist is not None else None)
    return r


def process(src, dst, mode):
    scan = json.load(open(src))
    key = "stage" if mode == "stage" else "category"
    rows, rejects, moved = [], [], []
    n_upd = 0
    for r in scan["rows"]:
        before = r.get(key)
        r, upd, rej = apply_official(r)
        if rej:
            rejects.append(rej)
        n_upd += upd
        if upd:
            if mode == "stage":
                r = stage_classify(r)
            else:
                proxy = (bool(r.get("ma_proxy")) or (r.get("ma50", 0) or 0) <= 0) if mode == "vcp" \
                    else (r.get("ma50", 0) or 0) <= 0
                r = vcp_classify(r, proxy)
            if r.get(key) != before:
                moved.append((r["ticker"], before, r[key]))
        rows.append(r)
    scan.update(rows=rows)
    json.dump(scan, open(dst, "w"), ensure_ascii=False, indent=1)
    c = Counter(r[key] for r in rows)
    print(f"{dst}: {n_upd}/{len(rows)} official |", dict(c))
    if rejects:
        print("  >5% corrections (official applied):", rejects)
    if moved:
        print(f"  reclassified {len(moved)}:", moved[:14], "..." if len(moved) > 14 else "")
    return rows


if __name__ == "__main__":
    process("scan_R12_2026-08-29.json", "scan_R13_2026-08-30.json", "vcp")
    process("scan_stage_R5_2026-08-29.json", "scan_stage_R6_2026-08-30.json", "stage")
    process("scan_PB-R5_2026-08-29.json", "scan_PB-R6_2026-08-30.json", "pb")

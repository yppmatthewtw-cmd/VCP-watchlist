#!/usr/bin/env python3
"""R12 data build: official 9/2 closes + 7-item certainty + market-cap tiers (series3 through 2026-09-01).

Sources: zyhe16/top-us-stock-tickers daily snapshots (rebuilt into series4.pkl)
using the exact bottoms/higher-lows/certainty algorithm from the 10MA-watchlist
session (session_01U5TQY1txXMGPoW66fKknbs), applied to this repo's 274-ticker
universe. Percentile components (dv/contr/rs) rank within this universe.
"""
import csv, io, json, pickle, statistics, subprocess

SCRATCH = "/tmp/claude-0/-home-user-VCP-watchlist/ff996f21-17e8-5ead-916f-161009f304a9/scratchpad/work10"
ZREPO = "/home/user/zyhe16/top-us-stock-tickers"

d = pickle.load(open(f"{SCRATCH}/series4.pkl", "rb"))
CAL, SER = d["cal"], d["series"]
print("calendar:", CAL[0], "->", CAL[-1], f"({len(CAL)} trading days)")

# The source series is split-unadjusted. Each event below was verified against
# the source's own share counts (split leaves mcap unchanged; HEAD shares moved
# by exactly the factor) and against this repo's independent web quotes, which
# already sit on the post-split basis. MRNA's 8/19 +177% keeps a constant share
# count in the source — a genuine news repricing, deliberately NOT adjusted.
SPLITS = {"CRWD": ("2026-07-02", 0.25),   # 4:1 forward split
          "KLAC": ("2026-06-12", 0.1),    # 10:1 forward split
          "DD":   ("2026-06-24", 3.0),    # 1:3 reverse split
          "RUSHB": ("2026-08-31", 2 / 3),  # 3:2 split, stock dividend payable 2026-08-31 (8-K 2026-07-28)
          "RUSHA": ("2026-08-31", 2 / 3)}
for sym, (d0, f) in SPLITS.items():
    if sym in SER and d0 in CAL:
        fi, cs, vs, ff = SER[sym]
        cut = CAL.index(d0) - fi
        if cut > 0:
            cs = [c * f if i < cut else c for i, c in enumerate(cs)]
            vs = [v / f if i < cut else v for i, v in enumerate(vs)]
            SER[sym] = (fi, cs, vs, ff)
            print(f"split-adjusted {sym}: x{f} before {d0}")
pickle.dump({"cal": CAL, "series": SER}, open(f"{SCRATCH}/series4adj.pkl", "wb"))

blob = subprocess.run(["git", "-C", ZREPO, "show", "HEAD:data/v2/tickers.csv"],
                      capture_output=True, text=True).stdout
meta = {}
for row in csv.DictReader(io.StringIO(blob.lstrip("﻿"))):
    s = row["symbol"].strip()
    try:
        meta[s] = {"mcap": float(row["market_cap"] or 0), "sector": row["sector"].strip() or "",
                   "price": float(row["price"] or 0)}
    except ValueError:
        pass

ALIAS = {"GPS": "GAP"}   # Gap Inc. now trades as GAP; the source has no GPS row
MY = set()
for f in ("scan_R16_2026-09-02.json", "scan_stage_R9_2026-09-02.json", "scan_PB-R9_2026-09-02.json"):
    MY |= {ALIAS.get(r["ticker"], r["ticker"]) for r in json.load(open(f))["rows"]}
have = sorted(s for s in MY if s in SER and SER[s][0] + len(SER[s][1]) == len(CAL) and len(SER[s][1]) >= 60)
print(f"my universe {len(MY)} | with full current series: {len(have)} | missing: {sorted(MY - set(have))}")

# Reference eligibility (screener10.py): current series, >=90 obs, price>=2, median 20-day $vol >= $1M.
# Percentile items are ranked over THIS market-wide set, then read off for the watchlist.
def _eligible(sym):
    fi, cs, vs, ff = SER[sym]
    if fi + len(cs) != len(CAL) or len(cs) < 90 or cs[-1] < 2: return False
    dv = sorted(c * v for c, v in zip(cs[-20:], vs[-20:]))
    return dv[len(dv) // 2] >= 1_000_000
ELIG = sorted(s for s in SER if _eligible(s))
print(f"market-wide eligible set for percentiles: {len(ELIG)} symbols")
short_hist = sorted(s for s in have if s not in ELIG)
print(f"watchlist tickers scored but outside the reference gate (short history / thin volume): {short_hist}")

def sma(cs, L):
    out = [None] * len(cs); run = 0.0
    for i, c in enumerate(cs):
        run += c
        if i >= L: run -= cs[i - L]
        if i >= L - 1: out[i] = run / L
    return out

def find_bottoms(cs):
    n = len(cs); raw = []
    for i in range(3, n - 3):
        w = cs[i - 3:i + 4]
        if cs[i] == min(w) and cs[i - 3] > cs[i] and cs[i + 3] > cs[i]:
            raw.append((i, cs[i]))
    dedup = []
    for i, c in raw:
        if dedup and i - dedup[-1][0] <= 3:
            if c < dedup[-1][1]: dedup[-1] = (i, c)
        else:
            dedup.append((i, c))
    return dedup

def higher_lows(bots, n, look=45, recent=25):
    inw = [(i, c) for i, c in bots if i >= n - look]
    if len(inw) < 2: return None
    for a, b in zip(inw, inw[1:]):
        if b[1] <= a[1]: return None
    if inw[-1][0] < n - recent: return None
    return inw

def pct_ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    for rank, i in enumerate(order):
        r[i] = rank / (len(vals) - 1) if len(vals) > 1 else 0.5
    return r

POOL = sorted(set(ELIG) | set(have))
rets = {s: SER[s][1][-1] / SER[s][1][-22] - 1 for s in POOL if len(SER[s][1]) >= 22}
med = statistics.median(rets[s] for s in ELIG if s in rets)   # market median, as in the reference
univ, struct, contr_vals = {}, {}, {}
for s in POOL:
    fi, cs, vs, ff = SER[s]
    dn, up = [], []
    for i in range(len(cs) - 15, len(cs)):
        if cs[i] > cs[i - 1]: up.append(vs[i])
        elif cs[i] < cs[i - 1]: dn.append(vs[i])
    dv = (sum(dn) / len(dn)) / (sum(up) / len(up)) if dn and up and sum(up) > 0 else 1.0
    ma20, ma50 = sma(cs, 20), sma(cs, 50)
    f1 = cs[-1] > ma20[-1] if ma20[-1] else False
    f2 = (ma20[-1] > ma50[-1]) if ma50[-1] else False
    f3 = (ma50[-1] > ma50[-11]) if (ma50[-1] and len(ma50) > 11 and ma50[-11]) else False
    univ[s] = {"dv_ratio": dv, "s_ma": 0.4 * f1 + 0.3 * f2 + 0.3 * f3,
               "ma_flags": [bool(f1), bool(f2), bool(f3)], "rs21": rets.get(s, 0) - med}
    n = len(cs)
    bots = find_bottoms(cs)
    hl = higher_lows(bots, n)
    if hl is None:
        continue
    (bP, pP), (bL, pL) = hl[-2], hl[-1]
    H_mid = max(cs[bP:bL]); post_high = max(cs[bL + 1:]); C = cs[-1]
    broke = post_high > H_mid
    progress = (C - pL) / (H_mid - pL) if H_mid > pL else 1.0
    s_break = 1.0 if broke else 0.6 * max(0.0, min(1.0, progress))
    s_retr = max(0.0, min(1.0, progress))
    d_held = (n - 1) - bL
    undercut = min(cs[bL + 1:]) < pL * 0.999
    s_time = min(1.0, d_held / 15) * (0.25 if undercut else 1.0)
    depths, prev_i = [], None
    for k, (bi, bp) in enumerate(hl):
        hi = (max(cs[max(0, bi - 10):bi]) if bi > 0 else bp) if k == 0 else max(cs[prev_i:bi])
        if hi > bp: depths.append((hi - bp) / hi)
        prev_i = bi
    contr = depths[-1] / depths[0] if len(depths) >= 2 and depths[0] > 1e-4 else 1.0
    contr_vals[s] = contr
    struct[s] = {"s_break": s_break, "s_retr": s_retr, "s_time": s_time,
                 "broke": broke, "d_held": d_held, "undercut": undercut, "contr": contr}

import bisect
def pct_of(sorted_vals, v):
    """percentile of v within a sorted reference list (0..1)."""
    if not sorted_vals: return 0.5
    return bisect.bisect_left(sorted_vals, v) / max(1, len(sorted_vals) - 1)
ref_contr = sorted(contr_vals[s] for s in contr_vals if s in ELIG)
ref_rs = sorted(univ[s]["rs21"] for s in univ if s in ELIG)
ref_dv = sorted(univ[s]["dv_ratio"] for s in univ if s in ELIG)
for s in contr_vals:
    struct[s]["s_contr"] = 1 - min(1.0, pct_of(ref_contr, contr_vals[s]))
for s in univ:
    univ[s]["s_rs"] = min(1.0, pct_of(ref_rs, univ[s]["rs21"]))
    univ[s]["s_dv"] = 1 - min(1.0, pct_of(ref_dv, univ[s]["dv_ratio"]))
print(f"percentile reference sizes: rs/dv {len(ref_rs)} | contraction (market HL tickers) {len(ref_contr)}")

cert = {}
for s in have:
    u = univ[s]; st = struct.get(s)
    if st:
        c7 = {"break": st["s_break"], "retr": st["s_retr"], "time": st["s_time"],
              "dv": u["s_dv"], "contr": st["s_contr"], "rs": u["s_rs"], "ma": u["s_ma"]}
        hl_ok = True
    else:
        c7 = {"break": 0.0, "retr": 0.0, "time": 0.0,
              "dv": u["s_dv"], "contr": 0.0, "rs": u["s_rs"], "ma": u["s_ma"]}
        hl_ok = False
    total = 100 * (0.25 * c7["break"] + 0.10 * c7["retr"] + 0.15 * c7["time"]
                   + 0.15 * c7["dv"] + 0.10 * c7["contr"] + 0.10 * c7["rs"] + 0.15 * c7["ma"])
    fi, cseries, vseries, ff = SER[s]
    m = meta.get(s, {})
    cert[s] = {"cert": round(total, 1), "hl_ok": hl_ok,
               "c7": {k: round(v * 100, 1) for k, v in c7.items()},
               "official_close": round(cseries[-1], 4), "mcap": m.get("mcap", 0),
               "chg_21d": round((cseries[-1] / cseries[-22] - 1) * 100, 1) if len(cseries) >= 22 else None,
               "chg_63d": round((cseries[-1] / cseries[-64] - 1) * 100, 1) if len(cseries) >= 64 else None,
               "ma_flags": u["ma_flags"], "dv_ratio": round(u["dv_ratio"], 2),
               "prev_close": round(cseries[-2], 4),
               "range_1m_pct": round((max(cseries[-21:]) / min(cseries[-21:]) - 1) * 100, 1),
               "chg_full_pct": round((cseries[-1] / cseries[0] - 1) * 100, 1),
               "full_days": len(cseries),
               "series_high": round(max(cseries), 4), "series_low": round(min(cseries), 4),
               "short_history": s in short_hist,
               "chg_1d": round((cseries[-1] / cseries[-2] - 1) * 100, 2),
               "chg_5d": round((cseries[-1] / cseries[-6] - 1) * 100, 2) if len(cseries) >= 6 else None,
               "filled_0831": s in set(d.get("filled", {}).get("2026-08-31", []))}

json.dump(cert, open("cert7_2026-09-02.json", "w"), ensure_ascii=False, indent=1)
# any NEW split-like cliff since the last build (8/28 -> 9/1)?
for sym in have:
    fi, cs, vs, ff = SER[sym]
    for i in range(max(1, len(cs) - 3), len(cs)):
        r = cs[i] / cs[i - 1]
        if r <= 0.62 or r >= 1.75:
            print(f"CLIFF {sym} {CAL[fi + i]}: {cs[i-1]:.2f} -> {cs[i]:.2f} (x{r:.3f}) — check for a split before trusting")
n_hl = sum(1 for v in cert.values() if v["hl_ok"])
print(f"certainty computed for {len(cert)} tickers ({n_hl} with a higher-lows structure)")
big = sum(1 for v in cert.values() if v["mcap"] >= 10e9)
mid = sum(1 for v in cert.values() if 2e9 <= v["mcap"] < 10e9)
small = sum(1 for v in cert.values() if 0 < v["mcap"] < 2e9)
print(f"cap tiers: big {big} | mid {mid} | small {small} | no-mcap {len(cert)-big-mid-small}")

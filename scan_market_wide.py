#!/usr/bin/env python3
"""Market-wide scan with the watchlist's own rules — how much is the fixed
274-ticker universe missing?

The watchlist universe was fixed when the first VCP scan was built and has been
carried forward ever since. Now that the merged series covers the whole liquid
US market with a 250-day Yahoo history (MA50 / MA200 / 52-week range / 1-month
to 1-year momentum all computable), the same classifiers can be run over every
eligible symbol. This reports how many names outside the universe would qualify
for the top grades, and lists the best of them.

Output: market_scan_<date>.json
"""
import json, pickle, statistics, sys

from build_r14_snapshots import stage_classify, vcp_classify   # same rules; R15 clone loads a cert file that may not exist yet

SCRATCH = "/tmp/claude-0/-home-user-VCP-watchlist/ff996f21-17e8-5ead-916f-161009f304a9/scratchpad/work10"
d = pickle.load(open(f"{SCRATCH}/series5.pkl", "rb"))
CAL, SER, LONG, SRC = d["cal"], d["series"], d["long"], d["src"]
AS_OF = CAL[-1]

UNI = set()
for f in ("scan_R19_2026-09-06.json", "scan_stage_R12_2026-09-06.json", "scan_PB-R12_2026-09-06.json"):
    UNI |= {r["ticker"] for r in json.load(open(f))["rows"]}

MCAP = {}
try:
    import csv, io, subprocess
    blob = subprocess.run(["git", "-C", "/home/user/zyhe16/top-us-stock-tickers", "show",
                           "HEAD:data/v2/tickers.csv"], capture_output=True, text=True).stdout
    for row in csv.DictReader(io.StringIO(blob.lstrip("﻿"))):
        try:
            MCAP[row["symbol"].strip()] = (float(row["market_cap"] or 0), row["sector"].strip(),
                                           row["name"].strip())
        except ValueError:
            pass
except Exception as e:                                    # metadata is optional
    print("no market-cap metadata:", e)

rows, skipped = [], 0
for s, (fi, cs, vs, ff) in SER.items():
    if fi + len(cs) != len(CAL) or len(cs) < 90:
        continue
    px = cs[-1]
    lg = LONG.get(s) or {}
    if px < 2 or not lg.get("ma200") or (lg.get("days52") or 0) < 240:
        skipped += 1
        continue
    dv = statistics.median(c * v for c, v in zip(cs[-20:], vs[-20:]))
    if dv < 1e6:
        continue
    mc, sector, name = MCAP.get(s, (0, "", ""))
    def chg(n):
        return round((px / cs[-1 - n] - 1) * 100, 1) if len(cs) > n else None
    r = {"ticker": s, "price": round(px, 2), "name": name, "sector": sector, "mcap": mc,
         "year_high": lg["hi52"], "year_low": lg["lo52"],
         "ma50": round(sum(cs[-50:]) / 50, 2) if len(cs) >= 50 else 0,
         "ma200": round(lg["ma200"], 2),
         "chg_1m": chg(21), "chg_3m": chg(63), "chg_6m": lg.get("chg_6m"), "chg_1y": lg.get("chg_1y"),
         "range_1m_pct": round((max(cs[-21:]) / min(cs[-21:]) - 1) * 100, 1) if len(cs) >= 21 else None,
         "vol_ratio": round(statistics.median(vs[-10:]) / statistics.median(vs[-60:-10]), 2)
                      if len(vs) >= 60 and statistics.median(vs[-60:-10]) else None,
         "dollar_vol": round(dv / 1e6, 1), "src": SRC.get(s)}
    rows.append(r)

vcp = [vcp_classify(dict(r)) for r in rows]
stg = [stage_classify(dict(r)) for r in rows]
by_t = {r["ticker"]: r for r in vcp}
st_t = {r["ticker"]: r for r in stg}

out = {"as_of": AS_OF, "eligible": len(rows), "in_universe": len(UNI & {r["ticker"] for r in rows})}
for label, sel in (("VCP_A", [r for r in vcp if r["category"] == "A_VCP待突破"]),
                   ("VCP_B", [r for r in vcp if r["category"] == "B_上升結構"]),
                   ("Stage_2A", [r for r in stg if r["stage"] == "2A_初升段"])):
    for r in sel:
        r["off_high_pct"] = r.get("off_high_pct")
    inside = [r for r in sel if r["ticker"] in UNI]
    outside = sorted((r for r in sel if r["ticker"] not in UNI), key=lambda r: -r["score"])
    out[label] = {"total": len(sel), "in_universe": len(inside), "outside": len(outside),
                  "top_outside": [{"t": r["ticker"], "name": r["name"][:28], "sector": r["sector"],
                                   "mcap_b": round(r["mcap"] / 1e9, 1), "price": r["price"],
                                   "score": r["score"], "off_high": r["off_high_pct"],
                                   "chg_1m": r["chg_1m"], "chg_6m": r["chg_6m"],
                                   "dv_m": r["dollar_vol"],
                                   # a 21-day range under 3% with the price glued to the
                                   # high is the signature of a cash-deal price peg, not a
                                   # contraction (the 10MA watchlist excludes these)
                                   "pegged": bool((r["range_1m_pct"] or 99) < 3
                                                  and (r["off_high_pct"] if "off_high_pct" in r
                                                       else 99) < 3)}
                                  for r in outside[:25]]}
    print(f"{label}: {len(sel)} market-wide | {len(inside)} in the 274 universe | {len(outside)} outside")

# how much of the market does the universe cover at all?
big = [r for r in rows if r["mcap"] >= 2e9]
out["coverage"] = {"eligible": len(rows), "eligible_ge_2b": len(big),
                   "universe_in_eligible": out["in_universe"],
                   "pct_of_ge_2b": round(len(UNI & {r["ticker"] for r in big}) / max(len(big), 1) * 100, 1)}
print("coverage:", out["coverage"], "| skipped (no 250d history / price<2):", skipped)
json.dump(out, open(f"market_scan_{AS_OF}.json", "w"), ensure_ascii=False, indent=1)
print(f"wrote market_scan_{AS_OF}.json")

#!/usr/bin/env python3
"""Check R16's Yahoo-sourced 2026-09-09 closes against the official close.

R16 published 9/9 from Yahoo alone — the upstream snapshot repo had nothing
newer than a 9/9 mid-session quote. The 9/10 mid-session snapshot's
price_change column recovers the previous session's official close, and with
9/7 a market holiday that previous session is 9/4. This compares the two.
"""
import json, pickle, statistics

SCRATCH = "/tmp/claude-0/-home-user-VCP-watchlist/ff996f21-17e8-5ead-916f-161009f304a9/scratchpad/work10"
d = pickle.load(open(f"{SCRATCH}/series4.pkl", "rb"))     # official only, now through 9/4
CAL, SER, FILLED = d["cal"], d["series"], d.get("filled", {})
assert CAL[-1] == "2026-09-09", CAL[-1]
# "filled" marks a close recovered from the next session's snapshot rather than
# read from a post-close one — that recovery is exactly what is being checked
# here, so those tickers stay in.
filled_94 = set(FILLED.get("2026-09-09", []))

ALIAS = {"GPS": "GAP"}
# No split scaling here: a split only rebases the history before its date, and
# the last close in the official series is already on the current basis (checked
# against the upstream HEAD quote for KLAC / CRWD / DD / RUSHB / APH).

pub = {}
for f in ("scan_R21_2026-09-10.json", "scan_stage_R14_2026-09-10.json", "scan_PB-R14_2026-09-10.json"):
    for r in json.load(open(f))["rows"]:
        pub.setdefault(ALIAS.get(r["ticker"], r["ticker"]), r)

diffs, missing, worst = [], [], []
for t, r in pub.items():
    s = SER.get(t)
    if not s or s[0] + len(s[1]) != len(CAL):
        missing.append(t)
        continue
    official = s[1][-1]
    px = r["price"]
    d_pct = (px / official - 1) * 100
    diffs.append(d_pct)
    worst.append((round(abs(d_pct), 3), t, round(px, 2), round(official, 2)))

worst.sort(reverse=True)
out = {"n": len(diffs), "median_pct": round(statistics.median(abs(x) for x in diffs), 4),
       "mean_signed_pct": round(statistics.mean(diffs), 4),
       "gt_0_1pct": sum(1 for x in diffs if abs(x) > 0.1),
       "gt_0_5pct": sum(1 for x in diffs if abs(x) > 0.5),
       "no_official": sorted(missing), "worst": worst[:15]}
json.dump(out, open("validate_r16_0909.json", "w"), ensure_ascii=False, indent=1)
print(f"R16 9/9 published vs official: n={out['n']} median |Δ|={out['median_pct']}% "
      f"|Δ|>0.1%: {out['gt_0_1pct']} |Δ|>0.5%: {out['gt_0_5pct']} | no official close: {len(missing)}")
print("worst:", out["worst"][:8])

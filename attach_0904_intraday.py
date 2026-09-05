#!/usr/bin/env python3
"""Attach the official 2026-09-04 INTRADAY snapshot (10:24 ET) to the scans.

The upstream repo published a mid-session snapshot on 9/4 but no post-close one,
so these prices are NOT a close: they are a 10:24 ET quote whose price_change
reproduces our stored 9/2 close exactly (verified to 0.000% across 241 tickers).
They are carried in separate fields and are deliberately NOT used for
classification, scoring or the certainty series — the tables stay on the
full-day 9/3 official close; the intraday figure is shown in its own column.
"""
import csv, io, json, subprocess

ZREPO = "/home/user/zyhe16/top-us-stock-tickers"
ALIAS = {"GPS": "GAP"}
blob = subprocess.run(["git", "-C", ZREPO, "show", "HEAD:data/v2/tickers.csv"],
                      capture_output=True, text=True).stdout
INTRA = {}
for row in csv.DictReader(io.StringIO(blob.lstrip("﻿"))):
    try:
        INTRA[row["symbol"].strip()] = (float(row["price"]), float(row["percent_change"]))
    except (ValueError, KeyError):
        pass

for f in ("scan_R18_2026-09-05.json", "scan_stage_R11_2026-09-05.json", "scan_PB-R11_2026-09-05.json"):
    scan = json.load(open(f))
    n = 0
    for r in scan["rows"]:
        hit = INTRA.get(ALIAS.get(r["ticker"], r["ticker"]))
        if hit:
            r["px_0904_intraday"], r["chg_0904_intraday"] = round(hit[0], 2), round(hit[1], 2)
            n += 1
    json.dump(scan, open(f, "w"), ensure_ascii=False, indent=1)
    print(f"{f}: 9/4 intraday attached to {n}/{len(scan['rows'])}")

vals = [r["chg_0904_intraday"] for r in json.load(open("scan_R18_2026-09-05.json"))["rows"]
        if r.get("chg_0904_intraday") is not None]
import statistics
print(f"universe 9/4 intraday median {statistics.median(vals):+.2f}% | "
      f"up {sum(1 for v in vals if v > 0)} / down {sum(1 for v in vals if v < 0)}")

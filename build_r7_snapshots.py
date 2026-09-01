#!/usr/bin/env python3
"""R7: apply the verified 2026-09-01 closes over the R4 (8/31 partial) base.

The upstream snapshot repo still has not published data past 8/28 (its 9/1
commit only restored the Actions schedule) and its API stays egress-blocked, so
9/1 closes again came from web search — and only 9 of 274 tickers could be
verified this round. Every other row keeps its previous price and its own
as_of date, so the table now carries three visible bases: 9/1, 8/31 and 8/28.

R14 -> R15, stage R7 -> R8, PB R7 -> R8. Old snapshots are kept untouched.
"""
import json
from collections import Counter

from build_r3_snapshots import stage_classify, vcp_classify

SCRATCH = "/tmp/claude-0/-home-user-VCP-watchlist/ff996f21-17e8-5ead-916f-161009f304a9/scratchpad"
Q = json.load(open(f"{SCRATCH}/quotes0901_final.json"))


def apply_quote(r):
    q = Q.get(r["ticker"])
    r = dict(r)
    if not q or q.get("date") != "2026-09-01" or not q.get("price"):
        return r, False
    old = r.get("price") or 0
    px = q["price"]
    delta = (px / old - 1) * 100 if old else 0
    r["price"] = px
    r["year_high"] = max(r.get("year_high") or 0, px)
    r["year_low"] = min(r.get("year_low") or px, px)
    for k in ("chg_1m", "chg_3m", "chg_6m", "chg_1y"):
        if r.get(k) is not None:
            r[k] = round(r[k] + delta, 1)
    r["chg_5d"] = round((r.get("chg_5d") or 0) + delta, 2)
    r["as_of"] = "2026-09-01"
    r["quote_conf"] = q.get("confidence")
    r["_delta"] = round(delta, 2)
    r["_qnote"] = q.get("note", "")
    return r, True


def process(src, dst, mode):
    scan = json.load(open(src))
    key = "stage" if mode == "stage" else "category"
    rows, moved, notes = [], [], scan.get("notes", [])
    n = 0
    for r in scan["rows"]:
        before = r.get(key)
        r, upd = apply_quote(r)
        n += upd
        if upd:
            if mode == "stage":
                r = stage_classify(r)
            else:
                proxy = (bool(r.get("ma_proxy")) or (r.get("ma50", 0) or 0) <= 0) if mode == "vcp" \
                    else (r.get("ma50", 0) or 0) <= 0
                r = vcp_classify(r, proxy)
            if r.get(key) != before:
                moved.append((r["ticker"], before, r[key]))
            if abs(r.get("_delta", 0)) > 2 and r.get("_qnote"):
                notes.append({"ticker": r["ticker"],
                              "note": f"9/1 {r['_delta']:+.1f}%。{r['_qnote']}", "earnings_date": ""})
            r.pop("_qnote", None)
        rows.append(r)
    seen, out = set(), []
    for x in reversed(notes):
        if x["ticker"] not in seen:
            seen.add(x["ticker"])
            out.append(x)
    scan.update(rows=rows, notes=list(reversed(out)))
    json.dump(scan, open(dst, "w"), ensure_ascii=False, indent=1)
    print(f"{dst}: {n}/{len(rows)} on 9/1 | bases "
          f"{dict(Counter((r.get('as_of') or '')[:10] for r in rows))}")
    if moved:
        print(f"  reclassified: {moved}")


process("scan_R14_2026-08-31.json", "scan_R15_2026-09-01.json", "vcp")
process("scan_stage_R7_2026-08-31.json", "scan_stage_R8_2026-09-01.json", "stage")
process("scan_PB-R7_2026-08-31.json", "scan_PB-R8_2026-09-01.json", "pb")

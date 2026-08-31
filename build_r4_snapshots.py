#!/usr/bin/env python3
"""R4 snapshot refresh: apply verified 2026-08-31 closes on top of the R3 (8/28
official) base.

The upstream daily-snapshot repo's auto-updater broke on 8/28 and its live API
is blocked by this session's egress policy, so 8/31 closes could only be
gathered by web search: 67 of 274 tickers verified. Every other row keeps its
official 8/28 close and its own as_of date, so the mixed basis stays visible
per row rather than being papered over.

R13 -> R14, stage R6 -> R7, PB R6 -> R7. Old snapshots are kept untouched.
"""
import json
from collections import Counter

from build_r3_snapshots import stage_classify, vcp_classify

SCRATCH = "/tmp/claude-0/-home-user-VCP-watchlist/ff996f21-17e8-5ead-916f-161009f304a9/scratchpad"
Q = json.load(open(f"{SCRATCH}/quotes31_final.json"))


def apply_quote(r):
    t = r["ticker"]
    r = dict(r)
    q = Q.get(t)
    if not q or q.get("date") != "2026-08-31" or not q.get("price"):
        return r, False          # keeps its 8/28 as_of — mixed basis stays visible
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
    r["as_of"] = "2026-08-31"
    r["quote_conf"] = q.get("confidence")
    r["_delta"] = round(delta, 2)
    if q.get("note"):
        r["_qnote"] = q["note"]
    return r, True


def process(src, dst, mode):
    scan = json.load(open(src))
    key = "stage" if mode == "stage" else "category"
    rows, moved, notes = [], [], scan.get("notes", [])
    n_upd = 0
    for r in scan["rows"]:
        before = r.get(key)
        r, upd = apply_quote(r)
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
            if abs(r.get("_delta", 0)) > 2 and r.get("_qnote"):
                notes.append({"ticker": r["ticker"],
                              "note": f"8/31 {r['_delta']:+.1f}%。{r.pop('_qnote')}",
                              "earnings_date": ""})
            r.pop("_qnote", None)
        rows.append(r)
    seen, out = set(), []
    for n in reversed(notes):
        if n["ticker"] not in seen:
            seen.add(n["ticker"])
            out.append(n)
    scan.update(rows=rows, notes=list(reversed(out)))
    json.dump(scan, open(dst, "w"), ensure_ascii=False, indent=1)
    c = Counter(r[key] for r in rows)
    dates = Counter((r.get("as_of") or "")[:10] for r in rows)
    print(f"{dst}: {n_upd}/{len(rows)} on 8/31 | dates {dict(dates)} | {dict(c)}")
    if moved:
        print(f"  reclassified {len(moved)}: {moved[:12]}{' ...' if len(moved) > 12 else ''}")


process("scan_R13_2026-08-30.json", "scan_R14_2026-08-31.json", "vcp")
process("scan_stage_R6_2026-08-30.json", "scan_stage_R7_2026-08-31.json", "stage")
process("scan_PB-R6_2026-08-30.json", "scan_PB-R7_2026-08-31.json", "pb")

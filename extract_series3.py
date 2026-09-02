#!/usr/bin/env python3
"""Rebuild the official daily close/volume series from the zyhe16 snapshot repo.

Generalises the 10MA session's extract_series.py: every post-v2 snapshot
(8/28 onward) carries price_change, so price - price_change gives the OFFICIAL
close of the previous trading day. That both corrects days the raw snapshots
got slightly wrong and FILLS days the updater skipped (8/31: the repo's
scheduler was broken that day). Filled days get a neighbour-mean volume and
are listed so the caveat can name them.

Writes series3.pkl {cal, series{sym: (first_idx, closes, vols, ffill_count)}, filled}.
"""
import calendar, csv, datetime, io, os, pickle, subprocess

SCRATCH = "/tmp/claude-0/-home-user-VCP-watchlist/ff996f21-17e8-5ead-916f-161009f304a9/scratchpad/work10"
REPO = "/home/user/zyhe16/top-us-stock-tickers"
HOLIDAYS = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
            "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"}


def is_td(d): return d.weekday() < 5 and d.isoformat() not in HOLIDAYS
def prev_td(d):
    d -= datetime.timedelta(days=1)
    while not is_td(d): d -= datetime.timedelta(days=1)
    return d
def us_dst(d):
    mar = [x for x in calendar.Calendar().itermonthdates(d.year, 3) if x.month == 3 and x.weekday() == 6][1]
    nov = [x for x in calendar.Calendar().itermonthdates(d.year, 11) if x.month == 11 and x.weekday() == 6][0]
    return mar <= d < nov
def commit_to_date(ts):
    d = ts.date(); cutoff = 20 if us_dst(d) else 21
    return d if (ts.hour >= cutoff and is_td(d)) else prev_td(d)
def git_show(sha, path):
    return subprocess.run(["git", "-C", REPO, "show", f"{sha}:{path}"], capture_output=True, text=True).stdout


log = subprocess.run(["git", "-C", REPO, "log", "--format=%H|%aI|%s"], capture_output=True, text=True, check=True).stdout
by_date = {}
for line in log.strip().split("\n"):
    sha, iso, subj = line.split("|", 2)
    if "auto-update ticker lists" not in subj.lower(): continue
    ts = datetime.datetime.fromisoformat(iso).astimezone(datetime.timezone.utc)
    dd = commit_to_date(ts).isoformat()
    if dd not in by_date or ts > by_date[dd][0]:
        by_date[dd] = (ts, sha)
snap_dates = sorted(by_date)
d0, d1 = datetime.date.fromisoformat(snap_dates[0]), datetime.date.fromisoformat(snap_dates[-1])
cal, d = [], d0
while d <= d1:
    if is_td(d): cal.append(d.isoformat())
    d += datetime.timedelta(days=1)
missing = [x for x in cal if x not in by_date]
print(f"trading days {len(cal)} ({cal[0]} -> {cal[-1]}), snapshots {len(snap_dates)}, missing {missing}")

close, vol = {}, {}
def ingest(blob, dd):
    for row in csv.DictReader(io.StringIO(blob.lstrip("﻿"))):
        try:
            sym = row["symbol"].strip(); p = float(row["price"]); v = float(row["volume"] or 0)
        except (ValueError, KeyError, TypeError): continue
        if p <= 0 or not sym: continue
        close.setdefault(sym, {})[dd] = p
        vol.setdefault(sym, {})[dd] = v
for dd in snap_dates:
    _, sha = by_date[dd]
    for path in ("tickers/all.csv", "tickers/sp500.csv"):
        blob = git_show(sha, path)
        if blob: ingest(blob, dd)

# official previous-day close implied by each v2 snapshot's price_change
filled, corrected = {}, 0
for dd in snap_dates:
    _, sha = by_date[dd]
    blob = git_show(sha, "data/v2/tickers.csv")
    if not blob: continue
    pd_ = prev_td(datetime.date.fromisoformat(dd)).isoformat()
    for row in csv.DictReader(io.StringIO(blob.lstrip("﻿"))):
        sym = row["symbol"].strip()
        try: p = float(row["price"]); ch = float(row["price_change"])
        except (ValueError, TypeError): continue
        op = round(p - ch, 4)
        if op <= 0 or sym not in close: continue
        if pd_ in close[sym]:
            if abs(op - close[sym][pd_]) / op < 0.05:
                close[sym][pd_] = op; corrected += 1
        elif pd_ in cal:
            close[sym][pd_] = op
            filled.setdefault(pd_, set()).add(sym)
print("prev-day official corrections:", corrected, "| filled days:", {k: len(v) for k, v in filled.items()})

cal_idx = {d: i for i, d in enumerate(cal)}
series = {}
for sym, cmap in close.items():
    idxs = sorted(cal_idx[d] for d in cmap if d in cal_idx)
    if not idxs: continue
    fi, li = idxs[0], idxs[-1]
    cs, vs, ff, gap, ok = [], [], 0, 0, True
    vmap = vol.get(sym, {})
    lastc = lastv = None
    for i in range(fi, li + 1):
        d = cal[i]
        if d in cmap:
            lastc = cmap[d]; gap = 0
            if d in vmap: lastv = vmap[d]
            else:  # filled day: neighbour-mean volume, flagged via `filled`
                nxt = vmap.get(cal[i + 1]) if i + 1 < len(cal) else None
                lastv = (lastv + nxt) / 2 if (lastv is not None and nxt is not None) else (nxt or lastv or 0.0)
        else:
            gap += 1; ff += 1
            if gap > 3: ok = False; break
        cs.append(lastc); vs.append(lastv)
    if ok: series[sym] = (fi, cs, vs, ff)
print(f"tickers aligned: {len(series)}")
os.makedirs(SCRATCH, exist_ok=True)
pickle.dump({"cal": cal, "series": series, "filled": {k: sorted(v) for k, v in filled.items()}},
            open(f"{SCRATCH}/series3.pkl", "wb"))

# sanity: 9/1 moves that a news wrap reported
chk = {"SU": 68.99, "RPRX": 62.32, "AMZN": 254.92, "NVDA": 217.44}
for t, want in chk.items():
    if t not in series: print(f"  {t}: no aligned series (ADR/gappy) — snapshot builder uses HEAD price"); continue
    fi, cs, vs, ff = series[t]
    print(f"  {t}: 9/1 {cs[-1]} (expect {want}) | 8/31 {cs[-2]:.2f} | 8/28 {cs[-3]:.2f}")

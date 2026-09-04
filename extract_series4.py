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
def snap_kind(ts):
    """Classify a snapshot by its fetch time (UTC).

    The upstream fetcher changed habits: it used to publish pre-open (~10:30
    UTC) or post-close (~20-22 UTC), but from 9/2 it publishes MID-SESSION
    (~14:35 UTC). A mid-session price is not a close, so recording it as one
    would corrupt the series — those snapshots contribute only their
    price_change, which yields the previous day's official close.

    Returns (kind, date_the_prices_close) where kind is
    'close' | 'preopen' | 'intraday'.
    """
    d = ts.date()
    open_h = 13.5 if us_dst(d) else 14.5      # 09:30 ET
    close_h = 20 if us_dst(d) else 21         # 16:00 ET
    h = ts.hour + ts.minute / 60
    if is_td(d) and h >= close_h:
        return "close", d
    if is_td(d) and h >= open_h:
        return "intraday", d                  # prices are mid-session
    return "preopen", prev_td(d)              # before the open -> prior close
def git_show(sha, path):
    return subprocess.run(["git", "-C", REPO, "show", f"{sha}:{path}"], capture_output=True, text=True).stdout


log = subprocess.run(["git", "-C", REPO, "log", "--format=%H|%aI|%s"], capture_output=True, text=True, check=True).stdout
by_date = {}
for line in log.strip().split("\n"):
    sha, iso, subj = line.split("|", 2)
    if "auto-update ticker lists" not in subj.lower(): continue
    ts = datetime.datetime.fromisoformat(iso).astimezone(datetime.timezone.utc)
    kind, dt = snap_kind(ts)
    dd = dt.isoformat()
    key = (dd, kind)
    if key not in by_date or ts > by_date[key][0]:
        by_date[key] = (ts, sha, kind)
closing = {dd: v for (dd, k), v in by_date.items() if k in ("close", "preopen")}
intraday = {dd: v for (dd, k), v in by_date.items() if k == "intraday"}
snap_dates = sorted(closing)
print(f"closing snapshots: {len(snap_dates)} | mid-session snapshots (price_change only): "
      f"{sorted(intraday)}")
# the calendar must reach the newest close we can RECOVER: a mid-session
# snapshot on day D yields D-1's official close via price_change
recoverable = [prev_td(datetime.date.fromisoformat(x)) for x in intraday]
d0 = datetime.date.fromisoformat(snap_dates[0])
d1 = max([datetime.date.fromisoformat(snap_dates[-1])] + recoverable)
cal, d = [], d0
while d <= d1:
    if is_td(d): cal.append(d.isoformat())
    d += datetime.timedelta(days=1)
missing = [x for x in cal if x not in closing]
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
    _, sha, _k = closing[dd]
    for path in ("tickers/all.csv", "tickers/sp500.csv"):
        blob = git_show(sha, path)
        if blob: ingest(blob, dd)

# official previous-day close implied by each v2 snapshot's price_change
filled, corrected = {}, 0
for (dd, kind), (_ts, sha) in sorted(((k, v[:2]) for k, v in by_date.items()), key=lambda kv: kv[0][0]):
    blob = git_show(sha, "data/v2/tickers.csv")
    if not blob: continue
    # price_change is measured against the previous session's official close.
    # For a 'close'/'preopen' snapshot dd is already that prior session, so its
    # own previous day is dd-1; for a mid-session snapshot dd is the day being
    # traded, so price_change resolves dd-1 too.
    base = datetime.date.fromisoformat(dd)
    # every kind resolves the same way: price_change is measured against the
    # close of the session before `base` (for 'preopen', snap_kind already
    # rebased dd onto the session the prices belong to)
    pd_ = prev_td(base).isoformat()
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
            open(f"{SCRATCH}/series4.pkl", "wb"))

# sanity: 9/1 moves that a news wrap reported
chk = {"NVDA": 224.41, "MSFT": 496.82, "CRWD": 203.42, "JNJ": 275.21}
for t, want in chk.items():
    if t not in series: print(f"  {t}: no aligned series (ADR/gappy) — snapshot builder uses HEAD price"); continue
    fi, cs, vs, ff = series[t]
    print(f"  {t}: {cal[-1]} {cs[-1]} (expect {want}) | {cal[-2]} {cs[-2]:.2f} | {cal[-3]} {cs[-3]:.2f}")

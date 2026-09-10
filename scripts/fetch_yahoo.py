#!/usr/bin/env python3
"""Pull daily bars from Yahoo Finance for the tickers in data/yahoo/tickers.txt
and write them as one gzipped CSV — run on a GitHub Actions runner (the research
container's egress proxy blocks Yahoo), see .github/workflows/fetch_yahoo_eod.yml.

Yahoo is the second, independent source for the tickers the Nasdaq-screener series
has no complete series for (the 33 ADR / gap-series names) and for the days the
upstream mirror has not published (09-04 close); the
comparison itself is done by scripts/yahoo_crosscheck.py against the series.

Unadjusted prices (auto_adjust=False) so a close compares directly with the
screener's last sale; the adjusted close is kept as a separate column, which is
how a split between the two sources shows up.
"""
import csv, gzip, os, sys, time

import pandas as pd
import yfinance as yf

START = os.environ.get("START", "2025-09-01")
END = os.environ.get("END", "2026-09-06")          # yfinance end is exclusive
LIST = os.environ.get("LIST", "data/yahoo/tickers.txt")
OUT = os.environ.get("OUT", f"data/yahoo/eod_{START}_{END}.csv.gz")
BATCH = int(os.environ.get("BATCH", "150"))

symbols = [s.strip() for s in open(LIST) if s.strip()]
# Nasdaq writes share classes as BRK.B / BF/B; Yahoo wants BRK-B
ysym = {s: s.replace(".", "-").replace("/", "-") for s in symbols}
back = {v: k for k, v in ysym.items()}
print(f"{len(symbols)} symbols, {START} -> {END}, batches of {BATCH}")

frames, failed = [], []
for i in range(0, len(symbols), BATCH):
    batch = [ysym[s] for s in symbols[i:i + BATCH]]
    for attempt in range(3):
        try:
            df = yf.download(batch, start=START, end=END, interval="1d", auto_adjust=False,
                             actions=False, group_by="ticker", threads=True, progress=False)
            break
        except Exception as e:                       # rate limit / transient
            print(f"batch {i // BATCH}: attempt {attempt + 1} failed: {e}")
            time.sleep(20 * (attempt + 1))
    else:
        failed += batch; continue
    got = 0
    for y in batch:
        try:
            sub = df[y] if isinstance(df.columns, pd.MultiIndex) else df
        except KeyError:
            failed.append(y); continue
        sub = sub.dropna(subset=["Close"])
        if sub.empty:
            failed.append(y); continue
        sub = sub.reset_index().rename(columns=str.lower)
        sub["symbol"] = back[y]
        frames.append(sub[["symbol", "date", "open", "high", "low", "close", "adj close", "volume"]])
        got += 1
    print(f"batch {i // BATCH}: {got}/{len(batch)} symbols with bars")
    time.sleep(2)

# Second pass: Yahoo rate-limits the later batches of a long run, and the
# symbols in them are dropped silently — on a 3,052-name list that reliably
# lost the tail of the alphabet. Retry what failed, in small batches, slowly.
if failed:
    retry, failed2 = sorted(set(failed)), []
    print(f"retry pass: {len(retry)} symbols", flush=True)
    for i in range(0, len(retry), 25):
        batch = retry[i:i + 25]
        for attempt in range(4):
            try:
                df = yf.download(batch, start=START, end=END, interval="1d", auto_adjust=False,
                                 actions=False, group_by="ticker", threads=False, progress=False)
                break
            except Exception as e:
                print(f"retry batch {i // 25}: attempt {attempt + 1} failed: {e}")
                time.sleep(30 * (attempt + 1))
        else:
            failed2 += batch; continue
        got = 0
        for y in batch:
            try:
                sub = df[y] if isinstance(df.columns, pd.MultiIndex) else df
            except KeyError:
                failed2.append(y); continue
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                failed2.append(y); continue
            sub = sub.reset_index().rename(columns=str.lower)
            sub["symbol"] = back[y]
            frames.append(sub[["symbol", "date", "open", "high", "low", "close", "adj close", "volume"]])
            got += 1
        print(f"retry batch {i // 25}: {got}/{len(batch)} recovered", flush=True)
        time.sleep(5)
    print(f"retry pass recovered {len(retry) - len(failed2)}/{len(retry)}")
    failed = failed2

if not frames:
    sys.exit("no data at all; refusing to write")
all_ = pd.concat(frames)
all_["date"] = pd.to_datetime(all_["date"]).dt.strftime("%Y-%m-%d")
all_ = all_.rename(columns={"adj close": "adj_close"}).sort_values(["symbol", "date"])
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with gzip.open(OUT, "wt", newline="") as f:
    all_.to_csv(f, index=False, float_format="%.4f")
n_sym = all_["symbol"].nunique()
print(f"wrote {OUT}: {len(all_)} bars, {n_sym} symbols, {len(failed)} without data")
if failed:
    print("no data:", " ".join(sorted(failed))[:2000])
if n_sym < 0.8 * len(symbols):
    sys.exit(f"only {n_sym}/{len(symbols)} symbols returned; refusing to commit")

#!/usr/bin/env python3
"""Pull quarterly income-statement fundamentals from Yahoo Finance for the
tickers in data/yahoo/fundamental_tickers.txt — run on a GitHub Actions runner
(the research container's egress proxy blocks Yahoo), see
.github/workflows/fetch_yahoo_fundamentals.yml.

Writes data/yahoo/fundamentals_<END>.json.gz:
  {ticker: {"info": {...}, "currency": "USD",
            "quarters": [{"period": "2026-06-30", <line item>: value, ...}, ...],
            "annual":   [{"period": "2025-12-31", ...}, ...],
            "rev_est":  {"+1q": {"avg":..,"low":..,"high":..,"growth":..}, ...},
            "eps_est":  {...}, "next_earnings": "2026-10-28"}}

Only the line items the workbook needs are kept, under Yahoo's own names, so a
missing item is visibly missing rather than silently zero.
"""
import gzip, json, math, os, sys, time

import pandas as pd
import yfinance as yf

LIST = os.environ.get("LIST", "data/yahoo/fundamental_tickers.txt")
END = os.environ.get("END", "2026-09-06")
OUT = os.environ.get("OUT", f"data/yahoo/fundamentals_{END}.json.gz")

WANT = ["Total Revenue", "Operating Revenue", "Cost Of Revenue", "Gross Profit",
        "Operating Expense", "Operating Income", "Total Operating Income As Reported",
        "EBIT", "EBITDA", "Normalized EBITDA", "Pretax Income", "Tax Provision",
        "Net Income", "Net Income Common Stockholders",
        "Net Income From Continuing Operation Net Minority Interest",
        "Normalized Income", "Total Unusual Items", "Total Unusual Items Excluding Goodwill",
        "Tax Effect Of Unusual Items", "Special Income Charges",
        "Net Non Operating Interest Income Expense", "Other Non Operating Income Expenses",
        "Interest Expense", "Reconciled Depreciation",
        "Basic EPS", "Diluted EPS", "Diluted Average Shares"]

INFO_KEYS = ["longName", "shortName", "sector", "industry", "financialCurrency", "currency",
             "marketCap", "trailingPE", "forwardPE", "profitMargins", "operatingMargins",
             "grossMargins", "ebitdaMargins", "revenueGrowth", "earningsGrowth",
             "earningsQuarterlyGrowth", "totalRevenue", "trailingEps", "forwardEps",
             "quoteType", "exchange"]


def num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def frame_rows(df, limit):
    """Yahoo returns line items as rows and periods as columns (newest first)."""
    out = []
    if df is None or getattr(df, "empty", True):
        return out
    for col in list(df.columns)[:limit]:
        rec = {"period": str(pd.Timestamp(col).date())}
        for item in WANT:
            if item in df.index:
                v = num(df.at[item, col])
                if v is not None:
                    rec[item] = v
        out.append(rec)
    return out


def est_rows(df):
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    for idx in df.index:
        rec = {}
        for c in df.columns:
            v = num(df.at[idx, c])
            if v is not None:
                rec[str(c)] = v
        if rec:
            out[str(idx)] = rec
    return out


symbols = [s.strip() for s in open(LIST) if s.strip()]
ysym = {s: s.replace(".", "-").replace("/", "-") for s in symbols}

# Reruns are idempotent and self-healing: an existing file is loaded and only
# the tickers that are missing or came back without a revenue line (Yahoo
# sometimes truncates the timeseries response under load) are fetched again.
data = {}
if os.path.exists(OUT):
    with gzip.open(OUT, "rt") as f:
        data = json.load(f)
    keep = {t: v for t, v in data.items()
            if any("Total Revenue" in q for q in v.get("quarters", []))}
    todo = [s for s in symbols if s not in keep]
    print(f"{len(data)} tickers on file, {len(keep)} complete -> refetching {len(todo)}", flush=True)
    symbols = todo
else:
    print(f"{len(symbols)} tickers -> {OUT}", flush=True)

failed = []
for n, s in enumerate(symbols, 1):
    rec = {}
    for attempt in range(3):
        try:
            tk = yf.Ticker(ysym[s])
            q = frame_rows(tk.quarterly_income_stmt, 6)
            a = frame_rows(tk.income_stmt, 3)
            if not any("Total Revenue" in x for x in q):
                raise ValueError("truncated income statement")
            # Yahoo publishes EPS for the newest quarter days before the rest of
            # the statement; keep the stub so the workbook can say so.
            rec["quarters"], rec["annual"] = q, a
            break
        except Exception as e:                       # rate limit / transient / delisted
            if attempt == 2:
                failed.append(f"{s}({type(e).__name__})")
            else:
                time.sleep(8 * (attempt + 1))
    if not rec:
        continue
    for attr, key in (("info", "info"), ("revenue_estimate", "rev_est"),
                      ("earnings_estimate", "eps_est"), ("calendar", "calendar")):
        try:
            v = getattr(tk, attr)
            if key == "info":
                rec["info"] = {k: v.get(k) for k in INFO_KEYS if v.get(k) is not None}
            elif key == "calendar":
                d = (v or {}).get("Earnings Date") or []
                rec["next_earnings"] = str(d[0]) if d else None
            else:
                rec[key] = est_rows(v)
        except Exception:
            pass
    if rec.get("quarters") or rec.get("annual"):
        data[s] = rec
    if n % 25 == 0:
        print(f"  {n}/{len(symbols)} done, {len(failed)} failed", flush=True)
    time.sleep(0.4)

full = sum(1 for v in data.values() if any("Total Revenue" in q for q in v.get("quarters", [])))
if not symbols:
    print("nothing to refetch")
elif len(data) < 0.8 * len(symbols):
    sys.exit(f"only {len(data)}/{len(symbols)} tickers returned; refusing to commit")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with gzip.open(OUT, "wt") as f:
    json.dump(data, f, ensure_ascii=False)
nq = sum(len(v.get("quarters", [])) for v in data.values())
print(f"wrote {OUT}: {len(data)} tickers ({full} with a revenue line), "
      f"{nq} quarterly statements, {len(failed)} failed")
if failed:
    print("failed:", " ".join(failed)[:2000])

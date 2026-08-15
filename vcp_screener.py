#!/usr/bin/env python3
"""VCP (Volatility Contraction Pattern) watchlist screener.

Scans a universe of tickers for Minervini-style VCP setups:
stage-2 trend template, successively shallower pullbacks,
volume dry-up, and proximity to the pivot buy point.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("yfinance is required: pip install -r requirements.txt", file=sys.stderr)
    raise


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Contraction:
    high_date: pd.Timestamp
    low_date: pd.Timestamp
    depth_pct: float  # pullback depth from local high, positive number


@dataclass
class VCPResult:
    ticker: str
    passed_trend: bool
    contractions: list[Contraction] = field(default_factory=list)
    score: float = 0.0
    close: float = 0.0
    pct_off_high: float = 0.0
    pct_above_low: float = 0.0
    pivot: float = 0.0
    pct_to_pivot: float = 0.0
    volume_ratio: float = 0.0  # recent avg volume / 50d avg volume
    notes: str = ""


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def trend_template(df: pd.DataFrame) -> tuple[bool, dict]:
    """Minervini stage-2 trend template checks."""
    close = df["Close"]
    ma50 = close.rolling(50).mean()
    ma150 = close.rolling(150).mean()
    ma200 = close.rolling(200).mean()

    c = float(close.iloc[-1])
    lo52 = float(close.iloc[-252:].min())
    hi52 = float(close.iloc[-252:].max())

    checks = {
        "above_ma50": c > float(ma50.iloc[-1]),
        "above_ma150": c > float(ma150.iloc[-1]),
        "above_ma200": c > float(ma200.iloc[-1]),
        "ma150_above_ma200": float(ma150.iloc[-1]) > float(ma200.iloc[-1]),
        "ma200_rising": float(ma200.iloc[-1]) > float(ma200.iloc[-22]),
        "above_low_30pct": c >= lo52 * 1.30,
    }
    info = {
        "close": c,
        "pct_off_high": (hi52 - c) / hi52 * 100.0,
        "pct_above_low": (c - lo52) / lo52 * 100.0,
        "hi52": hi52,
    }
    return all(checks.values()), {**checks, **info}


def find_contractions(df: pd.DataFrame, lookback: int = 120, order: int = 5) -> list[Contraction]:
    """Find successive pullbacks (local high -> subsequent local low) in the
    recent window and return them in chronological order."""
    window = df.iloc[-lookback:]
    highs = window["High"].to_numpy()
    lows = window["Low"].to_numpy()
    idx = window.index

    # Local maxima/minima via simple neighborhood comparison
    n = len(window)
    swing_highs = [
        i for i in range(order, n - order)
        if highs[i] == highs[i - order:i + order + 1].max()
    ]

    contractions: list[Contraction] = []
    last_low_i = -1
    for hi_i in swing_highs:
        if hi_i <= last_low_i:
            continue
        # low between this high and the next higher high (or end of data)
        end = n
        for j in range(hi_i + 1, n):
            if highs[j] > highs[hi_i]:
                end = j
                break
        if end - hi_i < 2:
            continue
        seg = lows[hi_i + 1:end]
        lo_rel = int(np.argmin(seg))
        lo_i = hi_i + 1 + lo_rel
        depth = (highs[hi_i] - lows[lo_i]) / highs[hi_i] * 100.0
        if depth < 1.0:  # ignore noise
            continue
        contractions.append(Contraction(idx[hi_i], idx[lo_i], depth))
        last_low_i = lo_i

    return contractions


def is_contracting(contractions: list[Contraction], tolerance: float = 1.15) -> list[Contraction]:
    """Return the longest suffix of contractions in which each pullback is
    shallower than the previous (small tolerance allowed)."""
    if not contractions:
        return []
    seq = [contractions[0]]
    for c in contractions[1:]:
        if c.depth_pct <= seq[-1].depth_pct * tolerance:
            seq.append(c)
        else:
            seq = [c]
    return seq


def analyze(ticker: str, df: pd.DataFrame, max_off_high: float, min_contractions: int) -> VCPResult:
    res = VCPResult(ticker=ticker, passed_trend=False)
    if df is None or len(df) < 260:
        res.notes = "insufficient history"
        return res

    ok, info = trend_template(df)
    res.close = info["close"]
    res.pct_off_high = info["pct_off_high"]
    res.pct_above_low = info["pct_above_low"]
    res.passed_trend = ok

    if not ok:
        res.notes = "failed trend template"
        return res
    if res.pct_off_high > max_off_high:
        res.notes = f"{res.pct_off_high:.0f}% off high (> {max_off_high:.0f}%)"
        res.passed_trend = False
        return res

    all_contr = find_contractions(df)
    seq = is_contracting(all_contr)
    res.contractions = seq

    # Pivot = high of the most recent contraction
    if seq:
        last_high_date = seq[-1].high_date
        res.pivot = float(df.loc[last_high_date, "High"])
        res.pct_to_pivot = (res.pivot - res.close) / res.close * 100.0

    # Volume dry-up: last 10 days vs 50-day average
    vol = df["Volume"]
    v50 = float(vol.rolling(50).mean().iloc[-1])
    v10 = float(vol.iloc[-10:].mean())
    res.volume_ratio = v10 / v50 if v50 > 0 else 1.0

    # --- Scoring (0-100) ---
    score = 0.0
    score += 25.0  # trend template passed

    n = len(seq)
    if n >= min_contractions:
        score += min(20.0, 8.0 * n)  # more contractions, up to 20

        # Tightness: final contraction depth (shallower = better)
        final_depth = seq[-1].depth_pct
        score += max(0.0, 20.0 * (1.0 - min(final_depth, 20.0) / 20.0))

        # Contraction ratio: how much depths shrink across the sequence
        if n >= 2 and seq[0].depth_pct > 0:
            ratio = seq[-1].depth_pct / seq[0].depth_pct
            score += max(0.0, 15.0 * (1.0 - min(ratio, 1.0)))

    # Volume dry-up
    if res.volume_ratio < 1.0:
        score += min(10.0, 10.0 * (1.0 - res.volume_ratio) / 0.5)

    # Pivot proximity (within 10% is workable, within 3% is ideal)
    if seq and -2.0 <= res.pct_to_pivot <= 10.0:
        score += max(0.0, 10.0 * (1.0 - abs(res.pct_to_pivot) / 10.0))

    res.score = round(min(score, 100.0), 1)
    if n < min_contractions:
        res.notes = f"only {n} contraction(s)"
    return res


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_universe(path: str) -> list[str]:
    tickers = []
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip().upper()
            if line:
                tickers.append(line)
    return tickers


def fetch(tickers: list[str]) -> dict[str, pd.DataFrame]:
    data = yf.download(tickers, period="2y", interval="1d", group_by="ticker",
                       auto_adjust=True, progress=False, threads=True)
    out = {}
    for t in tickers:
        try:
            df = data[t].dropna() if len(tickers) > 1 else data.dropna()
            if not df.empty:
                out[t] = df
        except (KeyError, AttributeError):
            pass
    return out


def write_reports(results: list[VCPResult], basename: str, min_score: float) -> None:
    rows = []
    for r in results:
        rows.append({
            "ticker": r.ticker,
            "score": r.score,
            "close": round(r.close, 2),
            "pivot": round(r.pivot, 2) if r.pivot else "",
            "pct_to_pivot": round(r.pct_to_pivot, 1) if r.pivot else "",
            "pct_off_52w_high": round(r.pct_off_high, 1),
            "contractions": len(r.contractions),
            "depths_pct": " > ".join(f"{c.depth_pct:.1f}" for c in r.contractions),
            "vol_ratio_10d_50d": round(r.volume_ratio, 2),
            "notes": r.notes,
        })
    df = pd.DataFrame(rows).sort_values("score", ascending=False)
    df.to_csv(f"{basename}.csv", index=False)

    watch = df[df["score"] >= min_score]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# VCP Watchlist — {now}", ""]
    if watch.empty:
        lines.append(f"No candidates scored >= {min_score:.0f}.")
    else:
        lines.append("| Ticker | Score | Close | Pivot | To pivot % | Off high % | Contractions (depths %) | Vol 10d/50d |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for _, r in watch.iterrows():
            lines.append(
                f"| {r.ticker} | {r.score} | {r.close} | {r.pivot} | {r.pct_to_pivot} "
                f"| {r.pct_off_52w_high} | {r.depths_pct} | {r.vol_ratio_10d_50d} |"
            )
    lines += ["", f"Scanned {len(df)} tickers; {len(watch)} on watchlist (score >= {min_score:.0f}).",
              "", "_Screening aid only — not investment advice._", ""]
    with open(f"{basename}.md", "w") as f:
        f.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description="VCP watchlist screener")
    ap.add_argument("--tickers", help="Comma-separated tickers (overrides --universe)")
    ap.add_argument("--universe", default="tickers.txt")
    ap.add_argument("--min-score", type=float, default=60.0)
    ap.add_argument("--max-off-high", type=float, default=25.0)
    ap.add_argument("--min-contractions", type=int, default=2)
    ap.add_argument("--out", default="watchlist")
    args = ap.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = load_universe(args.universe)
    if not tickers:
        print("No tickers to scan.", file=sys.stderr)
        return 1

    print(f"Fetching data for {len(tickers)} tickers...")
    data = fetch(tickers)
    print(f"Got data for {len(data)} tickers. Analyzing...")
    if not data:
        print("No price data retrieved (network issue or bad tickers).", file=sys.stderr)
        return 1

    results = [analyze(t, df, args.max_off_high, args.min_contractions)
               for t, df in data.items()]
    write_reports(results, args.out, args.min_score)

    top = sorted(results, key=lambda r: r.score, reverse=True)
    n_watch = sum(1 for r in top if r.score >= args.min_score)
    print(f"\nWatchlist ({n_watch} tickers with score >= {args.min_score:.0f}):")
    for r in top:
        if r.score >= args.min_score:
            depths = " > ".join(f"{c.depth_pct:.1f}%" for c in r.contractions)
            print(f"  {r.ticker:<6} score {r.score:>5.1f}  close {r.close:>9.2f}  "
                  f"pivot {r.pivot:>9.2f} ({r.pct_to_pivot:+.1f}%)  contractions: {depths}")
    print(f"\nWrote {args.out}.csv and {args.out}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

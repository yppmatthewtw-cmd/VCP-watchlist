# VCP Watchlist

A stock screener that scans for **Volatility Contraction Patterns (VCP)** — the setup popularized by Mark Minervini — and builds a ranked watchlist of candidates.

## What it looks for

1. **Trend Template** (stage-2 uptrend filter):
   - Price above the 50-day, 150-day, and 200-day moving averages
   - 150-day MA above the 200-day MA, and the 200-day MA trending up
   - Price at least 30% above its 52-week low
   - Price within 25% of its 52-week high
2. **Volatility contraction**:
   - A series of pullbacks (contractions) from local highs, each *shallower* than the last (e.g. 25% → 15% → 8% → 4%)
   - At least 2 contractions detected
3. **Volume dry-up**: recent volume well below its 50-day average as the pattern tightens
4. **Pivot proximity**: price within a few percent of the pattern's pivot (buy point)

Each candidate gets a composite **VCP score (0–100)** and the watchlist is sorted by score.

## Usage

```bash
pip install -r requirements.txt

# Scan the default universe (tickers.txt)
python vcp_screener.py

# Scan specific tickers
python vcp_screener.py --tickers NVDA,MSFT,AVGO,PLTR

# Use your own universe file (one ticker per line, # for comments)
python vcp_screener.py --universe my_tickers.txt

# Loosen/tighten filters
python vcp_screener.py --min-score 50 --max-off-high 30
```

Outputs:

- `watchlist.csv` — full results table
- `watchlist.md` — human-readable report with per-ticker contraction details

## Options

| Flag | Default | Meaning |
|---|---|---|
| `--tickers` | – | Comma-separated tickers (overrides universe file) |
| `--universe` | `tickers.txt` | Path to universe file |
| `--min-score` | `60` | Minimum VCP score to make the watchlist |
| `--max-off-high` | `25` | Max % below 52-week high allowed |
| `--min-contractions` | `2` | Minimum number of contractions |
| `--out` | `watchlist` | Output file basename |

## Notes

- Price data comes from Yahoo Finance via `yfinance`; a network connection is required.
- This is a screening aid, not investment advice. Always confirm the pattern and fundamentals yourself.

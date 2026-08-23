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

## AI watchlist reports

The dated `VCP watchlist (Github)_R*` files are generated from a scan of the AI-focused
universe. Rebuild them from a scan JSON with:

```bash
python make_report.py scan_R0_2026-08-15.json --rev R1 --model "Opus5"   # .md + .csv
python make_html.py   scan_R0_2026-08-15.json --rev R1 --model "Opus5"   # .html
```

## Pre-breakout watchlist (all-US-market series)

The dated `Pre-breakout watchlist (Github)_R*` files are a separate series that screens
**every US-listed stock** (NASDAQ / NYSE / AMEX, ~8,300 tickers → liquidity-filtered to
~2,300) for pre-breakout setups: stage-2 uptrend, within ~10% of the 52-week high, a
tight 1-month range (≥2.5% to reject merger-arb pins) and volume dry-up.

`pb_screener.py` rebuilds a year of daily closes for the whole market from the nightly
snapshots archived in the public `rreichel3/US-Stock-Symbols` dataset repo (each git
commit is an official NASDAQ-screener dump), back-adjusts detected splits, then scores
and tiers candidates with the same A/E/B/C/D scheme:

```bash
python pb_screener.py --out pb_scan_rows.json          # quantitative screen (network required)
# ...news-verify candidates, add notes/market, then:
python make_report.py scan_PB-R0_2026-08-23.json --rev R0 --model "Fable5;ultracode"
python make_html.py   scan_PB-R0_2026-08-23.json --rev R0 --model "Fable5;ultracode"
```

Pre-breakout scan JSONs are named `scan_PB-R*.json` so `make_history.py` (which globs
`scan_R*.json`) keeps tracking only the VCP series. A scan JSON can override the report
series/title and methodology text via optional keys (`series`, `title`, `html_title`,
`data_basis`, `method_notes`, `score_line`, `source_footer`, `data_note`, `disclaimer`) —
without them the generators produce the original VCP-series output unchanged.

Every ticker links to its TradingView chart via `exchanges.py`, which maps each
symbol to its exchange:

```
https://www.tradingview.com/chart/?symbol=nasdaq:nvda
https://www.tradingview.com/chart/?symbol=nyse:iot
```

Both generators warn if a scanned ticker has no exchange mapping — add it to
`NASDAQ` or `NYSE` in `exchanges.py` when the universe grows.

### History tracker

`make_history.py` lines up every `scan_R*.json` snapshot (most recent 10) and
renders each ticker's tier trajectory — who stayed on the watchlist, who was
promoted, and who fell below the line:

```bash
python make_history.py --rev R3 --model "Opus5;high"
```

Tickers currently in tiers A/E/B render above the line; the rest render below
it, split into "dropped out after qualifying" and "never qualified".

## Notes

- Price data comes from Yahoo Finance via `yfinance`; a network connection is required.
- This is a screening aid, not investment advice. Always confirm the pattern and fundamentals yourself.

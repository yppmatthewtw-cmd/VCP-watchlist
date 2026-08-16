"""Ticker -> exchange mapping and TradingView chart links.

TradingView chart URLs need an EXCHANGE:SYMBOL pair, e.g.
    https://www.tradingview.com/chart/?symbol=nasdaq:nvda
"""

from __future__ import annotations

NASDAQ = [
    # AI chips / semis
    "NVDA", "AMD", "AVGO", "ARM", "MRVL", "MU", "ASML", "LRCX", "AMAT", "KLAC",
    "TER", "ALAB", "MPWR", "SNPS", "CDNS", "QCOM", "INTC", "CRDO", "CBRS",
    # hardware / optics
    "SMCI", "LITE", "AAOI",
    # mega-cap / platforms
    "MSFT", "GOOGL", "AMZN", "META", "TSLA",
    # software / security
    "PLTR", "CRWD", "PANW", "ZS", "MDB", "DDOG", "APP", "MNDY",
    # AI small caps
    "SOUN", "TEM", "AXON", "DUOL", "CGNX",
    # power / neoclouds
    "CEG", "TLN", "NBIS", "CRWV", "IREN", "APLD",
]

NYSE = [
    "TSM", "DELL", "HPE", "ANET", "CLS", "JBL", "FN", "COHR", "CIEN", "MOD",
    "ORCL", "NOW", "CRM", "SNOW", "NET", "AI", "BBAI", "RDDT", "IOT",
    "VRT", "ETN", "PWR", "GEV", "VST", "SMR", "OKLO", "BE",
]

EXCHANGE = {t: "nasdaq" for t in NASDAQ}
EXCHANGE.update({t: "nyse" for t in NYSE})


def tv_url(ticker: str) -> str:
    """TradingView chart URL for a ticker, e.g. nasdaq:nvda."""
    ex = EXCHANGE.get(ticker.upper())
    sym = ticker.lower()
    return f"https://www.tradingview.com/chart/?symbol={ex}:{sym}" if ex \
        else f"https://www.tradingview.com/chart/?symbol={sym}"


def missing(tickers) -> list[str]:
    """Tickers with no exchange mapping — link would fall back to bare symbol."""
    return sorted({t.upper() for t in tickers} - set(EXCHANGE))

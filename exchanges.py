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
    "VRT", "ETN", "PWR", "GEV", "VST", "SMR", "OKLO", "BE", "OUST",
]


# All-market expansion (2026-08-22)
NASDAQ += ['ANGO', 'ANIK', 'AXTI', 'BLFS', 'CLDX', 'CME', 'COIN', 'COST', 'CSX', 'DASH', 'EH', 'GILD', 'HOOD', 'HST', 'IOVA', 'ISRG', 'LOB', 'LQDA', 'LULU', 'MAR', 'MCHP', 'MRNA', 'NFLX', 'PCAR', 'REGN', 'ROST', 'RPRX', 'RVMD', 'SBUX', 'TXRH', 'UBSI', 'UFPT', 'URBN', 'VCYT', 'VRTX', 'VTRS', 'WDC']
NYSE += ['ABBV', 'AEO', 'AXP', 'BA', 'BAC', 'BIRK', 'BOOT', 'BX', 'CAH', 'CAT', 'CCJ', 'CVX', 'ENVA', 'ETR', 'FCX', 'FLR', 'GL', 'GLW', 'GPS', 'GS', 'GWW', 'H', 'HII', 'HLT', 'HMY', 'HUBB', 'ICE', 'JNJ', 'JPM', 'KKR', 'KO', 'LH', 'LLY', 'LMT', 'LUMN', 'MA', 'MET', 'MRK', 'NEE', 'NEM', 'NKE', 'NSC', 'OLN', 'OXY', 'PARR', 'PBF', 'PNC', 'RDW', 'RTX', 'SPOT', 'TGT', 'TJX', 'TPR', 'UNH', 'UNM', 'UNP', 'V', 'XOM', 'XPO']


# Pre-breakout universe (2026-08-23)
NASDAQ += ['ADPT', 'ALRS', 'AMAL', 'AMRX', 'ARWR', 'AXGN', 'BJRI', 'BRKR', 'CBIO', 'CCBG', 'CHRD', 'CORT', 'CYRX', 'DNTH', 'DRH', 'EBC', 'ELVN', 'FANG', 'FCFS', 'FTNT', 'GSAT', 'HTO', 'IBKR', 'JAZZ', 'KARO', 'KNSA', 'MBX', 'MEDP', 'MEOH', 'NEO', 'NWBI', 'PGC', 'PVLA', 'RAPP', 'RLAY', 'RRBI', 'RUSHB', 'SENEA', 'SLDE', 'SYRE', 'TGTX', 'TIGO', 'TRST', 'TRVI', 'VSAT', 'WSFS', 'ZD']
NYSE += ['AMN', 'APLE', 'ATI', 'AWR', 'BFH', 'BNS', 'BNY', 'CBL', 'CDP', 'CF', 'CLDT', 'CM', 'CNC', 'CNI', 'CNQ', 'CVE', 'CXW', 'DD', 'DINO', 'EOG', 'EQNR', 'EXPD', 'FBP', 'FTI', 'GD', 'GEO', 'GNK', 'HG', 'HSBC', 'HSHP', 'INSW', 'KFRC', 'KFY', 'KMX', 'MATX', 'MAX', 'MS', 'MSGS', 'OFG', 'PBR', 'PEB', 'PK', 'PKE', 'RCUS', 'REX', 'SNX', 'SOBO', 'STT', 'SU', 'TD', 'TRGP', 'UHAL', 'UNF', 'VOYA', 'WKC', 'WST', 'WT', 'WTTR']

AMEX = ["IMO", "NHC"]   # NYSE American

EXCHANGE = {t: "nasdaq" for t in NASDAQ}
EXCHANGE.update({t: "nyse" for t in NYSE})
EXCHANGE.update({t: "amex" for t in AMEX})


def tv_url(ticker: str) -> str:
    """TradingView chart URL for a ticker, e.g. nasdaq:nvda."""
    ex = EXCHANGE.get(ticker.upper())
    sym = ticker.lower()
    return f"https://www.tradingview.com/chart/?symbol={ex}:{sym}" if ex \
        else f"https://www.tradingview.com/chart/?symbol={sym}"


def missing(tickers) -> list[str]:
    """Tickers with no exchange mapping — link would fall back to bare symbol."""
    return sorted({t.upper() for t in tickers} - set(EXCHANGE))

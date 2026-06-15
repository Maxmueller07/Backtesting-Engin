import re


KNOWN_TICKERS = {
    "apple": ("AAPL", "Apple", "USD", "aktie"),
    "microsoft": ("MSFT", "Microsoft", "USD", "aktie"),
    "meta": ("META", "Meta Platforms", "USD", "aktie"),
    "facebook": ("META", "Meta Platforms", "USD", "aktie"),
    "amazon": ("AMZN", "Amazon", "USD", "aktie"),
    "google": ("GOOGL", "Alphabet", "USD", "aktie"),
    "alphabet": ("GOOGL", "Alphabet", "USD", "aktie"),
    "tesla": ("TSLA", "Tesla", "USD", "aktie"),
    "nvidia": ("NVDA", "NVIDIA", "USD", "aktie"),
    "rheinmetall": ("RHM.DE", "Rheinmetall", "EUR", "aktie"),
    "sap": ("SAP.DE", "SAP", "EUR", "aktie"),
    "siemens": ("SIE.DE", "Siemens", "EUR", "aktie"),
    "allianz": ("ALV.DE", "Allianz", "EUR", "aktie"),
    "basf": ("BAS.DE", "BASF", "EUR", "aktie"),
    "bmw": ("BMW.DE", "BMW", "EUR", "aktie"),
    "mercedes": ("MBG.DE", "Mercedes-Benz", "EUR", "aktie"),
    "vw": ("VOW3.DE", "Volkswagen Vz.", "EUR", "aktie"),
    "volkswagen": ("VOW3.DE", "Volkswagen Vz.", "EUR", "aktie"),
    "bitcoin": ("BTC-USD", "Bitcoin", "USD", "crypto"),
    "btc": ("BTC-USD", "Bitcoin", "USD", "crypto"),
    "ethereum": ("ETH-USD", "Ethereum", "USD", "crypto"),
    "eth": ("ETH-USD", "Ethereum", "USD", "crypto"),
    "s&p 500": ("SPY", "SPDR S&P 500 ETF", "USD", "fonds_etf"),
    "sp500": ("SPY", "SPDR S&P 500 ETF", "USD", "fonds_etf"),
    "nasdaq": ("QQQ", "Invesco QQQ", "USD", "fonds_etf"),
    "msci world": ("EUNL.DE", "iShares Core MSCI World", "EUR", "fonds_etf"),
    "dax etf": ("EXS1.DE", "DAX ETF", "EUR", "fonds_etf"),
}

MARKET_SUFFIXES = {
    "DE": [".DE", ".F", ".BE", ".MU", ".DU", ".HM", ".HA"],
    "US": [""],
    "UK": [".L"],
    "CH": [".SW"],
    "NL": [".AS"],
    "FR": [".PA"],
    "JP": [".T"],
}


def _clean_query(query):
    text = str(query or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def resolve_ticker_candidates(query, market="AUTO"):
    clean = _clean_query(query)
    if not clean:
        return []

    key = clean.lower()
    if key in KNOWN_TICKERS:
        symbol, name, currency, tax_type = KNOWN_TICKERS[key]
        return [{
            "symbol": symbol,
            "name": name,
            "waehrung": currency,
            "steuer_typ": tax_type,
            "confidence": 0.98,
            "reason": "Bekannte Standard-Zuordnung",
        }]

    compact = re.sub(r"[^A-Za-z0-9.\-]", "", clean).upper()
    if not compact:
        return []

    if "." in compact or "-" in compact:
        return [{
            "symbol": compact,
            "name": compact,
            "waehrung": "AUTO",
            "steuer_typ": "crypto" if compact.endswith("-USD") or compact.endswith("-EUR") else "aktie",
            "confidence": 0.85,
            "reason": "Symbol enthaelt bereits yfinance-Suffix oder Paar-Schreibweise",
        }]

    selected_market = str(market or "AUTO").upper()
    suffixes = MARKET_SUFFIXES.get(selected_market)
    if not suffixes:
        suffixes = ["", ".DE", ".F", ".L", ".SW", ".AS", ".PA", ".T"]

    candidates = []
    for idx, suffix in enumerate(suffixes):
        symbol = f"{compact}{suffix}"
        candidates.append({
            "symbol": symbol,
            "name": clean,
            "waehrung": "AUTO",
            "steuer_typ": "aktie",
            "confidence": max(0.35, 0.75 - idx * 0.05),
            "reason": "Heuristik aus Eingabe plus Boersen-Suffix",
        })
    return candidates[:8]

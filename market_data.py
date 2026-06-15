from functools import lru_cache
from pathlib import Path

import pandas as pd
import yfinance as yf


DEFAULT_BASE_CURRENCY = "EUR"
COMMON_CURRENCIES = ("AUTO", "EUR", "USD", "CHF", "GBP", "GBp", "JPY", "CAD", "AUD")
CACHE_DIR = Path(__file__).resolve().parent / ".yfinance-cache"
CACHE_DIR.mkdir(exist_ok=True)

try:
    yf.set_tz_cache_location(str(CACHE_DIR))
    if hasattr(yf, "cache") and hasattr(yf.cache, "set_cache_location"):
        yf.cache.set_cache_location(str(CACHE_DIR))
except Exception:
    pass


def normalize_currency(value, default=None):
    if value is None:
        return default
    currency = str(value).strip()
    if not currency:
        return default
    if currency == "GBp":
        return "GBp"
    upper = currency.upper()
    if upper == "AUTO":
        return None
    if upper in {"GBX", "GBPENCE", "GBPENNY", "GB.P"}:
        return "GBp"
    return upper


def settlement_currency(currency):
    normalized = normalize_currency(currency, DEFAULT_BASE_CURRENCY)
    return "GBP" if normalized == "GBp" else normalized


def price_unit_factor(currency):
    return 0.01 if normalize_currency(currency) == "GBp" else 1.0


def _as_series(value, index):
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return pd.Series(index=index, dtype=float)
        return value.iloc[:, 0]
    if isinstance(value, pd.Series):
        return value
    return pd.Series(value, index=index, dtype=float)


@lru_cache(maxsize=512)
def detect_asset_currency(symbol):
    try:
        ticker = yf.Ticker(symbol)
        fast_info = getattr(ticker, "fast_info", None)
        currency = None
        if fast_info is not None:
            if hasattr(fast_info, "get"):
                currency = fast_info.get("currency")
            if not currency:
                currency = getattr(fast_info, "currency", None)
        if not currency:
            info = getattr(ticker, "info", {}) or {}
            currency = info.get("currency") or info.get("financialCurrency")
        return normalize_currency(currency)
    except Exception:
        return None


def resolve_asset_currency(symbol, configured_currency, basis_currency=DEFAULT_BASE_CURRENCY):
    basis = normalize_currency(basis_currency, DEFAULT_BASE_CURRENCY) or DEFAULT_BASE_CURRENCY
    configured = str(configured_currency or "").strip()

    if not configured:
        return basis, "default_basis"

    if configured.upper() == "AUTO":
        detected = detect_asset_currency(symbol)
        if detected:
            return detected, "auto_detected"
        return basis, "auto_basis_fallback"

    return normalize_currency(configured, basis), "manual"


def _download_close(symbol, start, end):
    df = yf.download(
        symbol,
        start=start,
        end=end,
        actions=True,
        auto_adjust=False,
        progress=False,
    )
    if df.empty or "Close" not in df:
        raise ValueError(f"Keine Kursdaten fuer {symbol} gefunden")
    close = _as_series(df["Close"], df.index).astype(float)
    dividends = _as_series(df["Dividends"], df.index).astype(float) if "Dividends" in df else pd.Series(0.0, index=df.index)
    return close, dividends.fillna(0.0)


def _download_fx_pair(pair, start, end, index):
    try:
        df = yf.download(pair, start=start, end=end, auto_adjust=False, progress=False)
        if df.empty or "Close" not in df:
            return None
        rate = _as_series(df["Close"], df.index).astype(float)
        rate = rate.reindex(index).ffill().bfill()
        if rate.dropna().empty:
            return None
        return rate
    except Exception:
        return None


def get_fx_series(from_currency, to_currency, index, start, end, allow_cross=True):
    from_ccy = settlement_currency(from_currency)
    to_ccy = settlement_currency(to_currency)

    if from_ccy == to_ccy:
        return pd.Series(1.0, index=index)

    direct = _download_fx_pair(f"{from_ccy}{to_ccy}=X", start, end, index)
    if direct is not None:
        return direct

    inverse = _download_fx_pair(f"{to_ccy}{from_ccy}=X", start, end, index)
    if inverse is not None:
        return 1.0 / inverse

    if allow_cross and from_ccy != "USD" and to_ccy != "USD":
        first = get_fx_series(from_ccy, "USD", index, start, end, allow_cross=False)
        second = get_fx_series("USD", to_ccy, index, start, end, allow_cross=False)
        return first * second

    raise ValueError(f"Kein kostenloser FX-Kurs fuer {from_ccy}->{to_ccy} gefunden")


def download_symbol_history(symbol, start, end, basis_currency=DEFAULT_BASE_CURRENCY, configured_currency=None):
    basis = normalize_currency(basis_currency, DEFAULT_BASE_CURRENCY) or DEFAULT_BASE_CURRENCY
    close_native, dividends_native = _download_close(symbol, start, end)
    asset_currency, currency_source = resolve_asset_currency(symbol, configured_currency, basis)
    factor = price_unit_factor(asset_currency)
    money_currency = settlement_currency(asset_currency)
    fx = get_fx_series(money_currency, basis, close_native.index, start, end)

    converted = pd.DataFrame(index=close_native.index)
    converted["Close"] = close_native * factor * fx
    converted["Dividends"] = dividends_native * factor * fx
    converted = converted.ffill().dropna(subset=["Close"])

    meta = {
        "symbol": symbol,
        "asset_currency": asset_currency,
        "settlement_currency": money_currency,
        "basis_currency": basis,
        "currency_source": currency_source,
        "price_unit_factor": factor,
        "fx_pair": f"{money_currency}->{basis}",
    }
    return converted, meta

from datetime import date, datetime, timedelta

import pandas as pd

from market_data import DEFAULT_BASE_CURRENCY, download_symbol_history, normalize_currency


def _parse_created_at(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return date.today()


def _series_to_list(series):
    return [float(v) for v in series.fillna(0).tolist()]


def build_portfolio_dashboard(portfolio, today=None):
    today = today or date.today()
    basis = normalize_currency(portfolio.get("basiswaehrung"), DEFAULT_BASE_CURRENCY) or DEFAULT_BASE_CURRENCY
    saved_date = _parse_created_at(portfolio.get("created_at"))
    fetch_start = max(saved_date - timedelta(days=10), date(1970, 1, 1))
    fetch_end = today + timedelta(days=1)
    startkapital = float(portfolio.get("startkapital") or 0)

    prices = {}
    metas = {}
    errors = []

    for asset in portfolio.get("assets", []):
        symbol = asset.get("symbol")
        if not symbol:
            continue
        try:
            history, meta = download_symbol_history(
                symbol,
                start=fetch_start.isoformat(),
                end=fetch_end.isoformat(),
                basis_currency=basis,
                configured_currency=asset.get("waehrung"),
            )
            prices[symbol] = history["Close"]
            metas[symbol] = meta
        except Exception as exc:
            errors.append({"symbol": symbol, "message": str(exc)})

    target_allocation = [
        {
            "symbol": asset.get("symbol"),
            "name": asset.get("name"),
            "anteil": float(asset.get("anteil") or 0),
            "waehrung": asset.get("waehrung") or "Basis",
            "steuer_typ": asset.get("steuer_typ") or "aktie",
        }
        for asset in portfolio.get("assets", [])
    ]

    if not prices:
        return {
            "id": portfolio.get("id"),
            "name": portfolio.get("name"),
            "created_at": portfolio.get("created_at"),
            "basiswaehrung": basis,
            "startkapital": startkapital,
            "current_value": startkapital,
            "total_return": 0.0,
            "total_return_pct": 0.0,
            "target_allocation": target_allocation,
            "current_allocation": target_allocation,
            "history": {"labels": [], "total": [], "assets": {}},
            "waehrungen": metas,
            "errors": errors,
        }

    price_df = pd.DataFrame(prices).sort_index().ffill()
    since_saved = price_df[price_df.index.date >= saved_date].dropna(how="all")
    if since_saved.empty:
        since_saved = price_df.tail(1)
        errors.append({
            "symbol": "PORTFOLIO",
            "message": "Noch keine neuen Tageskurse seit Speicherung; letzte verfuegbare Kurse werden angezeigt.",
        })
    price_df = since_saved.ffill().dropna()

    values = pd.DataFrame(index=price_df.index)
    for asset in portfolio.get("assets", []):
        symbol = asset.get("symbol")
        if symbol not in price_df:
            continue
        start_price = float(price_df[symbol].iloc[0])
        if not start_price:
            continue
        initial_value = startkapital * float(asset.get("anteil") or 0) / 100
        units = initial_value / start_price
        values[symbol] = price_df[symbol] * units

    if values.empty:
        total = pd.Series([startkapital], index=[pd.Timestamp(saved_date)])
    else:
        total = values.sum(axis=1)

    current_value = float(total.iloc[-1])
    total_return = current_value - startkapital
    total_return_pct = (total_return / startkapital * 100) if startkapital else 0.0

    current_allocation = []
    if not values.empty and current_value:
        last_values = values.iloc[-1]
        for asset in portfolio.get("assets", []):
            symbol = asset.get("symbol")
            if symbol in last_values:
                value = float(last_values[symbol])
                current_allocation.append({
                    "symbol": symbol,
                    "name": asset.get("name"),
                    "anteil": value / current_value * 100,
                    "wert": value,
                    "waehrung": metas.get(symbol, {}).get("asset_currency") or asset.get("waehrung") or basis,
                    "steuer_typ": asset.get("steuer_typ") or "aktie",
                })

    labels = [str(idx.date()) for idx in total.index]
    asset_history = {
        symbol: _series_to_list(values[symbol])
        for symbol in values.columns
    } if not values.empty else {}

    return {
        "id": portfolio.get("id"),
        "name": portfolio.get("name"),
        "created_at": portfolio.get("created_at"),
        "tracking_start": labels[0] if labels else None,
        "tracking_end": labels[-1] if labels else None,
        "basiswaehrung": basis,
        "startkapital": startkapital,
        "current_value": current_value,
        "total_return": float(total_return),
        "total_return_pct": float(total_return_pct),
        "target_allocation": target_allocation,
        "current_allocation": current_allocation or target_allocation,
        "history": {
            "labels": labels,
            "total": _series_to_list(total),
            "assets": asset_history,
        },
        "waehrungen": metas,
        "errors": errors,
    }

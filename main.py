import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd

from custom_rule_engine import execute_custom_rules
from Protfolio import Portfolio
from Parrameter import Parameter
from market_data import DEFAULT_BASE_CURRENCY, download_symbol_history, normalize_currency
from tax_engine import TradeLedger


def _as_series(value, index):
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return pd.Series(index=index, dtype=float)
        return value.iloc[:, 0]
    if isinstance(value, pd.Series):
        return value
    return pd.Series(value, index=index)


def _portfolio_value(portfolio, kurse):
    asset_value = sum(asset.stueckzahl * float(kurse[asset.symbol]) for asset in portfolio.assets)
    return asset_value + float(portfolio.cash)


def _xirr(cashflows):
    if len(cashflows) < 2 or not any(amount < 0 for _, amount in cashflows) or not any(amount > 0 for _, amount in cashflows):
        return 0.0

    start = cashflows[0][0]

    def npv(rate):
        total = 0.0
        for date, amount in cashflows:
            years = max((date - start).days / 365.25, 0)
            total += amount / ((1 + rate) ** years)
        return total

    low, high = -0.9999, 10.0
    try:
        low_npv, high_npv = npv(low), npv(high)
    except OverflowError:
        return 0.0
    if low_npv * high_npv > 0:
        return 0.0

    for _ in range(100):
        mid = (low + high) / 2
        mid_npv = npv(mid)
        if abs(mid_npv) < 1e-7:
            return mid
        if low_npv * mid_npv <= 0:
            high = mid
            high_npv = mid_npv
        else:
            low = mid
            low_npv = mid_npv
    return (low + high) / 2


def regel_manager(
    portfolio,
    reihe,
    datum,
    aktive_regeln,
    state,
    runtime_state,
    intervall,
    schwellwert_config=None,
    stop_loss_config=None,
    custom_regeln=None,
    historische_kurse=None,
    ledger=None,
):
    aktive_regeln = set(aktive_regeln)
    schwellwert_config = schwellwert_config or {}
    stop_loss_config = stop_loss_config or {}

    if "Stop_Loss" in aktive_regeln:
        for asset in portfolio.assets:
            asset.aktueller_preis = reihe[asset.symbol]
            Parameter.execute_stop_loss(
                portfolio,
                asset,
                reihe[asset.symbol],
                state,
                ausstieg_prozent=stop_loss_config.get("ausstieg_prozent", 15),
                wiedereinstieg_prozent=stop_loss_config.get("wiedereinstieg_prozent", 0),
                ledger=ledger,
                datum=datum,
            )

    if "Thesaurirend" in aktive_regeln:
        Parameter.Thesaurirend(portfolio, reihe, state, list(aktive_regeln), ledger=ledger, datum=datum)

    if "dividenden_umschichten" in aktive_regeln:
        Parameter.dividentenUmschichten(portfolio, reihe, state, ledger=ledger, datum=datum)

    if "schwellwert" in aktive_regeln:
        Parameter.schwellwert_umschichtung(
            portfolio,
            reihe,
            state,
            schwelle=schwellwert_config.get("schwelle", 50000),
            von=schwellwert_config.get("von", ""),
            zu=schwellwert_config.get("zu", ""),
            prozent=schwellwert_config.get("prozent", 30),
            ledger=ledger,
            datum=datum,
        )

    if "rebalancing" in aktive_regeln:
        last_rebalance = runtime_state.get("last_rebalance_date")
        rebalancing_noetig = "rebalancing_noetig" in state.get("PORTFOLIO", set())
        intervall_faellig = last_rebalance is None or (datum - last_rebalance).days >= intervall
        if rebalancing_noetig or intervall_faellig:
            Parameter.rebalancing(portfolio, aktuelle_kurse=reihe, state=state, ledger=ledger, datum=datum)
            runtime_state["last_rebalance_date"] = datum

    if custom_regeln:
        execute_custom_rules(
            portfolio=portfolio,
            current_prices=reihe,
            historical_prices=historische_kurse,
            current_date=datum,
            custom_rules=custom_regeln,
            ledger=ledger,
            runtime_state=runtime_state,
        )


def simuliere(
    portfolio: Portfolio,
    aktive_regeln: list,
    startdatum: str,
    enddatum: str,
    intervall: int = 362,
    sp_start: float = 500,
    schwellwert_config: dict | None = None,
    stop_loss_config: dict | None = None,
    sparplan_dynamisierung: float = 0.10,
    sparplan_limit: float = 2000,
    basiswaehrung: str = DEFAULT_BASE_CURRENCY,
    transaktionskosten_config: dict | None = None,
    steuer_config: dict | None = None,
    custom_regeln: list | None = None,
):
    if intervall <= 0:
        raise ValueError("Rebalancing-Intervall muss groesser als 0 sein")
    if sp_start < 0:
        raise ValueError("Sparplan darf nicht negativ sein")
    if sparplan_dynamisierung < 0:
        raise ValueError("Sparplan-Dynamisierung darf nicht negativ sein")

    basiswaehrung = normalize_currency(basiswaehrung, DEFAULT_BASE_CURRENCY) or DEFAULT_BASE_CURRENCY
    preise_df = pd.DataFrame()
    currency_meta = {}
    for asset in portfolio.assets:
        history, meta = download_symbol_history(
            asset.symbol,
            start=startdatum,
            end=enddatum,
            basis_currency=basiswaehrung,
            configured_currency=getattr(asset, "waehrung", None),
        )
        preise_df[asset.symbol] = history["Close"]
        preise_df[f"{asset.symbol}_div"] = history["Dividends"].fillna(0)
        currency_meta[asset.symbol] = meta

    preise_df = preise_df.ffill().dropna()
    if preise_df.empty:
        raise ValueError("Keine gemeinsamen Kursdaten fuer die gewaehlten Assets und Daten gefunden")

    ledger = TradeLedger(transaktionskosten_config, steuer_config)
    gesamt_kapital = float(portfolio.cash)
    start_datum = preise_df.index[0]
    for asset in portfolio.assets:
        start_preis = preise_df[asset.symbol].iloc[0]
        if not start_preis or pd.isna(start_preis):
            raise ValueError(f"Ungueltiger Startpreis fuer {asset.symbol}")
        asset_wert = (gesamt_kapital * asset.ziel_anteil) / 100
        ledger.buy_with_budget(asset, asset_wert, start_preis, start_datum, reason="initial")
    portfolio.cash = 0

    portfolio_historie = pd.DataFrame(index=preise_df.index)
    tages_state = {}
    runtime_state = {"last_rebalance_date": None}
    sp = float(sp_start)
    gesamt_eingezahlt = gesamt_kapital
    last_sparplan_month = None
    cashflows = [(preise_df.index[0], -gesamt_kapital)]
    unit_price = 100.0
    units = gesamt_kapital / unit_price if gesamt_kapital else 0.0
    last_harvest_year = None

    for datum, reihe in preise_df.iterrows():
        tages_state.clear()

        for asset in portfolio.assets:
            asset.aktueller_preis = reihe[asset.symbol]

        monats_key = (datum.year, datum.month)
        beitrag = 0.0
        if "sparblan" in aktive_regeln and monats_key != last_sparplan_month and sp > 0:
            beitrag = min(sp, sparplan_limit) if sparplan_limit > 0 else sp
            Parameter.sparplan(portfolio, beitrag, reihe, ledger=ledger, datum=datum)
            gesamt_eingezahlt += beitrag
            cashflows.append((datum, -beitrag))
            if units and unit_price:
                units += beitrag / unit_price
            last_sparplan_month = monats_key
            sp = min(beitrag * (1 + sparplan_dynamisierung), sparplan_limit) if sparplan_limit > 0 else beitrag * (1 + sparplan_dynamisierung)

        try:
            regel_manager(
                portfolio,
                reihe,
                datum,
                aktive_regeln,
                tages_state,
                runtime_state,
                intervall,
                schwellwert_config,
                stop_loss_config,
                custom_regeln,
                preise_df.loc[:datum],
                ledger,
            )
        except Exception as exc:
            raise RuntimeError(f"Fehler in Regelverarbeitung am {datum.date()}: {exc}") from exc

        next_rows = preise_df.index[preise_df.index > datum]
        is_last_trading_day_of_year = len(next_rows) == 0 or next_rows[0].year != datum.year
        if is_last_trading_day_of_year and last_harvest_year != datum.year:
            ledger.maybe_harvest_losses(portfolio, reihe, datum)
            last_harvest_year = datum.year

        for asset in portfolio.assets:
            portfolio_historie.at[datum, f"{asset.symbol}_wert"] = asset.stueckzahl * float(reihe[asset.symbol])
            portfolio_historie.at[datum, f"{asset.symbol}_aktiv"] = bool(getattr(asset, "aktiv", True))

        tages_wert = _portfolio_value(portfolio, reihe)
        portfolio_historie.at[datum, "Cash"] = float(portfolio.cash)
        portfolio_historie.at[datum, "Gesamtwert"] = tages_wert
        portfolio_historie.at[datum, "Eingezahlt"] = gesamt_eingezahlt

        if units:
            unit_price = tages_wert / units
        portfolio_historie.at[datum, "UnitValue"] = unit_price

    gesamtwert_ende = float(portfolio_historie["Gesamtwert"].iloc[-1])
    cashflows.append((portfolio_historie.index[-1], gesamtwert_ende))

    gewinn = gesamtwert_ende - float(gesamt_eingezahlt)
    gesamt_rendite = (gewinn / float(gesamt_eingezahlt)) * 100 if gesamt_eingezahlt else 0.0
    jaehrliche_rendite = _xirr(cashflows) * 100

    renditen = portfolio_historie["UnitValue"].pct_change().dropna()
    rendite_std = renditen.std()
    sharpe_ratio = float((renditen.mean() / rendite_std) * np.sqrt(252)) if rendite_std and not pd.isna(rendite_std) else 0.0
    volatilitaet = float(rendite_std * np.sqrt(252) * 100) if rendite_std and not pd.isna(rendite_std) else 0.0

    einzel_werte = {
        asset.symbol: float(portfolio_historie[f"{asset.symbol}_wert"].iloc[-1])
        for asset in portfolio.assets
    }

    return {
        "gesamtwert": gesamtwert_ende,
        "gesamt_eingezahlt": float(gesamt_eingezahlt),
        "gewinn": float(gewinn),
        "gesamt_rendite": float(gesamt_rendite),
        "jaehrliche_rendite": float(jaehrliche_rendite),
        "sharpe_ratio": sharpe_ratio,
        "volatilitaet": volatilitaet,
        "einzel_werte": einzel_werte,
        "historie": portfolio_historie,
        "cashflows": [(str(date.date()), float(amount)) for date, amount in cashflows],
        "startdatum": str(portfolio_historie.index[0].date()),
        "enddatum": str(portfolio_historie.index[-1].date()),
        "basiswaehrung": basiswaehrung,
        "waehrungen": currency_meta,
        "steuer_report": ledger.summary(),
        "custom_rule_events": runtime_state.get("custom_rule_events", []),
    }


if __name__ == "__main__":
    import matplotlib
    matplotlib.use("TkAgg", force=True)
    import matplotlib.pyplot as plt

    user_portfolio = Portfolio(20000, True)
    user_portfolio.add_asset("PepsiCo", "PEP", 50, 0)
    user_portfolio.add_asset("Intel", "INTC", 50, 0)

    if not user_portfolio.check_antiel():
        raise SystemExit(1)

    ergebnis = simuliere(
        portfolio=user_portfolio,
        aktive_regeln=["Thesaurirend", "rebalancing", "schwellwert"],
        startdatum="2014-04-01",
        enddatum="2026-01-01",
        intervall=362,
        sp_start=500,
        schwellwert_config={"schwelle": 50000, "von": "INTC", "zu": "PEP", "prozent": 30},
    )

    historie = ergebnis["historie"]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [2, 1]})
    ax1.plot(historie.index, historie["Gesamtwert"], color="black", linewidth=2.5, label="Gesamtportfolio")
    ax1.axhline(y=ergebnis["gesamt_eingezahlt"], color="red", linestyle="--", linewidth=1.2, label="Eingezahlt")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(True, linestyle="--", alpha=0.7)

    for asset in user_portfolio.assets:
        ax2.plot(historie.index, historie[f"{asset.symbol}_wert"], label=asset.symbol, alpha=0.8, linewidth=1.2)
    ax2.legend(loc="upper left", ncol=3, fontsize=8)
    ax2.grid(True, linestyle="--", alpha=0.7)
    plt.tight_layout()
    plt.show()

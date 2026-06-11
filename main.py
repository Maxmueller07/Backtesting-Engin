import matplotlib
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
from pandas.core.indexes import interval
from quantstats.stats import sharpe, volatility

matplotlib.use('TkAgg')

from Assets import Asset
from Protfolio import Portfolio
from Parrameter import Parameter


# ── Regel Manager ─────────────────────────────────────────────────────────────

def regel_manager(portfolio, reihe, datum, aktive_regeln, state, intervall_zähler, intervall, sp):
    for regel in aktive_regeln:
        match regel:
            case "Stop_Loss":
                for asset in portfolio.assets:
                    kurs_heute = reihe[asset.symbol]
                    asset.aktueller_preis = kurs_heute
                    Parameter.execute_stop_loss(portfolio, asset, kurs_heute, state)

            case "rebalancing":
                rebalancing_nötig = "rebalancing_nötig" in state.get("PORTFOLIO", set())
                if intervall_zähler % intervall == 0 or rebalancing_nötig:
                    Parameter.rebalancing(portfolio, aktuelle_kurse=reihe, state=state)

            case "schwellwert":
                Parameter.schwellwert_umschichtung(portfolio, reihe, state,
                                                   schwelle=50000,  # ← dein Zielwert
                                                   von="INTC",  # ← von Intel
                                                   zu="PEP",  # ← zu Pepsi
                                                   prozent=30)

            case "Thesaurirend":
                Parameter.Thesaurirend(portfolio, reihe, state, aktive_regeln)

            case "dividenden_umschichten":
                Parameter.dividentenUmschichten(portfolio, reihe, state)

            case "sparblan":
                if datum.day == 1:
                    limit = 2000
                    dynamiesierung = 0.1
                    if sp < limit:
                        sp += sp * dynamiesierung
                    else:
                        sp = limit
                    Parameter.sparplan(portfolio, datum, state, sp, kurse=reihe)

    return sp


# ── Haupt Simulations Funktion ────────────────────────────────────────────────

def simuliere(portfolio: Portfolio,
              aktive_regeln: list,
              startdatum: str,
              enddatum: str,
              intervall: int = 362,
              sp_start: float = 500):
    preise_df = pd.DataFrame()

    # Kursdaten laden
    for asset in portfolio.assets:
        df = yf.download(asset.symbol, start=startdatum, end=enddatum,
                         actions=True, auto_adjust=False)
        preise_df[asset.symbol] = df['Close']
        preise_df[f'{asset.symbol}_div'] = df['Dividends'].fillna(0)

    preise_df = preise_df.ffill()
    preise_df = preise_df.dropna()

    # Startstückzahlen berechnen
    gesamt_kapital = portfolio.cash
    for asset in portfolio.assets:
        start_preis = preise_df[asset.symbol].iloc[0]
        asset_wert = (gesamt_kapital * asset.ziel_anteil) / 100
        asset.stueckzahl = asset_wert / start_preis
    portfolio.cash = 0

    # Simulation
    portfolio_historie = pd.DataFrame(index=preise_df.index)
    tages_state = {}
    intervall_zähler = 0
    sp = sp_start
    gesamt_eingezahlt = gesamt_kapital

    for datum, reihe in preise_df.iterrows():
        try:
            intervall_zähler += 1
            tages_state.clear()

            for asset in portfolio.assets:
                asset.aktueller_preis = reihe[asset.symbol]
                aktueller_wert = asset.stueckzahl * reihe[asset.symbol]
                portfolio_historie.at[datum, f'{asset.symbol}_wert'] = aktueller_wert

            sp = regel_manager(portfolio, reihe, datum, aktive_regeln,
                               tages_state, intervall_zähler, intervall, sp)

            if datum.day == 1 and "sparblan" in aktive_regeln:
                gesamt_eingezahlt += sp

            tages_wert = sum(a.stueckzahl * reihe[a.symbol] for a in portfolio.assets)
            tages_wert += portfolio.cash
            portfolio_historie.at[datum, 'Gesamtwert'] = tages_wert

        except Exception as e:
            print(f"FEHLER am {datum}: {e}")
            import traceback
            traceback.print_exc()
            break

    # Kennzahlen berechnen
    gesamtwert_ende = portfolio_historie['Gesamtwert'].iloc[-1]
    gesamtwert_start = portfolio_historie['Gesamtwert'].iloc[0]
    gesamt_rendite = ((gesamtwert_ende / gesamtwert_start) - 1) * 100
    jahre = (portfolio_historie.index[-1] - portfolio_historie.index[0]).days / 365.25
    jaehrliche_rendite = ((gesamtwert_ende / gesamtwert_start) ** (1 / jahre) - 1) * 100

    renditen = portfolio_historie['Gesamtwert'].pct_change().dropna()
    sharpe_ratio = (renditen.mean() / renditen.std()) * np.sqrt(252)
    volatilitaet = renditen.std() * np.sqrt(252) * 100

    einzel_werte = {}
    for asset in portfolio.assets:
        einzel_werte[asset.symbol] = portfolio_historie[f'{asset.symbol}_wert'].iloc[-1]

    return {
        "gesamtwert": gesamtwert_ende,
        "gesamt_eingezahlt": gesamt_eingezahlt,
        "gewinn": gesamtwert_ende - gesamt_eingezahlt,
        "gesamt_rendite": gesamt_rendite,
        "jaehrliche_rendite": jaehrliche_rendite,
        "sharpe_ratio": sharpe_ratio,
        "volatilitaet": volatilitaet,
        "einzel_werte": einzel_werte,
        "historie": portfolio_historie,
        "startdatum": str(portfolio_historie.index[0].date()),
        "enddatum": str(portfolio_historie.index[-1].date()),
    }


# ── Direkt ausführen (ohne FastAPI) ──────────────────────────────────────────

if __name__ == "__main__":
    import matplotlib
    import matplotlib.pyplot as plt

    matplotlib.use('TkAgg')

    # Portfolio aufbauen
    User_porfolio = Portfolio(20000, True)

    # Bucket 1 – Stabil (50%)
    User_porfolio.add_asset("PepsiCo", "PEP", 50, 0)
    User_porfolio.add_asset("Intel", "INTC", 50, 0)


    if not User_porfolio.check_antiel():
        exit()

    aktive_regeln = [ "Thesaurirend", "rebalancing","schwellwert"]

    ergebnis = simuliere(
        portfolio=User_porfolio,
        aktive_regeln=aktive_regeln,
        startdatum="2014-04-01",
        enddatum="2026-01-01",
        intervall=362,
        sp_start=500
    )

    # Plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10),
                                   gridspec_kw={'height_ratios': [2, 1]})

    historie = ergebnis["historie"]

    ax1.plot(historie.index, historie['Gesamtwert'],
             color='black', linewidth=2.5, label='Gesamtportfolio')
    ax1.axhline(y=ergebnis["gesamt_eingezahlt"], color='red', linestyle='--',
                linewidth=1.2, label=f'Eingezahlt: {ergebnis["gesamt_eingezahlt"]:,.0f}€')
    ax1.set_title(
        f"Gesamt-Depot: {ergebnis['gesamtwert']:,.2f}€  |  "
        f"Eingezahlt: {ergebnis['gesamt_eingezahlt']:,.0f}€  |  "
        f"Gewinn: {ergebnis['gewinn']:,.0f}€\n"
        f"Gesamtrendite: {ergebnis['gesamt_rendite']:.1f}%  |  "
        f"Ø Jährlich: {ergebnis['jaehrliche_rendite']:.1f}%  |  "
        f"Sharpe: {ergebnis['sharpe_ratio']:.2f}  |  "
        f"Volatilität: {ergebnis['volatilitaet']:.1f}%",
        fontsize=11, fontweight='bold'
    )
    ax1.set_ylabel('Wert in Euro (€)', fontsize=11)
    ax1.grid(True, linestyle='--', alpha=0.7)
    ax1.legend(loc='upper left', fontsize=9)

    for asset in User_porfolio.assets:
        ax2.plot(historie.index, historie[f'{asset.symbol}_wert'],
                 label=asset.symbol, alpha=0.8, linewidth=1.2)

    einzel_titel = ' | '.join([f"{s}: {w:,.0f}€" for s, w in ergebnis["einzel_werte"].items()])
    ax2.set_title(einzel_titel, fontsize=9)
    ax2.set_ylabel('Einzelwerte (€)', fontsize=11)
    ax2.set_xlabel('Datum', fontsize=11)
    ax2.grid(True, linestyle='--', alpha=0.7)
    ax2.legend(loc='upper left', ncol=3, fontsize=8)

    plt.tight_layout()
    plt.show()








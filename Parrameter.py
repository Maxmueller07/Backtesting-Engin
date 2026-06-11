from os import add_dll_directory
import math

from bs4.diagnose import profile


class Parameter:


    regelsammlung = {"rebalance": [], "stop_loss": []}




    def rebalancing(portfolio,aktuelle_kurse,state ):



        aktive_assets = [a for a in portfolio.assets if getattr(a, 'aktiv', True) and "gesperrt"  not in state.get(a.symbol, set())]

        if not aktive_assets:
            print("Keine aktiven Assets mehr im Portfolio!")
            return


        wert_aktien = sum([a.stueckzahl * aktuelle_kurse[a.symbol] for a in aktive_assets])
        gesamtwert = portfolio.cash + wert_aktien


        portfolio.cash = 0


        summe_ziel_anteile = sum([a.ziel_anteil for a in aktive_assets])

        for a in aktive_assets:

            neuer_anteil_faktor = a.ziel_anteil / summe_ziel_anteile
            soll_wert_euro = gesamtwert * neuer_anteil_faktor


            a.stueckzahl = soll_wert_euro / aktuelle_kurse[a.symbol]


        inaktive_assets = [a for a in portfolio.assets if not getattr(a, 'aktiv', True)]
        for i_a in inaktive_assets:
            i_a.stueckzahl = 0

    def execute_stop_loss(portfolio, asset, kurs_heute, state, schwelle=0.85):
        kurs = float(kurs_heute)

        # Wiedereinstieg
        if not getattr(asset, 'aktiv', True):
            if asset.sold_preis is not None:
                if kurs >= asset.sold_preis:
                    asset.stueckzahl = asset.sold_erloes / kurs
                    portfolio.cash -= asset.sold_erloes
                    asset.aktiv = True
                    asset.peak_preis = kurs
                    asset.sold_preis = None
                    asset.sold_erloes = None
                    print(f"[WIEDEREINSTIEG] {asset.symbol} bei {kurs:.2f}")
            return

        # Peak tracken
        if asset.peak_preis is None:
            asset.peak_preis = kurs
        if kurs > asset.peak_preis:
            asset.peak_preis = kurs

        # Stop Loss
        stop_limit = asset.peak_preis * schwelle
        if asset.stueckzahl > 0 and kurs < stop_limit:
            erloes = asset.stueckzahl * kurs
            portfolio.cash += erloes
            asset.stueckzahl = 0
            asset.aktiv = False
            asset.peak_preis = None
            asset.sold_preis = kurs  # ← beide setzen
            asset.sold_erloes = erloes  # ← beide setzen
            state.setdefault(asset.symbol, set()).add("gesperrt")
            print(f"!!! STOP-LOSS GEFEUERT: {asset.symbol} bei {kurs:.2f} !!!")

    def Thesaurirend(portfolio, kurse, state,aktieve_regelen):
        for asset in portfolio.assets:
            if not getattr(asset, 'aktiv', True):
                continue
            if asset.regeln.get("dividenden_ziel") is not None and "dividenden_umschichten" in aktieve_regelen:
                continue

            div_spalte = f'{asset.symbol}_div'
            if div_spalte not in kurse:
                continue

            div_betrag = float(kurse[div_spalte])
            if math.isnan(div_betrag) or div_betrag <= 0:
                continue

            div_gesamt = asset.stueckzahl * div_betrag
            neue_stuecke = div_gesamt / float(kurse[asset.symbol])
            asset.stueckzahl += neue_stuecke
            asset.gesamt_dividenden += div_gesamt
            print(f"[DIVIDENDE] {asset.symbol}: +{div_gesamt:.2f}€ reinvestiert")


    def dividentenUmschichten(portfolio, kurse, state ):
        for asset in portfolio.assets:
            if not getattr(asset, 'aktiv', True):
                continue

            if asset.regeln.get("dividenden_ziel") is  None:
                continue

            summe = sum(asset.regeln.get("dividenden_ziel", None).values())
            if summe != 100:
                print(f"Fehler: {summe}% statt 100%")
                return

            for zie_symbol in asset.regeln.get("dividenden_ziel", None).keys():
                if zie_symbol not in [a.symbol for a in portfolio.assets]:
                    print(f"Fehler: {zie_symbol} nicht im Portfolio")
                    return

            div_spalte = f'{asset.symbol}_div'
            if div_spalte not in kurse:
                continue

            div_betrag = float(kurse[div_spalte])
            if math.isnan(div_betrag) or div_betrag <= 0:
                continue

            div_gesamt = asset.stueckzahl * div_betrag

            for zie_symbol, prozent in asset.regeln.get("dividenden_ziel", None).items():
                anteil = div_gesamt * (prozent / 100)
                ziel_asset = next(a for a in portfolio.assets if a.symbol == zie_symbol)
                neue_stuecke = anteil / float(kurse[zie_symbol])
                ziel_asset.stueckzahl += neue_stuecke
                print(f"[DIVIDENDE] {asset.symbol} → {zie_symbol}: +{anteil:.2f}€")

            asset.gesamt_dividenden += div_gesamt

    def sparplan(portfolio, datum, state, betrag,kurse):
        if datum.day != 1:
            return

        aktive_assets = [a for a in portfolio.assets if getattr(a, 'aktiv', True)]
        summe_anteile = sum(a.ziel_anteil for a in aktive_assets)



        for asset in aktive_assets:
            anteil = betrag * (asset.ziel_anteil / summe_anteile)
            asset.stueckzahl += anteil / float(kurse[asset.symbol])

        print(f"[SPARPLAN] +{betrag:.2f}€ am {datum.date()} direkt investiert")

    def schwellwert_umschichtung(portfolio, kurse, state, schwelle, von, zu, prozent):

        # None checks
        if not schwelle or not von or not zu or not prozent:
            print("Fehler: Schwellwert-Parameter fehlen")
            return

        if getattr(portfolio, 'schwellwert_gefeuert', False):
            return

        # Bereits heute umgeschichtet
        if "umgeschichtet" in state.get("PORTFOLIO", set()):
            return

        gesamtwert = sum(a.stueckzahl * float(kurse[a.symbol]) for a in portfolio.assets)

        if gesamtwert < schwelle:
            return

        von_asset = next((a for a in portfolio.assets if a.symbol == von), None)
        zu_asset = next((a for a in portfolio.assets if a.symbol == zu), None)

        if not von_asset or not zu_asset:
            print(f"Fehler: {von} oder {zu} nicht im Portfolio")
            return

        von_wert = von_asset.stueckzahl * float(kurse[von])
        umschicht = von_wert * (prozent / 100)

        von_asset.stueckzahl -= umschicht / float(kurse[von])
        zu_asset.stueckzahl += umschicht / float(kurse[zu])

        # Signal setzen
        state.setdefault("PORTFOLIO", set()).add("umgeschichtet")
        state.setdefault("PORTFOLIO", set()).add("rebalancing_nötig")  # ← Rebalancing auslösen
        portfolio.schwellwert_gefeuert = True
        print(f"[SCHWELLWERT] {prozent}% von {von} → {zu} | {umschicht:,.0f}€")
























import math


class Parameter:
    regelsammlung = {"rebalance": [], "stop_loss": []}

    @staticmethod
    def rebalancing(portfolio, aktuelle_kurse, state, ledger=None, datum=None):
        aktive_assets = [
            asset
            for asset in portfolio.assets
            if getattr(asset, "aktiv", True) and "gesperrt" not in state.get(asset.symbol, set())
        ]
        if not aktive_assets:
            return

        wert_aktien = sum(asset.stueckzahl * float(aktuelle_kurse[asset.symbol]) for asset in aktive_assets)
        gesamtwert = portfolio.cash + wert_aktien

        summe_ziel_anteile = sum(asset.ziel_anteil for asset in aktive_assets)
        if not summe_ziel_anteile:
            return

        if ledger is not None and datum is not None:
            targets = {
                asset.symbol: gesamtwert * (asset.ziel_anteil / summe_ziel_anteile)
                for asset in aktive_assets
            }
            for asset in portfolio.assets:
                preis = float(aktuelle_kurse[asset.symbol])
                aktueller_wert = asset.stueckzahl * preis
                if asset not in aktive_assets and asset.stueckzahl > 0:
                    ledger.sell_all(portfolio, asset, preis, datum, reason="rebalancing_inactive")
                elif asset in aktive_assets and aktueller_wert > targets[asset.symbol]:
                    verkaufswert = aktueller_wert - targets[asset.symbol]
                    ledger.sell_shares(portfolio, asset, verkaufswert / preis, preis, datum, reason="rebalancing")

            for asset in aktive_assets:
                preis = float(aktuelle_kurse[asset.symbol])
                aktueller_wert = asset.stueckzahl * preis
                zielwert = targets[asset.symbol]
                if aktueller_wert < zielwert and portfolio.cash > 0:
                    budget = min(zielwert - aktueller_wert, portfolio.cash)
                    portfolio.cash -= budget
                    ledger.buy_with_budget(asset, budget, preis, datum, reason="rebalancing")
            return

        portfolio.cash = 0
        for asset in aktive_assets:
            ziel_faktor = asset.ziel_anteil / summe_ziel_anteile
            soll_wert_euro = gesamtwert * ziel_faktor
            asset.stueckzahl = soll_wert_euro / float(aktuelle_kurse[asset.symbol])

        for asset in portfolio.assets:
            if not getattr(asset, "aktiv", True):
                asset.stueckzahl = 0

    @staticmethod
    def execute_stop_loss(
        portfolio,
        asset,
        kurs_heute,
        state,
        ausstieg_prozent=15,
        wiedereinstieg_prozent=0,
        ledger=None,
        datum=None,
    ):
        kurs = float(kurs_heute)
        ausstieg_faktor = 1 - (float(ausstieg_prozent) / 100)
        wiedereinstieg_faktor = 1 + (float(wiedereinstieg_prozent) / 100)

        if not getattr(asset, "aktiv", True):
            if asset.sold_preis is not None and kurs >= asset.sold_preis * wiedereinstieg_faktor:
                budget = min(asset.sold_erloes or 0, portfolio.cash)
                if ledger is not None and datum is not None:
                    portfolio.cash -= budget
                    ledger.buy_with_budget(asset, budget, kurs, datum, reason="stop_loss_reentry")
                else:
                    asset.stueckzahl = budget / kurs
                    portfolio.cash -= budget
                asset.aktiv = True
                asset.peak_preis = kurs
                asset.sold_preis = None
                asset.sold_erloes = None
            return

        if asset.peak_preis is None:
            asset.peak_preis = kurs
        if kurs > asset.peak_preis:
            asset.peak_preis = kurs

        stop_limit = asset.peak_preis * ausstieg_faktor
        if asset.stueckzahl > 0 and kurs < stop_limit:
            if ledger is not None and datum is not None:
                result = ledger.sell_all(portfolio, asset, kurs, datum, reason="stop_loss")
                erloes = result["net"]
            else:
                erloes = asset.stueckzahl * kurs
                portfolio.cash += erloes
                asset.stueckzahl = 0
            asset.aktiv = False
            asset.peak_preis = None
            asset.sold_preis = kurs
            asset.sold_erloes = erloes
            state.setdefault(asset.symbol, set()).add("gesperrt")

    @staticmethod
    def Thesaurirend(portfolio, kurse, state, aktive_regeln, ledger=None, datum=None):
        for asset in portfolio.assets:
            if not getattr(asset, "aktiv", True):
                continue
            if asset.regeln.get("dividenden_ziel") is not None and "dividenden_umschichten" in aktive_regeln:
                continue

            div_spalte = f"{asset.symbol}_div"
            if div_spalte not in kurse:
                continue

            div_betrag = float(kurse[div_spalte])
            if math.isnan(div_betrag) or div_betrag <= 0:
                continue

            div_gesamt = asset.stueckzahl * div_betrag
            net = ledger.process_dividend(datum, div_gesamt)["net"] if ledger is not None and datum is not None else div_gesamt
            if ledger is not None and datum is not None:
                ledger.buy_with_budget(asset, net, float(kurse[asset.symbol]), datum, reason="dividend_reinvest")
            else:
                asset.stueckzahl += div_gesamt / float(kurse[asset.symbol])
            asset.gesamt_dividenden += div_gesamt

    @staticmethod
    def dividentenUmschichten(portfolio, kurse, state, ledger=None, datum=None):
        symbols = {asset.symbol for asset in portfolio.assets}
        for asset in portfolio.assets:
            if not getattr(asset, "aktiv", True):
                continue

            ziel = asset.regeln.get("dividenden_ziel")
            if ziel is None:
                continue

            summe = sum(ziel.values())
            if summe != 100:
                raise ValueError(f"Dividendenziel fuer {asset.symbol} ergibt {summe}% statt 100%")

            for ziel_symbol in ziel:
                if ziel_symbol not in symbols:
                    raise ValueError(f"Dividendenziel {ziel_symbol} ist nicht im Portfolio")

            div_spalte = f"{asset.symbol}_div"
            if div_spalte not in kurse:
                continue

            div_betrag = float(kurse[div_spalte])
            if math.isnan(div_betrag) or div_betrag <= 0:
                continue

            div_gesamt = asset.stueckzahl * div_betrag
            net = ledger.process_dividend(datum, div_gesamt)["net"] if ledger is not None and datum is not None else div_gesamt
            for ziel_symbol, prozent in ziel.items():
                anteil = net * (prozent / 100)
                ziel_asset = next(a for a in portfolio.assets if a.symbol == ziel_symbol)
                if ledger is not None and datum is not None:
                    ledger.buy_with_budget(ziel_asset, anteil, float(kurse[ziel_symbol]), datum, reason="dividend_redirect")
                else:
                    ziel_asset.stueckzahl += anteil / float(kurse[ziel_symbol])

            asset.gesamt_dividenden += div_gesamt

    @staticmethod
    def sparplan(portfolio, betrag, kurse, ledger=None, datum=None):
        if betrag <= 0:
            return

        aktive_assets = [asset for asset in portfolio.assets if getattr(asset, "aktiv", True)]
        summe_anteile = sum(asset.ziel_anteil for asset in aktive_assets)
        if not aktive_assets or not summe_anteile:
            portfolio.cash += betrag
            return

        for asset in aktive_assets:
            anteil = betrag * (asset.ziel_anteil / summe_anteile)
            if ledger is not None and datum is not None:
                ledger.buy_with_budget(asset, anteil, float(kurse[asset.symbol]), datum, reason="sparplan")
            else:
                asset.stueckzahl += anteil / float(kurse[asset.symbol])

    @staticmethod
    def schwellwert_umschichtung(portfolio, kurse, state, schwelle, von, zu, prozent, ledger=None, datum=None):
        if not schwelle or not von or not zu or not prozent:
            return
        if getattr(portfolio, "schwellwert_gefeuert", False):
            return
        if "umgeschichtet" in state.get("PORTFOLIO", set()):
            return

        gesamtwert = sum(asset.stueckzahl * float(kurse[asset.symbol]) for asset in portfolio.assets) + portfolio.cash
        if gesamtwert < schwelle:
            return

        von_asset = next((asset for asset in portfolio.assets if asset.symbol == von), None)
        zu_asset = next((asset for asset in portfolio.assets if asset.symbol == zu), None)
        if not von_asset or not zu_asset:
            raise ValueError(f"Schwellwert-Assets {von}/{zu} nicht im Portfolio")

        von_wert = von_asset.stueckzahl * float(kurse[von])
        umschicht = von_wert * (prozent / 100)
        if ledger is not None and datum is not None:
            before_cash = portfolio.cash
            ledger.sell_shares(portfolio, von_asset, umschicht / float(kurse[von]), float(kurse[von]), datum, reason="schwellwert")
            budget = max(portfolio.cash - before_cash, 0.0)
            portfolio.cash -= budget
            ledger.buy_with_budget(zu_asset, budget, float(kurse[zu]), datum, reason="schwellwert")
        else:
            von_asset.stueckzahl -= umschicht / float(kurse[von])
            zu_asset.stueckzahl += umschicht / float(kurse[zu])

        state.setdefault("PORTFOLIO", set()).add("umgeschichtet")
        state.setdefault("PORTFOLIO", set()).add("rebalancing_noetig")
        portfolio.schwellwert_gefeuert = True

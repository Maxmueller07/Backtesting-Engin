from Assets import Asset


class Portfolio:
        from Assets import Asset
        def __init__(self, start_cash,srebalacing):
                self.cash = start_cash
                self.assets = []
                self.historie = []
                self.rebalancing = srebalacing

        def add_asset(self, name, symbol, anteil,Wert,regeln = None):
               nues_asset = Asset(name, symbol, anteil,Wert)
               nues_asset.regeln = regeln or {}
               self.assets.append(nues_asset)

        def gesamt_wert(self):
                # Summe aus Cash + Wert aller Assets
                wert_assets = sum([a.wert() for a in self.assets])
                return self.cash + wert_assets

        def check_rebalancing(self):
                total = self.gesamt_wert()
                for a in self.assets:
                        aktueller_anteil = a.wert() / total

                        pass
        def check_antiel(self):
                gesamt_antiel = sum([a.ziel_anteil for a in self.assets])
                if gesamt_antiel != 100 :
                        print(f"Fehler: Die Anteile ergeben {gesamt_antiel}%. Sie müssen 100% ergeben!")
                        return False

                print("Checkbestanden: Anteil ergeben 100%")
                return True



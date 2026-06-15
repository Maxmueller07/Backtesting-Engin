from Assets import Asset


class Portfolio:
    def __init__(self, start_cash, srebalacing):
        self.cash = start_cash
        self.assets = []
        self.historie = []
        self.rebalancing = srebalacing

    def add_asset(self, name, symbol, anteil, Wert, regeln=None, waehrung=None, steuer_typ=None):
        neues_asset = Asset(name, symbol, anteil, Wert, waehrung=waehrung, steuer_typ=steuer_typ)
        neues_asset.regeln = regeln or {}
        self.assets.append(neues_asset)

    def gesamt_wert(self):
        wert_assets = sum(asset.wert() for asset in self.assets)
        return self.cash + wert_assets

    def check_rebalancing(self):
        total = self.gesamt_wert()
        if not total:
            return []
        return [
            {"symbol": asset.symbol, "aktueller_anteil": asset.wert() / total}
            for asset in self.assets
        ]

    def check_antiel(self):
        gesamt_anteil = sum(asset.ziel_anteil for asset in self.assets)
        return abs(gesamt_anteil - 100) < 1e-9

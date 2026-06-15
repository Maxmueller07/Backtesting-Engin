class Asset:
    def __init__(self, name, symbol, ziel_anteil, Wert, waehrung=None, steuer_typ=None):
        self.name = name
        self.symbol = symbol
        self.ziel_anteil = ziel_anteil
        self.waehrung = waehrung
        self.steuer_typ = steuer_typ
        self.stueckzahl = 0
        self.lots = []
        self.aktueller_preis = 0
        self.aktueller_postis = 0
        self.aktiv = True
        self.peak_preis = None
        self.sold_preis = None
        self.sold_erloes = None
        self.gesamt_dividenden = 0.0
        self.regeln = {}


    def wert(self):

        return self.stueckzahl * self.aktueller_preis

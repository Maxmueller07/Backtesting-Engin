from collections import defaultdict


DEFAULT_TRANSACTION_COSTS = {
    "aktiv": False,
    "ordergebuehr_fix": 0.0,
    "ordergebuehr_prozent": 0.0,
    "mindestgebuehr": 0.0,
    "maximalgebuehr": 0.0,
}

DEFAULT_TAX_CONFIG = {
    "aktiv": False,
    "land": "DE",
    "jahreseinkommen": 45000.0,
    "automatisch_aus_einkommen": True,
    "sparer_pauschbetrag": 1000.0,
    "kapitalertragsteuer": 25.0,
    "solidaritaetszuschlag": 5.5,
    "kirchensteuer": 0.0,
    "tax_loss_harvesting": False,
    "harvesting_schwelle_prozent": 5.0,
}


def _merge(defaults, values):
    merged = defaults.copy()
    if values:
        merged.update({k: v for k, v in values.items() if v is not None})
    return merged


def infer_tax_category(symbol, configured=None):
    if configured:
        return configured
    upper = str(symbol or "").upper()
    if upper.endswith("-USD") or upper.endswith("-EUR"):
        return "crypto"
    if any(token in upper for token in ("ETF", "EUNL", "IWDA", "VWRL", "VWCE", "SPY", "QQQ")):
        return "fonds_etf"
    return "aktie"


def estimate_personal_marginal_tax_rate(jahreseinkommen):
    """Approximate German marginal income tax rate for backtest modelling.

    This intentionally stays simple and transparent. Capital gains use the
    lower of this estimate and the flat 25% Abgeltungsteuer.
    """
    income = max(float(jahreseinkommen or 0.0), 0.0)
    if income <= 12096:
        return 0.0
    if income <= 17443:
        progress = (income - 12096) / (17443 - 12096)
        return 14.0 + progress * 10.0
    if income <= 68480:
        progress = (income - 17443) / (68480 - 17443)
        return 24.0 + progress * 18.0
    if income <= 277825:
        return 42.0
    return 45.0


class TradeLedger:
    def __init__(self, transaction_costs=None, tax_config=None):
        self.cost_config = _merge(DEFAULT_TRANSACTION_COSTS, transaction_costs)
        self.tax_config = _merge(DEFAULT_TAX_CONFIG, tax_config)
        self.tax_enabled = bool(self.tax_config.get("aktiv"))
        self.loss_pot_stock = 0.0
        self.loss_pot_general = 0.0
        self.years = defaultdict(self._new_year_state)
        self.transaction_costs_total = 0.0
        self.tax_paid_total = 0.0
        self.realized_gains_total = 0.0
        self.realized_losses_total = 0.0
        self.dividends_gross_total = 0.0
        self.dividends_net_total = 0.0
        self.harvested_losses_total = 0.0
        self.trade_count = 0

    def _new_year_state(self):
        return {
            "allowance_remaining": float(self.tax_config.get("sparer_pauschbetrag", 1000.0)),
            "tax_paid": 0.0,
            "realized_gains": 0.0,
            "realized_losses": 0.0,
            "dividends_gross": 0.0,
            "dividends_net": 0.0,
            "harvested_losses": 0.0,
        }

    def _year(self, date):
        return self.years[int(date.year)]

    def effective_tax_rate(self):
        flat_tax = float(self.tax_config.get("kapitalertragsteuer", 25.0))
        personal_tax = estimate_personal_marginal_tax_rate(self.tax_config.get("jahreseinkommen", 45000.0))
        tax_percent = min(flat_tax, personal_tax) if self.tax_config.get("automatisch_aus_einkommen", True) else flat_tax
        tax = tax_percent / 100
        soli = float(self.tax_config.get("solidaritaetszuschlag", 5.5)) / 100
        church = float(self.tax_config.get("kirchensteuer", 0.0)) / 100
        return tax * (1 + soli + church)

    def order_fee(self, order_value):
        value = max(float(order_value), 0.0)
        if not self.cost_config.get("aktiv") or value <= 0:
            return 0.0
        fee = float(self.cost_config.get("ordergebuehr_fix", 0.0))
        fee += value * (float(self.cost_config.get("ordergebuehr_prozent", 0.0)) / 100)
        min_fee = float(self.cost_config.get("mindestgebuehr", 0.0))
        max_fee = float(self.cost_config.get("maximalgebuehr", 0.0))
        if min_fee > 0:
            fee = max(fee, min_fee)
        if max_fee > 0:
            fee = min(fee, max_fee)
        return min(fee, value)

    def buy_with_budget(self, asset, budget, price, date, reason="buy"):
        budget = max(float(budget), 0.0)
        price = float(price)
        if budget <= 0 or price <= 0:
            return {"shares": 0.0, "fee": 0.0, "invested": 0.0}

        fee = self.order_fee(budget)
        invested = max(budget - fee, 0.0)
        shares = invested / price if invested > 0 else 0.0
        if shares > 0:
            asset.stueckzahl += shares
            asset.lots.append({"shares": shares, "cost": budget})
            self.trade_count += 1
        self.transaction_costs_total += fee
        return {"shares": shares, "fee": fee, "invested": invested, "reason": reason}

    def sell_shares(self, portfolio, asset, shares, price, date, reason="sell"):
        shares = min(max(float(shares), 0.0), float(asset.stueckzahl))
        price = float(price)
        if shares <= 0 or price <= 0:
            return {"net": 0.0, "tax": 0.0, "fee": 0.0, "gain": 0.0}

        gross = shares * price
        fee = self.order_fee(gross)
        proceeds = gross - fee
        cost_basis = self._consume_lots(asset, shares, price)
        gain = proceeds - cost_basis
        tax = self.process_realized_gain(date, gain, infer_tax_category(asset.symbol, getattr(asset, "steuer_typ", None)), reason)
        net = proceeds - tax

        asset.stueckzahl -= shares
        if asset.stueckzahl < 1e-10:
            asset.stueckzahl = 0.0
        portfolio.cash += net
        self.transaction_costs_total += fee
        self.tax_paid_total += tax
        self.trade_count += 1
        return {"gross": gross, "net": net, "tax": tax, "fee": fee, "gain": gain, "reason": reason}

    def sell_all(self, portfolio, asset, price, date, reason="sell_all"):
        return self.sell_shares(portfolio, asset, asset.stueckzahl, price, date, reason)

    def _consume_lots(self, asset, shares, price):
        remaining = shares
        cost_basis = 0.0
        lots = []

        if not getattr(asset, "lots", None):
            return shares * float(price)

        for lot in asset.lots:
            if remaining <= 1e-12:
                lots.append(lot)
                continue
            lot_shares = float(lot["shares"])
            lot_cost = float(lot["cost"])
            if lot_shares <= remaining + 1e-12:
                cost_basis += lot_cost
                remaining -= lot_shares
            else:
                ratio = remaining / lot_shares
                cost_basis += lot_cost * ratio
                lots.append({"shares": lot_shares - remaining, "cost": lot_cost * (1 - ratio)})
                remaining = 0.0

        asset.lots = lots
        return cost_basis

    def process_dividend(self, date, gross_amount):
        gross = max(float(gross_amount), 0.0)
        if gross <= 0:
            return {"gross": 0.0, "net": 0.0, "tax": 0.0}

        year = self._year(date)
        self.dividends_gross_total += gross
        year["dividends_gross"] += gross
        tax = self._tax_positive_income(date, gross, "general")
        net = gross - tax
        self.dividends_net_total += net
        year["dividends_net"] += net
        self.tax_paid_total += tax
        return {"gross": gross, "net": net, "tax": tax}

    def process_realized_gain(self, date, gain, category, reason="sell"):
        year = self._year(date)
        if gain < 0:
            loss = abs(float(gain))
            if category == "aktie":
                self.loss_pot_stock += loss
            else:
                self.loss_pot_general += loss
            self.realized_losses_total += loss
            year["realized_losses"] += loss
            if reason == "tax_loss_harvest":
                self.harvested_losses_total += loss
                year["harvested_losses"] += loss
            return 0.0

        gain = max(float(gain), 0.0)
        self.realized_gains_total += gain
        year["realized_gains"] += gain
        if not self.tax_enabled:
            return 0.0
        return self._tax_positive_income(date, gain, "stock" if category == "aktie" else "general")

    def _tax_positive_income(self, date, amount, pot_type):
        if not self.tax_enabled:
            return 0.0

        taxable = float(amount)
        if pot_type == "stock":
            offset = min(taxable, self.loss_pot_stock)
            self.loss_pot_stock -= offset
            taxable -= offset
        else:
            offset = min(taxable, self.loss_pot_general)
            self.loss_pot_general -= offset
            taxable -= offset

        year = self._year(date)
        allowance = min(taxable, year["allowance_remaining"])
        year["allowance_remaining"] -= allowance
        taxable -= allowance

        tax = max(taxable, 0.0) * self.effective_tax_rate()
        year["tax_paid"] += tax
        return tax

    def maybe_harvest_losses(self, portfolio, prices, date):
        if not self.tax_enabled or not self.tax_config.get("tax_loss_harvesting"):
            return
        threshold = float(self.tax_config.get("harvesting_schwelle_prozent", 5.0))
        for asset in portfolio.assets:
            if not getattr(asset, "aktiv", True) or asset.stueckzahl <= 0:
                continue
            if infer_tax_category(asset.symbol, getattr(asset, "steuer_typ", None)) != "aktie":
                continue
            cost_basis = sum(float(lot["cost"]) for lot in getattr(asset, "lots", []))
            if cost_basis <= 0:
                continue
            price = float(prices[asset.symbol])
            current_value = asset.stueckzahl * price
            unrealized_loss = cost_basis - current_value
            loss_pct = (unrealized_loss / cost_basis) * 100
            if loss_pct < threshold:
                continue
            before_cash = portfolio.cash
            sell_result = self.sell_all(portfolio, asset, price, date, reason="tax_loss_harvest")
            budget = min(portfolio.cash - before_cash, portfolio.cash)
            portfolio.cash -= budget
            self.buy_with_budget(asset, budget, price, date, reason="tax_loss_harvest_rebuy")
            asset.peak_preis = price
            asset.aktiv = True
            asset.sold_preis = None
            asset.sold_erloes = None

    def summary(self):
        return {
            "aktiv": self.tax_enabled,
            "sparer_pauschbetrag": float(self.tax_config.get("sparer_pauschbetrag", 1000.0)),
            "jahreseinkommen": float(self.tax_config.get("jahreseinkommen", 45000.0)),
            "persoenlicher_grenzsteuersatz": estimate_personal_marginal_tax_rate(self.tax_config.get("jahreseinkommen", 45000.0)),
            "verwendeter_kapitalsteuersatz": min(
                float(self.tax_config.get("kapitalertragsteuer", 25.0)),
                estimate_personal_marginal_tax_rate(self.tax_config.get("jahreseinkommen", 45000.0)),
            ) if self.tax_config.get("automatisch_aus_einkommen", True) else float(self.tax_config.get("kapitalertragsteuer", 25.0)),
            "effektiver_steuersatz": self.effective_tax_rate() * 100 if self.tax_enabled else 0.0,
            "steuern_gezahlt": float(self.tax_paid_total),
            "transaktionskosten": float(self.transaction_costs_total),
            "realisierte_gewinne": float(self.realized_gains_total),
            "realisierte_verluste": float(self.realized_losses_total),
            "dividenden_brutto": float(self.dividends_gross_total),
            "dividenden_netto": float(self.dividends_net_total),
            "verlusttopf_aktien": float(self.loss_pot_stock),
            "verlusttopf_allgemein": float(self.loss_pot_general),
            "tax_loss_harvesting_verluste": float(self.harvested_losses_total),
            "anzahl_trades": int(self.trade_count),
            "jahre": {str(year): state for year, state in sorted(self.years.items())},
        }

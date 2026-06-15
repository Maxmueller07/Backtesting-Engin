import unittest
from unittest.mock import patch

import pandas as pd

from main import simuliere
from Protfolio import Portfolio


RULES = ["Stop_Loss", "rebalancing", "Thesaurirend", "dividenden_umschichten", "sparblan", "schwellwert"]


def make_portfolio(div_targets=False):
    portfolio = Portfolio(1000, True)
    reg_a = {"dividenden_ziel": {"BBB": 100}} if div_targets else {}
    reg_b = {"dividenden_ziel": {"AAA": 100}} if div_targets else {}
    portfolio.add_asset("Asset A", "AAA", 60, 0, regeln=reg_a)
    portfolio.add_asset("Asset B", "BBB", 40, 0, regeln=reg_b)
    return portfolio


class FinancialCoreTest(unittest.TestCase):
    def combo_prices(self, symbol):
        index = pd.bdate_range("2024-01-01", "2024-03-15")
        if symbol == "AAA":
            values = []
            for i in range(len(index)):
                if i < 10:
                    values.append(100 + i * 2)
                elif i < 20:
                    values.append(70 + i * 0.5)
                else:
                    values.append(82 + i * 1.2)
        else:
            values = [50 + i * 0.35 for i in range(len(index))]

        dividends = [0.0] * len(index)
        for i, date in enumerate(index):
            if date.day == 1:
                dividends[i] = 0.25 if symbol == "AAA" else 0.1
        return pd.DataFrame({"Close": values, "Dividends": dividends}, index=index)

    def test_all_rule_combinations_keep_daily_history_consistent(self):
        with patch("market_data.yf.download", side_effect=lambda symbol, *args, **kwargs: self.combo_prices(symbol)):
            for mask in range(1 << len(RULES)):
                active = [RULES[i] for i in range(len(RULES)) if mask & (1 << i)]
                portfolio = make_portfolio(div_targets="dividenden_umschichten" in active)

                result = simuliere(
                    portfolio,
                    active,
                    "2024-01-01",
                    "2024-03-15",
                    intervall=5,
                    sp_start=100,
                    schwellwert_config={"schwelle": 900, "von": "AAA", "zu": "BBB", "prozent": 20},
                    stop_loss_config={"ausstieg_prozent": 15, "wiedereinstieg_prozent": 0},
                    sparplan_dynamisierung=0.10,
                    sparplan_limit=2000,
                )

                history = result["historie"]
                asset_cols = [col for col in history.columns if col.endswith("_wert")]
                daily_sum = history[asset_cols].sum(axis=1) + history["Cash"]
                max_diff = (daily_sum - history["Gesamtwert"]).abs().max()
                self.assertLess(max_diff, 1e-6, msg=f"Inkonsistente Historie fuer {active}")

    def test_sparplan_uses_first_available_trading_day_and_dynamisierung(self):
        index = pd.bdate_range("2024-05-30", "2024-07-10")

        def prices(symbol, *args, **kwargs):
            return pd.DataFrame({"Close": [100.0] * len(index), "Dividends": [0.0] * len(index)}, index=index)

        portfolio = Portfolio(1000, True)
        portfolio.add_asset("Asset A", "AAA", 100, 0)

        with patch("market_data.yf.download", side_effect=prices):
            result = simuliere(
                portfolio,
                ["sparblan"],
                "2024-05-30",
                "2024-07-10",
                sp_start=100,
                sparplan_dynamisierung=0.10,
                sparplan_limit=1000,
            )

        self.assertEqual(result["cashflows"][:4], [
            ("2024-05-30", -1000.0),
            ("2024-05-30", -100.0),
            ("2024-06-03", -110.00000000000001),
            ("2024-07-01", -121.00000000000003),
        ])
        self.assertAlmostEqual(result["gesamt_eingezahlt"], 1331.0)

    def test_stop_loss_exit_and_reentry_are_independently_configurable(self):
        index = pd.bdate_range("2024-01-01", periods=5)

        def prices(symbol, *args, **kwargs):
            return pd.DataFrame({"Close": [100.0, 120.0, 107.0, 108.0, 111.0], "Dividends": [0.0] * 5}, index=index)

        with patch("market_data.yf.download", side_effect=prices):
            low_reentry = Portfolio(1000, True)
            low_reentry.add_asset("Asset A", "AAA", 100, 0)
            simuliere(
                low_reentry,
                ["Stop_Loss"],
                "2024-01-01",
                "2024-01-08",
                stop_loss_config={"ausstieg_prozent": 10, "wiedereinstieg_prozent": 3},
            )

            high_reentry = Portfolio(1000, True)
            high_reentry.add_asset("Asset A", "AAA", 100, 0)
            simuliere(
                high_reentry,
                ["Stop_Loss"],
                "2024-01-01",
                "2024-01-08",
                stop_loss_config={"ausstieg_prozent": 10, "wiedereinstieg_prozent": 10},
            )

        self.assertTrue(low_reentry.assets[0].aktiv)
        self.assertFalse(high_reentry.assets[0].aktiv)
        self.assertGreater(high_reentry.cash, 0)

    def test_transaction_costs_and_taxes_reduce_realized_rebalance_gain(self):
        index = pd.bdate_range("2024-01-01", periods=3)

        def prices(symbol, *args, **kwargs):
            if symbol == "AAA":
                close = [100.0, 200.0, 200.0]
            else:
                close = [100.0, 100.0, 100.0]
            return pd.DataFrame({"Close": close, "Dividends": [0.0] * len(index)}, index=index)

        with patch("market_data.yf.download", side_effect=prices):
            plain = Portfolio(1000, True)
            plain.add_asset("Winner", "AAA", 50, 0)
            plain.add_asset("Flat", "BBB", 50, 0)
            plain_result = simuliere(plain, ["rebalancing"], "2024-01-01", "2024-01-04", intervall=1, sp_start=0)

        with patch("market_data.yf.download", side_effect=prices):
            taxed = Portfolio(1000, True)
            taxed.add_asset("Winner", "AAA", 50, 0, steuer_typ="aktie")
            taxed.add_asset("Flat", "BBB", 50, 0, steuer_typ="aktie")
            taxed_result = simuliere(
                taxed,
                ["rebalancing"],
                "2024-01-01",
                "2024-01-04",
                intervall=1,
                sp_start=0,
                transaktionskosten_config={"aktiv": True, "ordergebuehr_fix": 1.0, "ordergebuehr_prozent": 0.0},
                steuer_config={"aktiv": True, "sparer_pauschbetrag": 0.0, "kapitalertragsteuer": 25.0, "solidaritaetszuschlag": 5.5},
            )

        self.assertGreater(taxed_result["steuer_report"]["steuern_gezahlt"], 0)
        self.assertGreater(taxed_result["steuer_report"]["transaktionskosten"], 0)
        self.assertLess(taxed_result["gesamtwert"], plain_result["gesamtwert"])

    def test_tax_loss_harvesting_realizes_stock_loss_pot(self):
        index = pd.bdate_range("2024-12-27", periods=3)

        def prices(symbol, *args, **kwargs):
            return pd.DataFrame({"Close": [100.0, 90.0, 80.0], "Dividends": [0.0] * len(index)}, index=index)

        portfolio = Portfolio(1000, True)
        portfolio.add_asset("Loser", "AAA", 100, 0, steuer_typ="aktie")

        with patch("market_data.yf.download", side_effect=prices):
            result = simuliere(
                portfolio,
                [],
                "2024-12-27",
                "2025-01-02",
                sp_start=0,
                steuer_config={
                    "aktiv": True,
                    "sparer_pauschbetrag": 0.0,
                    "tax_loss_harvesting": True,
                    "harvesting_schwelle_prozent": 5.0,
                },
            )

        report = result["steuer_report"]
        self.assertAlmostEqual(report["verlusttopf_aktien"], 200.0)
        self.assertAlmostEqual(report["tax_loss_harvesting_verluste"], 200.0)
        self.assertEqual(portfolio.assets[0].stueckzahl, 10.0)


if __name__ == "__main__":
    unittest.main()

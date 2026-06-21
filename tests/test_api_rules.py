import unittest

from fastapi.testclient import TestClient

import api
import ai_rule_builder
from indicator_registry import IndicatorRegistry


RISK_ROTATION_PROMPT = """
Erstelle eine Backtesting-Regel fuer mein Portfolio mit den Assets AAPL, SPY, GLD und TLT.

Die Regel soll eine Risk-Off-Marktrotation abbilden:

Wenn der Market-Rotation-Score unter 35 faellt UND AAPL unter seinem 200-Tage-Durchschnitt liegt UND die 30-Tage-Volatilitaet von AAPL ueber 28 Prozent liegt, dann soll das System 25 Prozent meiner AAPL-Position verkaufen.

Von dem Verkaufserloes sollen 60 Prozent in GLD und 40 Prozent in TLT investiert werden.

Die Regel darf hoechstens einmal alle 30 Tage ausloesen und insgesamt maximal 4-mal im gesamten Backtest.

Wenn der Market-Rotation-Score spaeter wieder ueber 65 steigt UND AAPL wieder ueber seinem 200-Tage-Durchschnitt liegt, dann soll die Regel eine Risk-On-Rotation machen: Verkaufe 50 Prozent der GLD-Position und investiere den Erloes zurueck in AAPL.

Nutze nur historische Daten bis zum jeweiligen Backtest-Tag. Vermeide Look-ahead Bias. Die Regel ist nur fuer historische Simulation gedacht und keine Anlageberatung.
"""

PROFIT_PROTECTION_PROMPT = """
Erstelle eine komplexe Backtesting-Regel fuer mein Portfolio mit den Assets AAPL, MSFT, NVDA, SPY, GLD, TLT und Cash.

Die Regel soll eine Gewinnsicherungs- und Trendbruch-Strategie abbilden.

Wenn eines meiner Wachstumsassets AAPL, MSFT oder NVDA seit dem Start des Backtests mehr als 45 Prozent Gewinn erzielt hat UND dieses Asset gleichzeitig unter seinen 100-Tage-Durchschnitt faellt UND die 30-Tage-Volatilitaet dieses Assets ueber 30 Prozent liegt, dann sichere Gewinne ab.

In diesem Fall soll das System 35 Prozent der betroffenen Position verkaufen.

Der Verkaufserloes soll so verteilt werden:
- 40 Prozent in SPY,
- 35 Prozent in TLT,
- 25 Prozent in GLD.

Diese Regel soll fuer AAPL, MSFT und NVDA jeweils separat gelten. Wenn mehrere Assets am selben Tag die Bedingungen erfuellen, darf die Regel fuer jedes betroffene Asset ausloesen, aber insgesamt duerfen an einem Tag maximal 2 Positionen umgeschichtet werden.

Die Regel darf pro Asset hoechstens einmal alle 45 Tage ausloesen und pro Asset maximal 3-mal im gesamten Backtest.

Zusaetzliche Schutzbedingung:
Wenn SPY selbst unter seinem 200-Tage-Durchschnitt liegt, dann soll der Verkaufserloes nicht in SPY investiert werden. In diesem Fall soll der SPY-Anteil stattdessen zu gleichen Teilen auf GLD und TLT verteilt werden.

Reentry-Regel:
Wenn ein zuvor reduziertes Wachstumsasset spaeter wieder ueber seinem 100-Tage-Durchschnitt liegt UND seine 30-Tage-Volatilitaet unter 22 Prozent faellt UND SPY ueber seinem 200-Tage-Durchschnitt liegt, dann soll das System 20 Prozent der verfuegbaren Cash-Position nutzen, um dieses Asset zurueckzukaufen.

Nutze nur historische Daten bis zum jeweiligen Backtest-Tag. Vermeide Look-ahead Bias. Fuehre keine echten Trades aus. Erstelle nur sichere Backtesting-Regeln. Wenn diese Logik zu komplex fuer eine einzelne Regel ist, teile sie in mehrere sichere Teilregeln auf.
"""

DEFENSIVE_REALLOCATION_PROMPT = """
Erstelle eine Backtesting-Regel fuer mein Portfolio mit den Assets AAPL, MSFT, SPY, GLD, TLT und Cash.

Die Regel soll eine defensive Umschichtung bei schwachem Aktienmarkt abbilden.

Wenn SPY unter seinem 200-Tage-Durchschnitt liegt UND die 30-Tage-Volatilitaet von SPY ueber 24 Prozent liegt UND AAPL ebenfalls unter seinem 100-Tage-Durchschnitt liegt, dann soll das System 30 Prozent meiner AAPL-Position verkaufen.

Der Verkaufserloes soll so verteilt werden:

* 50 Prozent in GLD
* 30 Prozent in TLT
* 20 Prozent als Cash behalten

Die Regel darf hoechstens einmal alle 30 Tage ausloesen und maximal 4-mal im gesamten Backtest.

Wenn SPY spaeter wieder ueber seinem 200-Tage-Durchschnitt liegt UND die 30-Tage-Volatilitaet von SPY unter 18 Prozent faellt, dann soll das System 25 Prozent des verfuegbaren Cash nutzen, um AAPL zurueckzukaufen.

Nutze nur historische Daten bis zum jeweiligen Backtest-Tag. Vermeide Look-ahead Bias. Fuehre keine echten Trades aus. Erstelle nur sichere Backtesting-Regeln. Wenn diese Logik zu komplex fuer eine einzelne Regel ist, teile sie in mehrere sichere Teilregeln auf.
"""

SIMPLE_SELL_TO_CASH_PROMPT = """
Erstelle eine Backtesting-Regel fuer mein Portfolio mit AAPL und Cash.

Wenn AAPL unter seinen 200-Tage-Durchschnitt faellt, dann verkaufe 25 Prozent meiner AAPL-Position und halte den Erloes als Cash.

Die Regel darf maximal einmal alle 30 Tage ausloesen und ist nur fuer historische Backtests gedacht.
"""

SIMPLE_CASH_TO_GLD_PROMPT = """
Erstelle eine Backtesting-Regel fuer mein Portfolio mit SPY, GLD und Cash.

Wenn SPY unter seinen 100-Tage-Durchschnitt faellt, dann nutze 30 Prozent meines verfuegbaren Cash, um GLD zu kaufen.

Die Regel darf maximal einmal alle 20 Tage ausloesen und soll keine echten Trades ausfuehren.
"""

SIMPLE_PROFIT_TO_GLD_PROMPT = """
Erstelle eine Backtesting-Regel fuer mein Portfolio mit AAPL, GLD und Cash.

Wenn AAPL mehr als 20 Prozent Gewinn seit Start des Backtests gemacht hat, dann verkaufe 15 Prozent meiner AAPL-Position und kaufe mit dem Erloes GLD.

Die Regel darf maximal 2-mal im gesamten Backtest ausloesen und dient nur der historischen Simulation.
"""

SIMPLE_PRICE_TO_GLD_PROMPT = """
Erstelle eine sehr einfache Backtesting-Testregel fuer mein Portfolio mit AAPL und GLD.

Wenn der AAPL-Kurs gr\u00f6\u00dfer als 100% der GLD-Position ist, dann verkaufe 50 Prozent meiner AAPL-Position und kaufe mit dem gesamten Verkaufserloes GLD.

Die Regel darf maximal 5-mal im gesamten Backtest ausloesen.
"""

SELF_HEALING_ENTROPY_PROMPT = """
If the 30-day entropy of AAPL is above 0.75, sell 20% of AAPL and buy GLD.
"""

SELF_HEALING_CASES = [
    (
        "rsi",
        "If the 14-day RSI of AAPL is below 30, use 25% of my cash to buy AAPL.",
        ["AAPL", "CASH"],
        "<",
        30,
        {"asset": "AAPL", "window": 14},
        "buy_with_cash_percent",
    ),
    (
        "correlation",
        "If the 90-day correlation between SPY and GLD is below -0.2, sell 20% SPY and buy GLD.",
        ["SPY", "GLD"],
        "<",
        -0.2,
        {"asset_a": "SPY", "asset_b": "GLD", "window": 90},
        "transfer_position_percent",
    ),
    (
        "macd",
        "If the MACD histogram of AAPL is below 0, sell 15% AAPL.",
        ["AAPL", "GLD"],
        "<",
        0,
        {"asset": "AAPL", "fast_window": 12, "slow_window": 26, "signal_window": 9, "output": "histogram"},
        "sell_position_percent",
    ),
    (
        "z_score",
        "If the 30-day z-score of AAPL is above 2, sell 10% AAPL.",
        ["AAPL", "GLD"],
        ">",
        2,
        {"asset": "AAPL", "window": 30},
        "sell_position_percent",
    ),
    (
        "moving_average_slope",
        "If the 50-day moving average slope of AAPL is negative, sell 10% AAPL.",
        ["AAPL", "GLD"],
        "<",
        0,
        {"asset": "AAPL", "window": 50, "slope_window": 10},
        "sell_position_percent",
    ),
    (
        "momentum",
        "If the 90-day momentum of AAPL is above 15%, buy AAPL with 20% cash.",
        ["AAPL", "CASH"],
        ">",
        0.15,
        {"asset": "AAPL", "window": 90},
        "buy_with_cash_percent",
    ),
]


class RuleApiTest(unittest.TestCase):
    def setUp(self):
        api.AGENT_CALLS.clear()
        ai_rule_builder._CACHE.clear()
        IndicatorRegistry.clear_dynamic_indicators()
        self.client = TestClient(api.app)

    def tearDown(self):
        api.app.dependency_overrides.clear()
        api.AGENT_CALLS.clear()
        ai_rule_builder._CACHE.clear()
        IndicatorRegistry.clear_dynamic_indicators()

    def authenticate(self):
        api.app.dependency_overrides[api.get_current_user] = lambda: {"user_id": 1, "username": "tester"}

    def test_rules_build_requires_login(self):
        response = self.client.post("/rules/build", json={"natural_language_rule": "Buy gold when market rotation is above 70."})

        self.assertIn(response.status_code, (401, 403))

    def test_rules_build_returns_deterministic_rule(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": "Buy gold when the market rotation score is above 70. Use 20% of my Apple position.",
                "portfolio_symbols": ["AAPL", "GLD", "SPY"],
                "base_currency": "EUR",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["agent"], "langgraph_rule_builder")
        self.assertEqual(data["audit"]["status"], "ok")
        self.assertEqual(data["rule"]["condition"]["indicator"], "market_rotation_score")
        self.assertEqual(data["rule"]["actions"][0]["type"], "transfer_position_percent")
        self.assertEqual(data["rule"]["actions"][0]["from_asset"], "AAPL")
        self.assertEqual(data["rule"]["actions"][0]["to_asset"], "GLD")

    def test_rules_build_keeps_drawdown_threshold_window_and_action_percent_separate(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": "If Apple drawdown is above 20% over 100 days, then sell 40% of Apple.",
                "portfolio_symbols": ["AAPL", "MSFT"],
                "base_currency": "EUR",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["rule"]["condition"]["indicator"], "drawdown")
        self.assertEqual(data["rule"]["condition"]["value"], 20)
        self.assertEqual(data["rule"]["condition"]["params"]["window"], 100)
        self.assertEqual(data["rule"]["actions"][0]["type"], "sell_position_percent")
        self.assertEqual(data["rule"]["actions"][0]["asset"], "AAPL")
        self.assertEqual(data["rule"]["actions"][0]["percent"], 40)

    def test_rules_build_can_request_new_asset_approval(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": "If Apple drawdown is above 20% over 100 days, then sell 40% of Apple.",
                "portfolio_symbols": ["MSFT"],
                "base_currency": "EUR",
                "new_asset_mode": "ask",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["requires_asset_approval"])
        self.assertEqual(data["new_assets"][0]["symbol"], "AAPL")
        self.assertEqual(data["new_assets"][0]["anteil"], 0)
        self.assertEqual(data["rule"]["condition"]["params"]["asset"], "AAPL")

    def test_rules_build_can_soft_approve_new_crypto_asset(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": "If Apple drawdown is above 20% over 100 days, then buy Bitcoin with 30% cash.",
                "portfolio_symbols": [],
                "base_currency": "EUR",
                "new_asset_mode": "soft_approve",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        symbols = {asset["symbol"] for asset in data["new_assets"]}
        self.assertEqual(data["status"], "ok")
        self.assertFalse(data["requires_asset_approval"])
        self.assertIn("AAPL", symbols)
        self.assertIn("BTC-USD", symbols)
        self.assertEqual(data["rule"]["actions"][0]["asset"], "BTC-USD")

    def test_rules_build_returns_risk_rotation_strategy_bundle(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": RISK_ROTATION_PROMPT,
                "portfolio_symbols": ["AAPL", "SPY", "GLD", "TLT"],
                "base_currency": "EUR",
                "new_asset_mode": "portfolio_only",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["rule_count"], 2)
        risk_off, risk_on = data["rules"]
        self.assertEqual(risk_off["condition"]["indicator"], "all")
        self.assertEqual(risk_off["execution"]["cooldown_days"], 30)
        self.assertEqual(risk_off["execution"]["max_triggers"], 4)
        self.assertEqual(risk_off["execution"]["group_id"], "risk_rotation_aapl")
        self.assertEqual(risk_off["execution"]["group_max_triggers"], 4)
        self.assertEqual(risk_off["execution"]["group_cooldown_days"], 30)
        self.assertEqual(risk_off["condition"]["params"]["conditions"][0]["params"]["defensive_proxy"], ["GLD", "TLT"])
        self.assertEqual(risk_off["actions"][0]["type"], "split_transfer_position_percent")
        self.assertEqual(risk_off["actions"][0]["from_asset"], "AAPL")
        self.assertEqual(risk_off["actions"][0]["percent"], 25)
        self.assertEqual(risk_off["actions"][0]["allocations"], [{"asset": "GLD", "percent": 60}, {"asset": "TLT", "percent": 40}])
        self.assertEqual(risk_on["actions"][0]["type"], "transfer_position_percent")
        self.assertEqual(risk_on["actions"][0]["from_asset"], "GLD")
        self.assertEqual(risk_on["actions"][0]["to_asset"], "AAPL")
        self.assertEqual(risk_on["actions"][0]["percent"], 50)
        self.assertEqual(risk_on["execution"]["group_id"], "risk_rotation_aapl")

    def test_rules_build_returns_profit_protection_strategy_bundle(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": PROFIT_PROTECTION_PROMPT,
                "portfolio_symbols": ["AAPL", "MSFT", "NVDA", "SPY", "GLD", "TLT", "CASH"],
                "base_currency": "EUR",
                "new_asset_mode": "portfolio_only",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["rule_count"], 9)
        rules = {rule["id"]: rule for rule in data["rules"]}
        self.assertIn("profit_protect_aapl_spy_on", rules)
        self.assertIn("profit_protect_aapl_spy_off", rules)
        self.assertIn("profit_reentry_aapl", rules)
        self.assertEqual(rules["profit_protect_aapl_spy_on"]["actions"][0]["allocations"], [
            {"asset": "SPY", "percent": 40},
            {"asset": "TLT", "percent": 35},
            {"asset": "GLD", "percent": 25},
        ])
        self.assertEqual(rules["profit_protect_aapl_spy_off"]["actions"][0]["allocations"], [
            {"asset": "TLT", "percent": 55},
            {"asset": "GLD", "percent": 45},
        ])
        self.assertEqual(rules["profit_protect_aapl_spy_on"]["execution"]["daily_group_id"], "growth_profit_protection_daily")
        self.assertEqual(rules["profit_protect_aapl_spy_on"]["execution"]["daily_group_max_triggers"], 2)
        self.assertEqual(rules["profit_protect_aapl_spy_on"]["execution"]["group_max_triggers"], 3)
        self.assertEqual(rules["profit_protect_aapl_spy_on"]["execution"]["group_cooldown_days"], 45)
        self.assertEqual(rules["profit_reentry_aapl"]["actions"][0]["type"], "buy_with_cash_percent")
        self.assertEqual(rules["profit_reentry_aapl"]["actions"][0]["cash_percent"], 20)

    def test_rules_build_returns_defensive_reallocation_bundle(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": DEFENSIVE_REALLOCATION_PROMPT,
                "portfolio_symbols": ["AAPL", "MSFT", "SPY", "GLD", "TLT", "CASH"],
                "base_currency": "EUR",
                "new_asset_mode": "portfolio_only",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["rule_count"], 2)
        risk_off, reentry = data["rules"]
        self.assertEqual(risk_off["id"], "defensive_aapl_to_gld_tlt_cash")
        self.assertEqual(risk_off["condition"]["indicator"], "all")
        self.assertEqual(risk_off["condition"]["params"]["conditions"][0]["params"], {"asset": "SPY", "window": 200})
        self.assertEqual(risk_off["condition"]["params"]["conditions"][1]["indicator"], "volatility")
        self.assertEqual(risk_off["condition"]["params"]["conditions"][1]["value"], 24)
        self.assertEqual(risk_off["condition"]["params"]["conditions"][2]["params"], {"asset": "AAPL", "window": 100})
        self.assertEqual(risk_off["actions"][0]["type"], "split_transfer_position_percent")
        self.assertEqual(risk_off["actions"][0]["from_asset"], "AAPL")
        self.assertEqual(risk_off["actions"][0]["percent"], 30)
        self.assertEqual(risk_off["actions"][0]["allocations"], [{"asset": "GLD", "percent": 50}, {"asset": "TLT", "percent": 30}])
        self.assertEqual(risk_off["execution"]["cooldown_days"], 30)
        self.assertEqual(risk_off["execution"]["max_triggers"], 4)
        self.assertEqual(risk_off["execution"]["group_id"], "defensive_rotation_aapl")
        self.assertEqual(reentry["id"], "defensive_reentry_cash_to_aapl")
        self.assertEqual(reentry["condition"]["params"]["conditions"][0]["indicator"], "asset_was_reduced")
        self.assertEqual(reentry["condition"]["params"]["conditions"][1]["params"], {"asset": "SPY", "window": 200})
        self.assertEqual(reentry["condition"]["params"]["conditions"][2]["value"], 18)
        self.assertEqual(reentry["actions"][0]["type"], "buy_with_cash_percent")
        self.assertEqual(reentry["actions"][0]["asset"], "AAPL")
        self.assertEqual(reentry["actions"][0]["cash_percent"], 25)
        self.assertEqual(reentry["execution"]["group_id"], "defensive_rotation_aapl")

    def test_rules_build_accepts_simple_sell_to_cash_prompt(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": SIMPLE_SELL_TO_CASH_PROMPT,
                "portfolio_symbols": ["AAPL", "CASH"],
                "base_currency": "EUR",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["rule"]["condition"]["indicator"], "price_below_moving_average")
        self.assertEqual(data["rule"]["condition"]["params"], {"asset": "AAPL", "window": 200})
        self.assertEqual(data["rule"]["actions"][0]["type"], "sell_position_percent")
        self.assertEqual(data["rule"]["actions"][0]["asset"], "AAPL")
        self.assertEqual(data["rule"]["actions"][0]["percent"], 25)
        self.assertIsNone(data["rule"]["execution"]["max_triggers"])
        self.assertEqual(data["rule"]["execution"]["cooldown_days"], 30)

    def test_rules_build_accepts_simple_cash_to_gld_prompt(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": SIMPLE_CASH_TO_GLD_PROMPT,
                "portfolio_symbols": ["SPY", "GLD", "CASH"],
                "base_currency": "EUR",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["rule"]["condition"]["indicator"], "price_below_moving_average")
        self.assertEqual(data["rule"]["condition"]["params"], {"asset": "SPY", "window": 100})
        self.assertEqual(data["rule"]["actions"][0]["type"], "buy_with_cash_percent")
        self.assertEqual(data["rule"]["actions"][0]["asset"], "GLD")
        self.assertEqual(data["rule"]["actions"][0]["cash_percent"], 30)
        self.assertIsNone(data["rule"]["execution"]["max_triggers"])
        self.assertEqual(data["rule"]["execution"]["cooldown_days"], 20)

    def test_rules_build_accepts_simple_profit_to_gld_prompt(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": SIMPLE_PROFIT_TO_GLD_PROMPT,
                "portfolio_symbols": ["AAPL", "GLD", "CASH"],
                "base_currency": "EUR",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["rule"]["condition"]["indicator"], "return_since_start")
        self.assertEqual(data["rule"]["condition"]["value"], 20)
        self.assertEqual(data["rule"]["condition"]["params"], {"asset": "AAPL"})
        self.assertEqual(data["rule"]["actions"][0]["type"], "transfer_position_percent")
        self.assertEqual(data["rule"]["actions"][0]["from_asset"], "AAPL")
        self.assertEqual(data["rule"]["actions"][0]["to_asset"], "GLD")
        self.assertEqual(data["rule"]["actions"][0]["percent"], 15)
        self.assertEqual(data["rule"]["execution"]["max_triggers"], 2)
        self.assertEqual(data["rule"]["execution"]["cooldown_days"], 0)

    def test_rules_build_accepts_simple_price_threshold_transfer_prompt(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": SIMPLE_PRICE_TO_GLD_PROMPT,
                "portfolio_symbols": ["AAPL", "GLD"],
                "base_currency": "EUR",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["audit"]["status"], "ok")
        self.assertEqual(data["rule"]["condition"]["indicator"], "price")
        self.assertEqual(data["rule"]["condition"]["operator"], ">")
        self.assertEqual(data["rule"]["condition"]["value"], 100)
        self.assertEqual(data["rule"]["condition"]["params"], {"asset": "AAPL"})
        self.assertEqual(data["rule"]["actions"][0]["type"], "transfer_position_percent")
        self.assertEqual(data["rule"]["actions"][0]["from_asset"], "AAPL")
        self.assertEqual(data["rule"]["actions"][0]["to_asset"], "GLD")
        self.assertEqual(data["rule"]["actions"][0]["percent"], 50)
        self.assertEqual(data["rule"]["execution"]["max_triggers"], 5)
        self.assertEqual(data["rule"]["execution"]["cooldown_days"], 0)

    def test_rules_build_self_heals_missing_entropy_indicator(self):
        self.authenticate()

        response = self.client.post(
            "/rules/build",
            json={
                "natural_language_rule": SELF_HEALING_ENTROPY_PROMPT,
                "portfolio_symbols": ["AAPL", "GLD"],
                "base_currency": "EUR",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["audit"]["status"], "ok")
        self.assertEqual(data["rule"]["condition"]["indicator"], "entropy")
        self.assertEqual(data["rule"]["condition"]["operator"], ">")
        self.assertEqual(data["rule"]["condition"]["value"], 0.75)
        self.assertEqual(data["rule"]["condition"]["params"]["asset"], "AAPL")
        self.assertEqual(data["rule"]["condition"]["params"]["window"], 30)
        self.assertEqual(data["rule"]["actions"][0]["type"], "transfer_position_percent")
        self.assertEqual(data["rule"]["actions"][0]["from_asset"], "AAPL")
        self.assertEqual(data["rule"]["actions"][0]["to_asset"], "GLD")
        self.assertEqual(data["rule"]["actions"][0]["percent"], 20)
        self.assertEqual(data["self_healing"]["status"], "ok")
        self.assertEqual(data["self_healing"]["registered_indicator"], "entropy")
        self.assertEqual(data["self_healing"]["formula_audit"]["status"], "ok")
        self.assertEqual(data["self_healing"]["indicator_tests"]["status"], "ok")
        self.assertEqual(data["auto_extensions"][0]["name"], "entropy")
        self.assertTrue(data["auto_extension_trace"]["original_rule_retried"])
        self.assertIn("entropy", data["audit"]["allowed_indicators"])

    def test_rules_build_self_heals_multiple_price_indicators(self):
        self.authenticate()

        for indicator, prompt, symbols, operator, value, expected_params, action_type in SELF_HEALING_CASES:
            with self.subTest(indicator=indicator):
                IndicatorRegistry.clear_dynamic_indicators()
                ai_rule_builder._CACHE.clear()
                response = self.client.post(
                    "/rules/build",
                    json={
                        "natural_language_rule": prompt,
                        "portfolio_symbols": symbols,
                        "base_currency": "EUR",
                    },
                )

                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["status"], "ok", data)
                self.assertEqual(data["rule"]["condition"]["indicator"], indicator)
                self.assertEqual(data["rule"]["condition"]["operator"], operator)
                self.assertAlmostEqual(float(data["rule"]["condition"]["value"]), float(value))
                for key, expected in expected_params.items():
                    self.assertEqual(data["rule"]["condition"]["params"][key], expected)
                self.assertEqual(data["rule"]["actions"][0]["type"], action_type)
                self.assertEqual(data["auto_extensions"][0]["name"], indicator)
                self.assertTrue(data["auto_extensions"][0]["security_passed"])
                self.assertTrue(data["auto_extensions"][0]["tests_passed"])
                self.assertTrue(data["auto_extension_trace"]["registered"])
                self.assertTrue(data["auto_extension_trace"]["original_rule_retried"])

    def test_rules_build_external_data_indicators_need_manual_review(self):
        self.authenticate()

        for prompt, indicator in [
            ("If news sentiment of AAPL is above 0.7, sell 10% AAPL.", "news_sentiment"),
            ("If earnings surprise of AAPL is above 5, sell 10% AAPL.", "earnings"),
        ]:
            with self.subTest(indicator=indicator):
                response = self.client.post(
                    "/rules/build",
                    json={
                        "natural_language_rule": prompt,
                        "portfolio_symbols": ["AAPL", "GLD"],
                        "base_currency": "EUR",
                    },
                )

                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["status"], "needs_manual_review")
                self.assertEqual(data["missing_indicator"], indicator)
                self.assertFalse(data["auto_extension_trace"]["registered"])

    def test_rules_validate_rejects_invalid_rule(self):
        self.authenticate()

        response = self.client.post(
            "/rules/validate",
            json={
                "portfolio_symbols": ["AAPL", "GLD"],
                "rule": {
                    "id": "bad",
                    "name": "Bad",
                    "condition": {"indicator": "unknown", "operator": ">", "value": 1, "params": {}},
                    "actions": [{"type": "run_python", "asset": "AAPL", "percent": 10}],
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["valid"])

    def test_rules_example_tests_returns_scenarios(self):
        self.authenticate()

        response = self.client.post(
            "/rules/example-tests",
            json={
                "rule": {
                    "id": "sell",
                    "name": "Sell",
                    "condition": {"indicator": "drawdown", "operator": ">=", "value": 10, "params": {"asset": "AAPL", "window": 30}},
                    "actions": [{"type": "sell_position_percent", "asset": "AAPL", "percent": 20}],
                }
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["example_tests"]), 3)


if __name__ == "__main__":
    unittest.main()

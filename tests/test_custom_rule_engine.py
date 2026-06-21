import unittest
from unittest.mock import patch

import pandas as pd

from custom_rule_engine import execute_custom_rules, resolve_indicator, validate_custom_rule
from indicator_registry import IndicatorRegistry, IndicatorSynthesizer
from main import simuliere
from Protfolio import Portfolio


def valid_rule():
    return {
        "id": "rule_aapl_to_gld",
        "name": "AAPL to Gold",
        "condition": {
            "indicator": "price_above_moving_average",
            "operator": ">",
            "value": 0.5,
            "params": {"asset": "AAPL", "window": 2},
        },
        "actions": [
            {
                "type": "transfer_position_percent",
                "from_asset": "AAPL",
                "to_asset": "GLD",
                "percent": 20,
            }
        ],
        "execution": {"frequency": "daily", "max_triggers": 1, "cooldown_days": 0},
    }


class CustomRuleEngineTest(unittest.TestCase):
    def setUp(self):
        IndicatorRegistry.clear_dynamic_indicators()

    def tearDown(self):
        IndicatorRegistry.clear_dynamic_indicators()

    def test_valid_transfer_rule_passes_validation(self):
        result = validate_custom_rule(valid_rule(), ["AAPL", "GLD", "SPY"])

        self.assertTrue(result["valid"])

    def test_unknown_action_is_rejected(self):
        rule = valid_rule()
        rule["actions"][0]["type"] = "run_python"

        result = validate_custom_rule(rule, ["AAPL", "GLD", "SPY"])

        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "unsupported_action")

    def test_invalid_operator_is_rejected(self):
        rule = valid_rule()
        rule["condition"]["operator"] = "contains"

        result = validate_custom_rule(rule, ["AAPL", "GLD", "SPY"])

        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "unsupported_operator")

    def test_percent_over_100_is_rejected(self):
        rule = valid_rule()
        rule["actions"][0]["percent"] = 120

        result = validate_custom_rule(rule, ["AAPL", "GLD", "SPY"])

        self.assertFalse(result["valid"])
        self.assertTrue(any(error["code"] == "invalid_percent" for error in result["errors"]))

    def test_missing_target_asset_is_rejected(self):
        result = validate_custom_rule(valid_rule(), ["AAPL", "SPY"])

        self.assertFalse(result["valid"])
        self.assertTrue(any(error["code"] == "missing_asset" for error in result["errors"]))

    def test_missing_asset_can_be_allowed_during_rule_build(self):
        result = validate_custom_rule(valid_rule(), ["AAPL", "SPY"], allow_new_assets=True)

        self.assertTrue(result["valid"])

    def test_condition_true_executes_transfer_once(self):
        dates = pd.bdate_range("2024-01-01", periods=3)
        prices = pd.DataFrame({"AAPL": [100.0, 110.0, 120.0], "GLD": [50.0, 50.0, 50.0], "SPY": [100.0, 101.0, 102.0]}, index=dates)
        portfolio = Portfolio(0, True)
        portfolio.add_asset("Apple", "AAPL", 50, 0)
        portfolio.add_asset("Gold", "GLD", 30, 0)
        portfolio.add_asset("SPY", "SPY", 20, 0)
        portfolio.assets[0].stueckzahl = 10
        portfolio.assets[1].stueckzahl = 0
        runtime = {}

        events = execute_custom_rules(
            portfolio,
            prices.iloc[1],
            prices.loc[:dates[1]],
            dates[1],
            [valid_rule()],
            runtime_state=runtime,
        )
        execute_custom_rules(
            portfolio,
            prices.iloc[2],
            prices.loc[:dates[2]],
            dates[2],
            [valid_rule()],
            runtime_state=runtime,
        )

        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(portfolio.assets[0].stueckzahl, 8.0)
        self.assertAlmostEqual(portfolio.assets[1].stueckzahl, 4.4)
        self.assertEqual(runtime["custom_rules"]["rule_aapl_to_gld"]["triggers"], 1)

    def test_composite_condition_executes_split_transfer_once(self):
        dates = pd.bdate_range("2024-01-01", periods=4)
        prices = pd.DataFrame(
            {
                "AAPL": [120.0, 80.0, 110.0, 70.0],
                "GLD": [50.0, 50.0, 50.0, 50.0],
                "TLT": [100.0, 100.0, 100.0, 100.0],
                "SPY": [100.0, 99.0, 98.0, 97.0],
            },
            index=dates,
        )
        rule = {
            "id": "risk_off_split",
            "name": "Risk-Off Split",
            "condition": {
                "indicator": "all",
                "operator": "==",
                "value": 1,
                "params": {
                    "conditions": [
                        {"indicator": "price_below_moving_average", "operator": "==", "value": 1, "params": {"asset": "AAPL", "window": 4}},
                        {"indicator": "volatility", "operator": ">", "value": 20, "params": {"asset": "AAPL", "window": 3}},
                    ]
                },
            },
            "actions": [
                {
                    "type": "split_transfer_position_percent",
                    "from_asset": "AAPL",
                    "percent": 25,
                    "allocations": [{"asset": "GLD", "percent": 60}, {"asset": "TLT", "percent": 40}],
                }
            ],
            "execution": {"frequency": "daily", "max_triggers": 1, "cooldown_days": 30},
        }
        portfolio = Portfolio(0, True)
        portfolio.add_asset("Apple", "AAPL", 50, 0)
        portfolio.add_asset("Gold", "GLD", 25, 0)
        portfolio.add_asset("Bonds", "TLT", 25, 0)
        portfolio.add_asset("Market", "SPY", 0, 0)
        portfolio.assets[0].stueckzahl = 100
        portfolio.assets[1].stueckzahl = 0
        portfolio.assets[2].stueckzahl = 0

        validation = validate_custom_rule(rule, ["AAPL", "GLD", "TLT", "SPY"])
        events = execute_custom_rules(portfolio, prices.iloc[-1], prices, dates[-1], [rule], runtime_state={})

        self.assertTrue(validation["valid"])
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(portfolio.assets[0].stueckzahl, 75.0)
        self.assertAlmostEqual(portfolio.assets[1].stueckzahl, 21.0)
        self.assertAlmostEqual(portfolio.assets[2].stueckzahl, 7.0)
        self.assertEqual(events[0]["actions"][0]["allocations"][0]["asset"], "GLD")

    def test_split_transfer_can_keep_unallocated_proceeds_as_cash(self):
        dates = pd.bdate_range("2024-01-01", periods=2)
        prices = pd.DataFrame(
            {"AAPL": [100.0, 110.0], "GLD": [50.0, 50.0], "TLT": [100.0, 100.0]},
            index=dates,
        )
        rule = {
            "id": "split_keep_cash",
            "name": "Split and keep cash",
            "condition": {
                "indicator": "price_above_moving_average",
                "operator": "==",
                "value": 1,
                "params": {"asset": "AAPL", "window": 2},
            },
            "actions": [
                {
                    "type": "split_transfer_position_percent",
                    "from_asset": "AAPL",
                    "percent": 30,
                    "allocations": [{"asset": "GLD", "percent": 50}, {"asset": "TLT", "percent": 30}],
                }
            ],
        }
        portfolio = Portfolio(0, True)
        portfolio.add_asset("Apple", "AAPL", 100, 0)
        portfolio.add_asset("Gold", "GLD", 0, 0)
        portfolio.add_asset("Bonds", "TLT", 0, 0)
        portfolio.assets[0].stueckzahl = 100

        validation = validate_custom_rule(rule, ["AAPL", "GLD", "TLT"])
        events = execute_custom_rules(portfolio, prices.iloc[-1], prices, dates[-1], [rule], runtime_state={})

        self.assertTrue(validation["valid"])
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(portfolio.assets[0].stueckzahl, 70.0)
        self.assertAlmostEqual(portfolio.assets[1].stueckzahl, 33.0)
        self.assertAlmostEqual(portfolio.assets[2].stueckzahl, 9.9)
        self.assertAlmostEqual(portfolio.cash, 660.0)
        self.assertAlmostEqual(events[0]["actions"][0]["retained_cash"], 660.0)

    def test_group_limits_apply_across_multiple_rules(self):
        date = pd.Timestamp("2024-02-01")
        prices = pd.DataFrame({"AAPL": [100.0, 110.0], "GLD": [50.0, 55.0]}, index=pd.bdate_range("2024-01-31", periods=2))
        base_rule = {
            "condition": {
                "indicator": "price_above_moving_average",
                "operator": "==",
                "value": 1,
                "params": {"asset": "AAPL", "window": 2},
            },
            "execution": {
                "frequency": "daily",
                "max_triggers": 4,
                "cooldown_days": 0,
                "group_id": "shared_rotation",
                "group_max_triggers": 1,
                "group_cooldown_days": 30,
            },
        }
        rules = [
            {**base_rule, "id": "first", "name": "First", "actions": [{"type": "sell_position_percent", "asset": "AAPL", "percent": 1}]},
            {**base_rule, "id": "second", "name": "Second", "actions": [{"type": "sell_position_percent", "asset": "GLD", "percent": 1}]},
        ]
        portfolio = Portfolio(0, True)
        portfolio.add_asset("Apple", "AAPL", 50, 0)
        portfolio.add_asset("Gold", "GLD", 50, 0)
        portfolio.assets[0].stueckzahl = 10
        portfolio.assets[1].stueckzahl = 10
        runtime = {}

        events = execute_custom_rules(portfolio, prices.iloc[-1], prices, date, rules, runtime_state=runtime)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["rule_id"], "first")
        self.assertEqual(runtime["custom_rule_groups"]["shared_rotation"]["triggers"], 1)

    def test_daily_group_limits_apply_across_multiple_assets(self):
        date = pd.Timestamp("2024-02-01")
        prices = pd.DataFrame(
            {"AAPL": [100.0, 110.0], "MSFT": [100.0, 110.0], "NVDA": [100.0, 110.0]},
            index=pd.bdate_range("2024-01-31", periods=2),
        )

        def daily_rule(symbol):
            return {
                "id": f"daily_{symbol}",
                "name": f"Daily {symbol}",
                "condition": {
                    "indicator": "price_above_moving_average",
                    "operator": "==",
                    "value": 1,
                    "params": {"asset": symbol, "window": 2},
                },
                "actions": [{"type": "sell_position_percent", "asset": symbol, "percent": 1}],
                "execution": {
                    "frequency": "daily",
                    "daily_group_id": "growth_daily",
                    "daily_group_max_triggers": 2,
                },
            }

        portfolio = Portfolio(0, True)
        for symbol in ["AAPL", "MSFT", "NVDA"]:
            portfolio.add_asset(symbol, symbol, 33, 0)
            portfolio.assets[-1].stueckzahl = 10
        runtime = {}

        events = execute_custom_rules(
            portfolio,
            prices.iloc[-1],
            prices,
            date,
            [daily_rule("AAPL"), daily_rule("MSFT"), daily_rule("NVDA")],
            runtime_state=runtime,
        )

        self.assertEqual([event["rule_id"] for event in events], ["daily_AAPL", "daily_MSFT"])
        self.assertEqual(runtime["custom_rule_daily_groups"]["growth_daily"]["daily_triggers"]["2024-02-01"], 2)

    def test_reentry_condition_requires_previous_reduction(self):
        dates = pd.bdate_range("2024-01-01", periods=2)
        prices = pd.DataFrame({"AAPL": [100.0, 110.0], "SPY": [100.0, 110.0]}, index=dates)
        rule = {
            "id": "reentry",
            "name": "Reentry",
            "condition": {
                "indicator": "all",
                "operator": "==",
                "value": 1,
                "params": {
                    "conditions": [
                        {"indicator": "asset_was_reduced", "operator": "==", "value": 1, "params": {"asset": "AAPL"}},
                        {"indicator": "price_above_moving_average", "operator": "==", "value": 1, "params": {"asset": "AAPL", "window": 2}},
                    ]
                },
            },
            "actions": [{"type": "buy_with_cash_percent", "asset": "AAPL", "cash_percent": 20}],
        }
        portfolio = Portfolio(1000, True)
        portfolio.add_asset("Apple", "AAPL", 100, 0)
        portfolio.add_asset("Market", "SPY", 0, 0)
        portfolio.assets[0].stueckzahl = 0

        no_reduction_events = execute_custom_rules(portfolio, prices.iloc[-1], prices, dates[-1], [rule], runtime_state={})
        with_reduction_runtime = {"reduced_assets": {"AAPL": 1}}
        reentry_events = execute_custom_rules(portfolio, prices.iloc[-1], prices, dates[-1], [rule], runtime_state=with_reduction_runtime)

        self.assertEqual(no_reduction_events, [])
        self.assertEqual(len(reentry_events), 1)
        self.assertAlmostEqual(portfolio.assets[0].stueckzahl, 200 / 110)

    def test_return_since_start_indicator_uses_first_available_price(self):
        dates = pd.bdate_range("2024-01-01", periods=3)
        prices = pd.DataFrame({"AAPL": [100.0, 130.0, 160.0]}, index=dates)
        condition = {
            "indicator": "return_since_start",
            "operator": ">",
            "value": 45,
            "params": {"asset": "AAPL"},
        }

        value = resolve_indicator(condition, prices)

        self.assertAlmostEqual(value, 60.0)

    def test_price_indicator_executes_threshold_transfer_rule(self):
        dates = pd.bdate_range("2024-01-01", periods=2)
        prices = pd.DataFrame({"AAPL": [90.0, 110.0], "GLD": [50.0, 50.0]}, index=dates)
        rule = {
            "id": "aapl_price_to_gld",
            "name": "AAPL price to GLD",
            "condition": {
                "indicator": "price",
                "operator": ">",
                "value": 100,
                "params": {"asset": "AAPL"},
            },
            "actions": [{"type": "transfer_position_percent", "from_asset": "AAPL", "to_asset": "GLD", "percent": 50}],
            "execution": {"frequency": "daily", "max_triggers": 5, "cooldown_days": 0},
        }
        portfolio = Portfolio(0, True)
        portfolio.add_asset("Apple", "AAPL", 50, 0)
        portfolio.add_asset("Gold", "GLD", 50, 0)
        portfolio.assets[0].stueckzahl = 10
        portfolio.assets[1].stueckzahl = 0

        validation = validate_custom_rule(rule, ["AAPL", "GLD"])
        events = execute_custom_rules(portfolio, prices.iloc[-1], prices, dates[-1], [rule], runtime_state={})

        self.assertTrue(validation["valid"])
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(portfolio.assets[0].stueckzahl, 5.0)
        self.assertAlmostEqual(portfolio.assets[1].stueckzahl, 11.0)
        self.assertEqual(events[0]["rule_id"], "aapl_price_to_gld")

    def test_market_rotation_score_is_bounded(self):
        dates = pd.bdate_range("2024-01-01", periods=6)
        prices = pd.DataFrame({"SPY": [100, 102, 104, 106, 108, 110], "GLD": [100, 100, 99, 99, 98, 98], "TLT": [100, 99, 99, 98, 98, 97]}, index=dates)
        condition = {
            "indicator": "market_rotation_score",
            "operator": ">",
            "value": 70,
            "params": {"equity_proxy": "SPY", "defensive_proxy": ["GLD", "TLT"], "window": 5},
        }

        score = resolve_indicator(validate_custom_rule({
            "id": "rotation",
            "name": "Rotation",
            "condition": condition,
            "actions": [{"type": "sell_position_percent", "asset": "SPY", "percent": 1}],
        }, ["SPY", "GLD", "TLT"])["rule"]["condition"], prices)

        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_simulation_accepts_custom_rules(self):
        index = pd.bdate_range("2024-01-01", periods=4)

        def prices(symbol, *args, **kwargs):
            data = {
                "AAPL": [100.0, 110.0, 120.0, 120.0],
                "GLD": [50.0, 50.0, 50.0, 50.0],
                "SPY": [100.0, 101.0, 102.0, 103.0],
            }[symbol]
            return pd.DataFrame({"Close": data, "Dividends": [0.0] * len(index)}, index=index)

        portfolio = Portfolio(1000, True)
        portfolio.add_asset("Apple", "AAPL", 60, 0)
        portfolio.add_asset("Gold", "GLD", 20, 0)
        portfolio.add_asset("SPY", "SPY", 20, 0)

        with patch("market_data.yf.download", side_effect=prices):
            result = simuliere(
                portfolio,
                [],
                "2024-01-01",
                "2024-01-05",
                sp_start=0,
                custom_regeln=[valid_rule()],
            )

        self.assertEqual(len(result["custom_rule_events"]), 1)
        self.assertEqual(result["custom_rule_events"][0]["rule_id"], "rule_aapl_to_gld")

    def test_dynamic_rsi_condition_true_triggers_buy_with_cash(self):
        IndicatorRegistry.register_dynamic_indicator(IndicatorSynthesizer.synthesize({"indicator": "rsi"}, "RSI", ["AAPL"]))
        dates = pd.bdate_range("2024-01-01", periods=40)
        prices = pd.DataFrame({"AAPL": list(range(140, 100, -1))}, index=dates)
        rule = {
            "id": "dynamic_rsi_buy",
            "name": "Dynamic RSI Buy",
            "condition": {"indicator": "rsi", "operator": "<", "value": 30, "params": {"asset": "AAPL", "window": 14}},
            "actions": [{"type": "buy_with_cash_percent", "asset": "AAPL", "cash_percent": 25}],
        }
        portfolio = Portfolio(1000, True)
        portfolio.add_asset("Apple", "AAPL", 100, 0)
        portfolio.assets[0].stueckzahl = 0

        validation = validate_custom_rule(rule, ["AAPL"])
        events = execute_custom_rules(portfolio, prices.iloc[-1], prices, dates[-1], [rule], runtime_state={})

        self.assertTrue(validation["valid"])
        self.assertEqual(len(events), 1)
        self.assertGreater(portfolio.assets[0].stueckzahl, 0)

    def test_dynamic_correlation_condition_false_does_not_trigger(self):
        IndicatorRegistry.register_dynamic_indicator(IndicatorSynthesizer.synthesize({"indicator": "correlation"}, "correlation", ["AAPL", "GLD"]))
        dates = pd.bdate_range("2024-01-01", periods=80)
        prices = pd.DataFrame(
            {"AAPL": range(100, 180), "GLD": range(200, 280)},
            index=dates,
        )
        rule = {
            "id": "dynamic_corr_false",
            "name": "Dynamic Correlation False",
            "condition": {"indicator": "correlation", "operator": "<", "value": -0.2, "params": {"asset_a": "AAPL", "asset_b": "GLD", "window": 60}},
            "actions": [{"type": "transfer_position_percent", "from_asset": "AAPL", "to_asset": "GLD", "percent": 20}],
        }
        portfolio = Portfolio(0, True)
        portfolio.add_asset("Apple", "AAPL", 50, 0)
        portfolio.add_asset("Gold", "GLD", 50, 0)
        portfolio.assets[0].stueckzahl = 10

        events = execute_custom_rules(portfolio, prices.iloc[-1], prices, dates[-1], [rule], runtime_state={})

        self.assertEqual(events, [])

    def test_dynamic_entropy_rule_records_custom_rule_events(self):
        IndicatorRegistry.register_dynamic_indicator(IndicatorSynthesizer.synthesize({"indicator": "entropy"}, "entropy", ["AAPL", "GLD"]))
        dates = pd.bdate_range("2024-01-01", periods=40)
        prices = pd.DataFrame(
            {
                "AAPL": [100, 103, 99, 105, 98, 108, 102, 111] * 5,
                "GLD": [50.0] * 40,
            },
            index=dates,
        )
        rule = {
            "id": "dynamic_entropy_transfer",
            "name": "Dynamic Entropy Transfer",
            "condition": {"indicator": "entropy", "operator": ">", "value": 0.1, "params": {"asset": "AAPL", "window": 30, "bins": 5}},
            "actions": [{"type": "transfer_position_percent", "from_asset": "AAPL", "to_asset": "GLD", "percent": 10}],
            "execution": {"frequency": "daily", "max_triggers": 1, "cooldown_days": 0},
        }
        portfolio = Portfolio(0, True)
        portfolio.add_asset("Apple", "AAPL", 50, 0)
        portfolio.add_asset("Gold", "GLD", 50, 0)
        portfolio.assets[0].stueckzahl = 10
        runtime = {}

        events = execute_custom_rules(portfolio, prices.iloc[-1], prices, dates[-1], [rule], runtime_state=runtime)

        self.assertEqual(len(events), 1)
        self.assertEqual(runtime["custom_rule_events"][0]["rule_id"], "dynamic_entropy_transfer")

    def test_unapproved_dynamic_indicator_is_rejected(self):
        IndicatorRegistry.register_dynamic_indicator(IndicatorSynthesizer.synthesize({"indicator": "rsi"}, "RSI", ["AAPL"]), approved=False)
        rule = {
            "id": "pending_rsi",
            "name": "Pending RSI",
            "condition": {"indicator": "rsi", "operator": "<", "value": 30, "params": {"asset": "AAPL", "window": 14}},
            "actions": [{"type": "sell_position_percent", "asset": "AAPL", "percent": 10}],
        }

        validation = validate_custom_rule(rule, ["AAPL"])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(error["code"] == "unapproved_indicator" for error in validation["errors"]))


if __name__ == "__main__":
    unittest.main()

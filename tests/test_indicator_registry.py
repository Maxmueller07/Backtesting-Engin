import unittest

import pandas as pd

from indicator_registry import (
    FormulaEvaluator,
    FormulaIndicatorDefinition,
    FormulaSecurityAuditor,
    IndicatorRegistry,
    IndicatorSynthesizer,
    IndicatorTestRunner,
)


class IndicatorRegistryTest(unittest.TestCase):
    def setUp(self):
        IndicatorRegistry.clear_dynamic_indicators()

    def tearDown(self):
        IndicatorRegistry.clear_dynamic_indicators()

    def test_security_auditor_rejects_unknown_formula_operation(self):
        audit = FormulaSecurityAuditor.audit({
            "name": "unsafe_indicator",
            "description": "Unsafe",
            "formula": {"op": "eval", "value": "__import__('os').system('dir')"},
            "required_params": ["asset"],
            "default_params": {"window": 30},
            "version": "formula-indicator-v1",
        })

        self.assertFalse(audit["valid"])
        self.assertTrue(any(error["code"] == "unsupported_formula_op" for error in audit["errors"]))

    def test_security_auditor_rejects_suspicious_content_and_python_plugins(self):
        suspicious_cases = [
            {"name": "eval_indicator", "type": "formula_indicator", "formula": {"op": "price", "asset_param": "asset", "python": "eval('1')"}},
            {"name": "exec_indicator", "type": "formula_indicator", "formula": {"op": "price", "asset_param": "asset", "code": "exec('1')"}},
            {"name": "import_indicator", "type": "formula_indicator", "formula": {"op": "price", "asset_param": "asset", "import": "os"}},
            {"name": "url_indicator", "type": "formula_indicator", "formula": {"op": "price", "asset_param": "asset", "url": "https://example.com"}},
            {"name": "plugin_indicator", "type": "python_plugin", "formula": {"op": "price", "asset_param": "asset"}},
        ]

        for payload in suspicious_cases:
            with self.subTest(name=payload["name"]):
                payload.setdefault("description", "Unsafe")
                payload.setdefault("required_params", ["asset"])
                payload.setdefault("default_params", {"asset": "AAPL"})
                payload.setdefault("params_schema", {"asset": "symbol"})
                payload.setdefault("version", "formula-indicator-v1")
                audit = FormulaSecurityAuditor.audit(payload)
                self.assertFalse(audit["passed"])

    def test_entropy_formula_is_registered_tested_and_resolved(self):
        definition = IndicatorSynthesizer.synthesize(
            {"indicator": "entropy"},
            "If the 30-day entropy of AAPL is above 0.75, sell AAPL.",
            ["AAPL", "GLD"],
        )

        audit = FormulaSecurityAuditor.audit(definition)
        registration = IndicatorRegistry.register_dynamic_indicator(definition)
        tests = IndicatorTestRunner.run(definition, ["AAPL", "GLD"])
        prices = pd.DataFrame(
            {"AAPL": [100, 102, 99, 104, 101, 106, 100, 108, 103, 109, 104, 111]},
            index=pd.bdate_range("2024-01-01", periods=12),
        )
        value = IndicatorRegistry.resolve("entropy", prices, {"asset": "AAPL", "window": 10, "bins": 5})

        self.assertTrue(audit["valid"])
        self.assertEqual(registration["status"], "ok")
        self.assertTrue(tests["passed"])
        self.assertGreaterEqual(value, 0)
        self.assertLessEqual(value, 1)

    def test_registry_lists_builtins_and_blocks_unapproved_dynamic_indicator(self):
        self.assertIn("price", IndicatorRegistry.names())
        definition = IndicatorSynthesizer.synthesize({"indicator": "rsi"}, "RSI", ["AAPL"])

        registration = IndicatorRegistry.register_dynamic_indicator(definition, approved=False)

        self.assertEqual(registration["status"], "ok")
        self.assertIn("rsi", IndicatorRegistry.names())
        prices = pd.DataFrame({"AAPL": range(100, 140)}, index=pd.bdate_range("2024-01-01", periods=40))
        with self.assertRaises(ValueError):
            IndicatorRegistry.resolve("rsi", prices, {"asset": "AAPL", "window": 14})
        IndicatorRegistry.clear_dynamic_indicators()
        self.assertNotIn("rsi", IndicatorRegistry.names())

    def test_formula_dsl_evaluates_supported_synthesized_indicators(self):
        prices = pd.DataFrame(
            {
                "AAPL": [100 + i + (i % 5) for i in range(140)],
                "GLD": [80 + i * 0.2 for i in range(140)],
                "SPY": [120 + i * 0.6 for i in range(140)],
            },
            index=pd.bdate_range("2024-01-01", periods=140),
        )
        cases = [
            ("entropy", {"asset": "AAPL", "window": 30, "bins": 8}),
            ("rsi", {"asset": "AAPL", "window": 14}),
            ("macd", {"asset": "AAPL", "fast_window": 12, "slow_window": 26, "signal_window": 9, "output": "histogram"}),
            ("correlation", {"asset_a": "AAPL", "asset_b": "GLD", "window": 60}),
            ("beta", {"asset": "AAPL", "benchmark": "SPY", "window": 60}),
            ("z_score", {"asset": "AAPL", "window": 30}),
            ("moving_average_slope", {"asset": "AAPL", "window": 50, "slope_window": 10}),
            ("momentum", {"asset": "AAPL", "window": 90}),
        ]

        for indicator, params in cases:
            with self.subTest(indicator=indicator):
                definition = IndicatorSynthesizer.synthesize({"indicator": indicator}, indicator, ["AAPL", "GLD", "SPY"])
                audit = FormulaSecurityAuditor.audit(definition)
                tests = IndicatorTestRunner.run(definition, ["AAPL", "GLD", "SPY"])
                value = FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition["formula"], prices, params))
                self.assertTrue(audit["passed"], audit)
                self.assertTrue(tests["passed"], tests)
                self.assertIsInstance(value, float)

    def test_formula_indicator_handles_insufficient_history_and_output_range(self):
        definition = IndicatorSynthesizer.synthesize({"indicator": "rsi"}, "RSI", ["AAPL"])
        short_prices = pd.DataFrame({"AAPL": [100, 101, 99]}, index=pd.bdate_range("2024-01-01", periods=3))

        value = FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition["formula"], short_prices, {"asset": "AAPL", "window": 14}))

        self.assertGreaterEqual(value, 0)
        self.assertLessEqual(value, 100)

    def test_formula_dsl_uses_only_prices_until_current_date(self):
        definition = IndicatorSynthesizer.synthesize({"indicator": "momentum"}, "momentum", ["AAPL"])
        index = pd.bdate_range("2024-01-01", periods=120)
        base_prices = pd.DataFrame({"AAPL": [100 + i for i in range(120)]}, index=index)
        changed_future = base_prices.copy()
        changed_future.loc[index[80]:, "AAPL"] = 10000
        params = {"asset": "AAPL", "window": 30}

        value_a = FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition["formula"], base_prices.loc[:index[70]], params))
        value_b = FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition["formula"], changed_future.loc[:index[70]], params))

        self.assertEqual(value_a, value_b)


if __name__ == "__main__":
    unittest.main()

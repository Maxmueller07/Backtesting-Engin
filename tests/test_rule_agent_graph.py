import unittest

from rule_agent_graph import run_rule_builder_agent


class RuleAgentGraphTest(unittest.TestCase):
    def test_langgraph_rule_agent_returns_audited_rule(self):
        result = run_rule_builder_agent(
            "In my backtest buy gold when the market rotation score is above 70. Use 20% of my Apple position.",
            ["AAPL", "GLD", "SPY"],
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["agent"], "langgraph_rule_builder")
        self.assertEqual(result["audit"]["status"], "ok")
        self.assertIn("no_code_execution", result["audit"]["checks"])
        self.assertEqual(result["rule"]["condition"]["indicator"], "market_rotation_score")

    def test_langgraph_rule_agent_rejects_non_finance_request(self):
        result = run_rule_builder_agent("Write a poem about the weather.", ["AAPL", "GLD"])

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "not_finance_related")


if __name__ == "__main__":
    unittest.main()

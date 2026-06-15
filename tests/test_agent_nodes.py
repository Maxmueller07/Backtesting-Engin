import unittest
from unittest.mock import Mock, patch

import pandas as pd

from agent_graph import run_agent_analysis


class AgentNodesTest(unittest.TestCase):
    @patch("agent_nodes._search_internet_sources")
    @patch("agent_nodes.yf.Ticker")
    def test_run_agent_analysis_uses_selected_template_and_yfinance_data(self, ticker_cls, search_sources):
        search_sources.return_value = []
        ticker = Mock()
        ticker.get_info.return_value = {
            "longName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "marketCap": 3_000_000_000_000,
            "trailingPE": 30.5,
            "profitMargins": 0.25,
            "grossMargins": 0.44,
            "returnOnEquity": 1.2,
            "returnOnCapital": 0.32,
            "heldPercentInstitutions": 0.6,
            "companyOfficers": [{"name": "Tim Cook", "title": "CEO", "age": 63}],
        }
        ticker.balance_sheet = pd.DataFrame(
            {"2025-09-30": [1000, 400]},
            index=["Total Assets", "Total Liabilities Net Minority Interest"],
        )
        ticker.news = []
        ticker_cls.return_value = ticker

        result = run_agent_analysis(
            symbol="aapl",
            name=None,
            template={
                "management": True,
                "balance_sheet": True,
                "industry_analysis": False,
                "moat": True,
            },
            instructions={
                "management": "CEO und CFO",
                "balance_sheet": "ROE ROCE KGV",
                "moat": "Preissetzungsmacht",
            },
        )

        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(result["name"], "Apple Inc.")
        self.assertIn("yfinance", result["data_source"])
        section_keys = [section["key"] for section in result["sections"]]
        self.assertEqual(section_keys, ["management", "balance_sheet", "moat"])
        self.assertEqual(result["sections"][1]["requested_focus"], "ROE ROCE KGV")
        self.assertEqual(
            [item["label"] for item in result["sections"][1]["items"]],
            ["Suchauftrag", "ROE", "ROCE", "KGV"],
        )
        self.assertIn("KI-Analyse fuer Apple Inc. (AAPL)", result["summary"])

    @patch("agent_nodes._search_internet_sources")
    @patch("agent_nodes.yf.Ticker")
    def test_free_text_instruction_creates_variable_web_search_section(self, ticker_cls, search_sources):
        ticker = Mock()
        ticker.get_info.return_value = {
            "longName": "Meta Platforms, Inc.",
            "sector": "Communication Services",
            "industry": "Internet Content & Information",
            "companyOfficers": [],
        }
        ticker.news = []
        ticker_cls.return_value = ticker
        search_sources.return_value = [
            {
                "title": "Meta outlines future AI plans",
                "url": "https://example.com/meta-ai",
                "content": "Meta plans to invest in AI infrastructure and future products.",
                "source_type": "web",
            }
        ]

        result = run_agent_analysis(
            symbol="META",
            name="Meta",
            template={
                "management": True,
                "balance_sheet": False,
                "industry_analysis": True,
                "moat": False,
            },
            instructions={
                "management": "Zukunftsplaene",
                "industry_analysis": "groessten drei Konkurrenten",
            },
        )

        management = result["sections"][0]
        industry = result["sections"][1]
        self.assertIn("Zukunftsplaene", management["search_query"])
        self.assertIn("Suchauftrag 'Zukunftsplaene'", management["summary"])
        self.assertEqual(management["items"][1]["label"], "Meta outlines future AI plans")
        self.assertIn("groessten drei Konkurrenten", industry["search_query"])


if __name__ == "__main__":
    unittest.main()

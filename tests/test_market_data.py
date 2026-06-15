import unittest
from unittest.mock import patch

import pandas as pd

from market_data import download_symbol_history, normalize_currency


class MarketDataCurrencyTest(unittest.TestCase):
    def test_manual_currency_converts_prices_and_dividends_to_base(self):
        index = pd.bdate_range("2024-01-01", periods=2)

        def fake_download(symbol, *args, **kwargs):
            if symbol == "AAPL":
                return pd.DataFrame({"Close": [100.0, 110.0], "Dividends": [1.0, 0.0]}, index=index)
            if symbol == "USDEUR=X":
                return pd.DataFrame({"Close": [0.9, 0.91]}, index=index)
            return pd.DataFrame()

        with patch("market_data.yf.download", side_effect=fake_download):
            history, meta = download_symbol_history("AAPL", "2024-01-01", "2024-01-03", "EUR", "USD")

        self.assertEqual(meta["asset_currency"], "USD")
        self.assertEqual(meta["basis_currency"], "EUR")
        self.assertAlmostEqual(history["Close"].iloc[0], 90.0)
        self.assertAlmostEqual(history["Close"].iloc[1], 100.1)
        self.assertAlmostEqual(history["Dividends"].iloc[0], 0.9)

    def test_gbpence_is_kept_separate_from_gbp(self):
        self.assertEqual(normalize_currency("GBp"), "GBp")
        self.assertEqual(normalize_currency("GBX"), "GBp")
        self.assertEqual(normalize_currency("GBP"), "GBP")


if __name__ == "__main__":
    unittest.main()

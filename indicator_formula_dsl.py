from __future__ import annotations

from typing import Any

import pandas as pd

from indicator_registry import FormulaEvaluator


def evaluate_formula(formula: dict[str, Any], historical_prices: pd.DataFrame, current_date, params: dict[str, Any]):
    prices_until_current_date = historical_prices.loc[:current_date] if current_date is not None else historical_prices
    return FormulaEvaluator.evaluate(formula, prices_until_current_date, params or {})


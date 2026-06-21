from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from custom_rule_engine import execute_custom_rules, validate_custom_rule
from Protfolio import Portfolio
from rule_agent_graph import run_rule_builder_agent


SECRET_ENV_NAMES = {
    "OPENAI_API_KEY",
    "RULE_BUILDER_API_KEY",
    "GITHUB_TOKEN",
    "GITHUB_PAT",
    "GH_TOKEN",
    "TAVILY_API_KEY",
    "DATABASE_URL",
    "SECRET_KEY",
}


def sample_rule() -> dict[str, Any]:
    return {
        "id": "sandbox_aapl_to_gld",
        "name": "Sandbox AAPL to GLD",
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


def run_sandbox_validation(rule: dict[str, Any], portfolio_symbols: list[str]) -> dict[str, Any]:
    validation = validate_custom_rule(rule, portfolio_symbols)
    if not validation["valid"]:
        return {"status": "error", "stage": "validation", "validation": validation}

    dates = pd.bdate_range("2024-01-01", periods=4)
    prices = pd.DataFrame(
        {
            "AAPL": [100.0, 110.0, 120.0, 122.0],
            "GLD": [50.0, 50.0, 51.0, 51.0],
            "SPY": [100.0, 101.0, 102.0, 103.0],
        },
        index=dates,
    )
    portfolio = Portfolio(0, True)
    portfolio.add_asset("Apple", "AAPL", 60, 0)
    portfolio.add_asset("Gold", "GLD", 20, 0)
    portfolio.add_asset("SPY", "SPY", 20, 0)
    portfolio.assets[0].stueckzahl = 10.0
    portfolio.assets[1].stueckzahl = 0.0
    portfolio.assets[2].stueckzahl = 1.0
    runtime_state: dict[str, Any] = {}

    events = execute_custom_rules(
        portfolio=portfolio,
        current_prices=prices.iloc[1],
        historical_prices=prices.loc[: dates[1]],
        current_date=dates[1],
        custom_rules=[validation["rule"]],
        runtime_state=runtime_state,
    )

    return {
        "status": "ok",
        "validation": validation,
        "events": events,
        "portfolio": {
            "cash": float(portfolio.cash),
            "AAPL_shares": float(portfolio.assets[0].stueckzahl),
            "GLD_shares": float(portfolio.assets[1].stueckzahl),
        },
    }


def run_self_test(strict_no_secrets: bool = False) -> dict[str, Any]:
    secret_names = sorted(name for name in SECRET_ENV_NAMES if os.getenv(name))
    if strict_no_secrets and secret_names:
        return {
            "status": "error",
            "stage": "secret_check",
            "message": "Sandbox received secret environment variables.",
            "secret_names": secret_names,
        }

    agent_result = run_rule_builder_agent(
        "Buy gold when the market rotation score is above 70. Use 20% of my Apple position.",
        ["AAPL", "GLD", "SPY"],
        "EUR",
        "safe",
    )
    if agent_result.get("status") != "ok":
        return {"status": "error", "stage": "agent", "agent_result": agent_result}

    engine_result = run_sandbox_validation(sample_rule(), ["AAPL", "GLD", "SPY"])
    if engine_result.get("status") != "ok":
        return {"status": "error", "stage": "engine", "engine_result": engine_result}

    if not engine_result["events"]:
        return {"status": "error", "stage": "execution", "message": "Sample rule did not trigger."}

    return {
        "status": "ok",
        "sandbox": "rule-engine",
        "network_required": False,
        "agent": {
            "status": agent_result["status"],
            "rule_id": agent_result["rule"]["id"],
            "graph": agent_result.get("agent"),
        },
        "engine": {
            "events": len(engine_result["events"]),
            "AAPL_shares": engine_result["portfolio"]["AAPL_shares"],
            "GLD_shares": engine_result["portfolio"]["GLD_shares"],
        },
        "secret_env_names_seen": secret_names if not strict_no_secrets else [],
    }


def _load_rule_file(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AI custom rule validation in a sandbox-friendly process.")
    parser.add_argument("--self-test", action="store_true", help="Run built-in deterministic agent and engine smoke tests.")
    parser.add_argument("--strict-no-secrets", action="store_true", help="Fail if sensitive environment variables are present.")
    parser.add_argument("--rule-file", help="Path to a custom rule JSON file.")
    parser.add_argument("--portfolio-symbols", default="AAPL,GLD,SPY", help="Comma separated portfolio symbols for validation.")
    args = parser.parse_args(argv)

    if args.rule_file:
        result = run_sandbox_validation(
            _load_rule_file(args.rule_file),
            [symbol.strip().upper() for symbol in args.portfolio_symbols.split(",") if symbol.strip()],
        )
    else:
        result = run_self_test(strict_no_secrets=args.strict_no_secrets)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

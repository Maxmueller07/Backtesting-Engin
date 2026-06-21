from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from indicator_registry import IndicatorRegistry


DISCLAIMER = "Historical backtest rule only. Not investment advice."
SCHEMA_VERSION = "custom-rule-v1"
ALLOWED_OPERATORS = {">", ">=", "<", "<=", "==", "!="}
ALLOWED_ACTIONS = {
    "transfer_position_percent",
    "split_transfer_position_percent",
    "sell_position_percent",
    "buy_with_cash_percent",
}
ALLOWED_INDICATORS = {
    "all",
    "any",
    "asset_was_reduced",
    "price",
    "price_above_moving_average",
    "price_below_moving_average",
    "relative_strength",
    "return_since_start",
    "drawdown",
    "volatility",
    "market_rotation_score",
}
ALLOWED_FREQUENCIES = {"daily", "weekly", "monthly"}
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-=]{0,24}$")


def supported_indicators() -> set[str]:
    return set(ALLOWED_INDICATORS) | IndicatorRegistry.names()


class RuleCondition(BaseModel):
    indicator: str
    operator: str
    value: float | int | str | bool | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RuleAction(BaseModel):
    type: str
    from_asset: str | None = None
    to_asset: str | None = None
    asset: str | None = None
    percent: float | None = None
    cash_percent: float | None = None
    amount: float | None = None
    allocations: list[dict[str, Any]] = Field(default_factory=list)


class RuleExecutionConfig(BaseModel):
    frequency: str = "daily"
    max_triggers: int | None = None
    cooldown_days: int | None = None
    group_id: str | None = None
    group_max_triggers: int | None = None
    group_cooldown_days: int | None = None
    daily_group_id: str | None = None
    daily_group_max_triggers: int | None = None


class CustomRule(BaseModel):
    id: str
    name: str
    description: str | None = None
    condition: RuleCondition
    actions: list[RuleAction]
    execution: RuleExecutionConfig = Field(default_factory=RuleExecutionConfig)
    enabled: bool = True
    created_by_ai: bool = True
    disclaimer: str = DISCLAIMER


def model_to_dict(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def parse_custom_rule(rule: CustomRule | dict[str, Any]) -> CustomRule:
    if isinstance(rule, CustomRule):
        return rule
    return CustomRule(**rule)


def normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").upper().strip()


def validate_custom_rule(
    rule: CustomRule | dict[str, Any],
    portfolio_symbols: list[str] | set[str],
    allow_new_assets: bool = False,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[str] = []
    symbols = {normalize_symbol(symbol) for symbol in portfolio_symbols}

    try:
        parsed = parse_custom_rule(rule)
    except Exception as exc:
        return {
            "status": "error",
            "valid": False,
            "errors": [{"code": "invalid_schema", "message": str(exc)}],
            "warnings": [],
            "rule": None,
        }

    if not parsed.id or len(parsed.id) > 80 or not re.match(r"^[a-zA-Z0-9_\-]+$", parsed.id):
        errors.append({"code": "invalid_rule_id", "message": "Rule id is required and may only contain letters, numbers, '-' and '_'."})

    if not parsed.name or len(parsed.name.strip()) > 120:
        errors.append({"code": "invalid_rule_name", "message": "Rule name is required and must be shorter than 120 characters."})

    if parsed.condition.indicator not in supported_indicators():
        errors.append({
            "code": "unsupported_indicator",
            "message": f"The indicator '{parsed.condition.indicator}' is not supported.",
        })
    else:
        dynamic_definition = IndicatorRegistry.get(parsed.condition.indicator)
        if dynamic_definition and dynamic_definition.approval_status != "approved":
            errors.append({
                "code": "unapproved_indicator",
                "message": f"The dynamic indicator '{parsed.condition.indicator}' is not approved for simulation.",
            })

    if parsed.condition.operator not in ALLOWED_OPERATORS:
        errors.append({
            "code": "unsupported_operator",
            "message": f"The operator '{parsed.condition.operator}' is not supported.",
        })

    _validate_condition_assets(parsed.condition, symbols, allow_new_assets, errors)

    if not parsed.actions:
        errors.append({"code": "missing_action", "message": "At least one action is required."})

    for index, action in enumerate(parsed.actions):
        _validate_action(action, index, symbols, allow_new_assets, errors)

    execution = parsed.execution
    if execution.frequency not in ALLOWED_FREQUENCIES:
        errors.append({
            "code": "unsupported_frequency",
            "message": f"Frequency '{execution.frequency}' is not supported.",
        })
    if execution.max_triggers is not None and execution.max_triggers <= 0:
        errors.append({"code": "invalid_max_triggers", "message": "max_triggers must be positive."})
    if execution.cooldown_days is not None and execution.cooldown_days < 0:
        errors.append({"code": "invalid_cooldown", "message": "cooldown_days must be non-negative."})
    if execution.group_id is not None and not re.match(r"^[a-zA-Z0-9_\-]{1,80}$", execution.group_id):
        errors.append({"code": "invalid_group_id", "message": "group_id may only contain letters, numbers, '-' and '_'."})
    if execution.group_max_triggers is not None and execution.group_max_triggers <= 0:
        errors.append({"code": "invalid_group_max_triggers", "message": "group_max_triggers must be positive."})
    if execution.group_cooldown_days is not None and execution.group_cooldown_days < 0:
        errors.append({"code": "invalid_group_cooldown", "message": "group_cooldown_days must be non-negative."})
    if execution.daily_group_id is not None and not re.match(r"^[a-zA-Z0-9_\-]{1,80}$", execution.daily_group_id):
        errors.append({"code": "invalid_daily_group_id", "message": "daily_group_id may only contain letters, numbers, '-' and '_'."})
    if execution.daily_group_max_triggers is not None and execution.daily_group_max_triggers <= 0:
        errors.append({"code": "invalid_daily_group_max_triggers", "message": "daily_group_max_triggers must be positive."})

    if not parsed.disclaimer:
        warnings.append("Rule has no disclaimer. The default disclaimer will be used by the API.")

    return {
        "status": "ok" if not errors else "error",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "rule": model_to_dict(parsed),
    }


def _validate_condition_assets(condition: RuleCondition, symbols: set[str], allow_new_assets: bool, errors: list[dict[str, str]]):
    params = condition.params or {}
    indicator = condition.indicator
    if indicator in {"all", "any"}:
        nested = params.get("conditions")
        if not isinstance(nested, list) or not nested:
            errors.append({"code": "invalid_condition_group", "message": "Composite conditions need a non-empty params.conditions list."})
            return
        for index, raw_condition in enumerate(nested):
            try:
                child = RuleCondition(**raw_condition)
            except Exception as exc:
                errors.append({"code": "invalid_condition_group", "message": f"Condition {index} is invalid: {exc}"})
                continue
            if child.indicator not in supported_indicators():
                errors.append({"code": "unsupported_indicator", "message": f"Condition {index}: indicator '{child.indicator}' is not supported."})
                continue
            child_dynamic = IndicatorRegistry.get(child.indicator)
            if child_dynamic and child_dynamic.approval_status != "approved":
                errors.append({"code": "unapproved_indicator", "message": f"Condition {index}: dynamic indicator '{child.indicator}' is not approved for simulation."})
                continue
            if child.operator not in ALLOWED_OPERATORS:
                errors.append({"code": "unsupported_operator", "message": f"Condition {index}: operator '{child.operator}' is not supported."})
                continue
            _validate_condition_assets(child, symbols, allow_new_assets, errors)
        return

    dynamic_definition = IndicatorRegistry.get(indicator)
    if dynamic_definition:
        if dynamic_definition.approval_status != "approved":
            errors.append({"code": "unapproved_indicator", "message": f"Dynamic indicator '{indicator}' is not approved for simulation."})
            return
        for required in dynamic_definition.required_params:
            if required in {"asset", "asset_a", "asset_b", "benchmark"}:
                _require_symbol(params.get(required) or dynamic_definition.default_params.get(required), symbols, f"condition.{required}", errors, allow_missing=allow_new_assets)
            if required == "window":
                try:
                    window_value = params.get("window", dynamic_definition.default_params.get("window"))
                    if int(window_value) <= 0 or int(window_value) > 1000:
                        errors.append({"code": "invalid_window", "message": "Indicator window must be between 1 and 1000."})
                except (TypeError, ValueError):
                    errors.append({"code": "invalid_window", "message": "Indicator window must be a number."})
        return

    if indicator in {"asset_was_reduced", "price", "price_above_moving_average", "price_below_moving_average", "return_since_start", "drawdown", "volatility"}:
        _require_symbol(params.get("asset"), symbols, "condition.asset", errors, allow_missing=allow_new_assets)
    elif indicator == "relative_strength":
        _require_symbol(params.get("asset_a"), symbols, "condition.asset_a", errors, allow_missing=allow_new_assets)
        _require_symbol(params.get("asset_b"), symbols, "condition.asset_b", errors, allow_missing=allow_new_assets)
    elif indicator == "market_rotation_score":
        _require_symbol(params.get("equity_proxy", "SPY"), symbols, "condition.equity_proxy", errors, allow_missing=allow_new_assets)
        _require_symbol_or_symbols(params.get("defensive_proxy", "GLD"), symbols, "condition.defensive_proxy", errors, allow_missing=allow_new_assets)

    window = params.get("window")
    if window is not None:
        try:
            if int(window) <= 0 or int(window) > 1000:
                errors.append({"code": "invalid_window", "message": "Indicator window must be between 1 and 1000."})
        except (TypeError, ValueError):
            errors.append({"code": "invalid_window", "message": "Indicator window must be a number."})


def _validate_action(action: RuleAction, index: int, symbols: set[str], allow_new_assets: bool, errors: list[dict[str, str]]):
    if action.type not in ALLOWED_ACTIONS:
        errors.append({
            "code": "unsupported_action",
            "message": f"Action {index}: action type '{action.type}' is not supported.",
        })
        return

    if action.type == "transfer_position_percent":
        _require_symbol(action.from_asset, symbols, f"actions[{index}].from_asset", errors, allow_missing=allow_new_assets)
        _require_symbol(action.to_asset, symbols, f"actions[{index}].to_asset", errors, allow_missing=allow_new_assets)
        _require_percent(action.percent, f"actions[{index}].percent", errors)
    elif action.type == "split_transfer_position_percent":
        _require_symbol(action.from_asset, symbols, f"actions[{index}].from_asset", errors, allow_missing=allow_new_assets)
        _require_percent(action.percent, f"actions[{index}].percent", errors)
        if not action.allocations:
            errors.append({"code": "missing_allocation", "message": f"actions[{index}].allocations is required."})
        total = 0.0
        for allocation_index, allocation in enumerate(action.allocations):
            _require_symbol(allocation.get("asset"), symbols, f"actions[{index}].allocations[{allocation_index}].asset", errors, allow_missing=allow_new_assets)
            _require_percent(allocation.get("percent"), f"actions[{index}].allocations[{allocation_index}].percent", errors)
            try:
                total += float(allocation.get("percent"))
            except (TypeError, ValueError):
                pass
        if action.allocations and total > 100.0 + 1e-6:
            errors.append({"code": "invalid_allocation", "message": f"actions[{index}].allocations must not exceed 100."})
    elif action.type == "sell_position_percent":
        _require_symbol(action.asset, symbols, f"actions[{index}].asset", errors, allow_missing=allow_new_assets)
        _require_percent(action.percent, f"actions[{index}].percent", errors)
    elif action.type == "buy_with_cash_percent":
        _require_symbol(action.asset, symbols, f"actions[{index}].asset", errors, allow_missing=allow_new_assets)
        _require_percent(action.cash_percent, f"actions[{index}].cash_percent", errors)


def _require_symbol(symbol, symbols: set[str], field: str, errors: list[dict[str, str]], allow_missing: bool = False):
    normalized = normalize_symbol(symbol)
    if not normalized:
        errors.append({"code": "missing_asset", "message": f"{field} is required."})
        return
    if not SYMBOL_PATTERN.match(normalized):
        errors.append({"code": "invalid_symbol", "message": f"{field} has invalid symbol '{symbol}'."})
        return
    if normalized not in symbols and not allow_missing:
        errors.append({
            "code": "missing_asset",
            "message": f"The rule references {normalized}, but it is not in the portfolio.",
        })


def _require_symbol_or_symbols(value, symbols: set[str], field: str, errors: list[dict[str, str]], allow_missing: bool = False):
    if isinstance(value, list):
        if not value:
            errors.append({"code": "missing_asset", "message": f"{field} needs at least one symbol."})
            return
        for index, symbol in enumerate(value):
            _require_symbol(symbol, symbols, f"{field}[{index}]", errors, allow_missing=allow_missing)
        return
    _require_symbol(value, symbols, field, errors, allow_missing=allow_missing)


def _require_percent(value, field: str, errors: list[dict[str, str]]):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        errors.append({"code": "invalid_percent", "message": f"{field} must be a number."})
        return
    if numeric <= 0 or numeric > 100:
        errors.append({"code": "invalid_percent", "message": f"{field} must be > 0 and <= 100."})


def evaluate_condition(condition: RuleCondition | dict[str, Any], historical_prices: pd.DataFrame, runtime_state: dict[str, Any] | None = None) -> bool:
    parsed = condition if isinstance(condition, RuleCondition) else RuleCondition(**condition)
    value = resolve_indicator(parsed, historical_prices, runtime_state=runtime_state)
    return _compare(value, parsed.operator, parsed.value)


def resolve_indicator(condition: RuleCondition | dict[str, Any], historical_prices: pd.DataFrame, runtime_state: dict[str, Any] | None = None) -> float:
    condition = condition if isinstance(condition, RuleCondition) else RuleCondition(**condition)
    params = condition.params or {}
    indicator = condition.indicator
    if indicator == "all":
        conditions = params.get("conditions") or []
        return 1.0 if all(evaluate_condition(child, historical_prices, runtime_state=runtime_state) for child in conditions) else 0.0
    if indicator == "any":
        conditions = params.get("conditions") or []
        return 1.0 if any(evaluate_condition(child, historical_prices, runtime_state=runtime_state) for child in conditions) else 0.0
    if indicator == "asset_was_reduced":
        reduced_assets = (runtime_state or {}).get("reduced_assets", {})
        return 1.0 if int(reduced_assets.get(normalize_symbol(params.get("asset")), 0)) > 0 else 0.0
    if indicator == "price":
        series = _price_series(historical_prices, params["asset"])
        return float(series.iloc[-1])
    if indicator == "price_above_moving_average":
        series = _price_series(historical_prices, params["asset"])
        return 1.0 if series.iloc[-1] > _moving_average(series, params.get("window", 200)) else 0.0
    if indicator == "price_below_moving_average":
        series = _price_series(historical_prices, params["asset"])
        return 1.0 if series.iloc[-1] < _moving_average(series, params.get("window", 200)) else 0.0
    if indicator == "relative_strength":
        return _relative_strength(
            _price_series(historical_prices, params["asset_a"]),
            _price_series(historical_prices, params["asset_b"]),
            int(params.get("window", 90)),
        )
    if indicator == "return_since_start":
        return _period_return(_price_series(historical_prices, params["asset"]), len(_price_series(historical_prices, params["asset"])) - 1) * 100
    if indicator == "drawdown":
        series = _window(_price_series(historical_prices, params["asset"]), int(params.get("window", 252)))
        peak = float(series.max())
        current = float(series.iloc[-1])
        return ((peak - current) / peak) * 100 if peak > 0 else 0.0
    if indicator == "volatility":
        series = _window(_price_series(historical_prices, params["asset"]), int(params.get("window", 30)) + 1)
        returns = series.pct_change().dropna()
        return float(returns.std() * math.sqrt(252) * 100) if len(returns) else 0.0
    if indicator == "market_rotation_score":
        equity = _proxy_series(historical_prices, params.get("equity_proxy", "SPY"))
        defensive = _proxy_series(historical_prices, params.get("defensive_proxy", "GLD"))
        rel = _relative_strength(equity, defensive, int(params.get("window", 90))) / 100
        return max(0.0, min(100.0, 50.0 + math.tanh(rel * 3.0) * 50.0))
    if IndicatorRegistry.has(indicator):
        return IndicatorRegistry.resolve(indicator, historical_prices, params)
    raise ValueError(f"Unsupported indicator: {indicator}")


def execute_custom_rules(
    portfolio,
    current_prices,
    historical_prices: pd.DataFrame,
    current_date,
    custom_rules: list[CustomRule | dict[str, Any]] | None,
    ledger=None,
    runtime_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not custom_rules:
        return []

    runtime_state = runtime_state if runtime_state is not None else {}
    runtime_state.setdefault("custom_rules", {})
    runtime_state.setdefault("custom_rule_groups", {})
    runtime_state.setdefault("custom_rule_daily_groups", {})
    runtime_state.setdefault("custom_rule_events", [])
    runtime_state.setdefault("reduced_assets", {})
    portfolio_symbols = [asset.symbol for asset in portfolio.assets]
    events: list[dict[str, Any]] = []

    for raw_rule in custom_rules:
        rule = parse_custom_rule(raw_rule)
        if not rule.enabled:
            continue

        validation = validate_custom_rule(rule, portfolio_symbols)
        if not validation["valid"]:
            first = validation["errors"][0]["message"] if validation["errors"] else "invalid rule"
            raise ValueError(f"Custom rule validation failed for {rule.id}: {first}")

        rule_state = runtime_state["custom_rules"].setdefault(rule.id, {"triggers": 0, "last_trigger_date": None})
        group_state = None
        if rule.execution.group_id:
            group_state = runtime_state["custom_rule_groups"].setdefault(rule.execution.group_id, {"triggers": 0, "last_trigger_date": None})
        daily_group_state = None
        if rule.execution.daily_group_id:
            daily_group_state = runtime_state["custom_rule_daily_groups"].setdefault(rule.execution.daily_group_id, {"daily_triggers": {}})
        if not _can_run(rule, current_date, rule_state, group_state, daily_group_state):
            continue

        if not evaluate_condition(rule.condition, historical_prices, runtime_state=runtime_state):
            continue

        action_events = [_execute_action(portfolio, current_prices, current_date, action, ledger) for action in rule.actions]
        _record_reduced_assets(runtime_state, action_events)
        rule_state["triggers"] += 1
        rule_state["last_trigger_date"] = current_date
        if group_state is not None:
            group_state["triggers"] += 1
            group_state["last_trigger_date"] = current_date
        if daily_group_state is not None:
            day_key = _day_key(current_date)
            daily_group_state["daily_triggers"][day_key] = daily_group_state["daily_triggers"].get(day_key, 0) + 1
        event = {
            "date": str(current_date.date()) if hasattr(current_date, "date") else str(current_date),
            "rule_id": rule.id,
            "rule_name": rule.name,
            "actions": action_events,
        }
        events.append(event)
        runtime_state["custom_rule_events"].append(event)

    return events


def build_example_tests(rule: CustomRule | dict[str, Any]) -> list[dict[str, str]]:
    parsed = parse_custom_rule(rule)
    return [
        {
            "name": "condition_false_no_trade",
            "given": "Indicator condition evaluates to false.",
            "expected": "No action is executed and trigger count stays unchanged.",
        },
        {
            "name": "condition_true_executes_actions",
            "given": f"Indicator '{parsed.condition.indicator}' satisfies '{parsed.condition.operator} {parsed.condition.value}'.",
            "expected": "Configured actions execute once and a rule event is recorded.",
        },
        {
            "name": "missing_asset_rejected",
            "given": "A referenced asset symbol is not part of the portfolio.",
            "expected": "Validation returns missing_asset and simulation does not run the rule.",
        },
        {
            "name": "max_triggers_respected",
            "given": "The rule has already reached max_triggers.",
            "expected": "The rule is skipped on later days.",
        },
    ]


def _can_run(
    rule: CustomRule,
    current_date,
    rule_state: dict[str, Any],
    group_state: dict[str, Any] | None = None,
    daily_group_state: dict[str, Any] | None = None,
) -> bool:
    execution = rule.execution
    if execution.max_triggers is not None and rule_state["triggers"] >= execution.max_triggers:
        return False
    if group_state is not None and execution.group_max_triggers is not None and group_state["triggers"] >= execution.group_max_triggers:
        return False
    if daily_group_state is not None and execution.daily_group_max_triggers is not None:
        if daily_group_state.setdefault("daily_triggers", {}).get(_day_key(current_date), 0) >= execution.daily_group_max_triggers:
            return False

    last = rule_state.get("last_trigger_date")
    group_last = group_state.get("last_trigger_date") if group_state is not None else None
    if last is None:
        if group_last is None:
            return True
    if group_last is not None and execution.group_cooldown_days is not None and (current_date - group_last).days < execution.group_cooldown_days:
        return False

    if last is not None and execution.cooldown_days is not None and (current_date - last).days < execution.cooldown_days:
        return False

    if execution.frequency == "weekly":
        if last is None:
            return True
        return current_date.isocalendar()[:2] != last.isocalendar()[:2]
    if execution.frequency == "monthly":
        if last is None:
            return True
        return (current_date.year, current_date.month) != (last.year, last.month)
    return True


def _day_key(current_date) -> str:
    return str(current_date.date()) if hasattr(current_date, "date") else str(current_date)


def _record_reduced_assets(runtime_state: dict[str, Any], action_events: list[dict[str, Any]]):
    reduced_assets = runtime_state.setdefault("reduced_assets", {})
    for event in action_events:
        from_asset = event.get("from_asset")
        if event.get("type") in {"split_transfer_position_percent", "transfer_position_percent"} and from_asset:
            symbol = normalize_symbol(from_asset)
            reduced_assets[symbol] = int(reduced_assets.get(symbol, 0)) + 1
        if event.get("type") == "sell_position_percent" and event.get("asset"):
            symbol = normalize_symbol(event.get("asset"))
            reduced_assets[symbol] = int(reduced_assets.get(symbol, 0)) + 1


def _execute_action(portfolio, current_prices, current_date, action: RuleAction, ledger=None) -> dict[str, Any]:
    if action.type == "transfer_position_percent":
        from_asset = _find_asset(portfolio, action.from_asset)
        to_asset = _find_asset(portfolio, action.to_asset)
        percent = float(action.percent) / 100
        from_price = _current_price(current_prices, from_asset.symbol)
        to_price = _current_price(current_prices, to_asset.symbol)
        value_to_sell = from_asset.stueckzahl * from_price * percent
        if ledger is not None:
            before_cash = float(portfolio.cash)
            ledger.sell_shares(portfolio, from_asset, value_to_sell / from_price, from_price, current_date, reason="custom_rule")
            budget = max(float(portfolio.cash) - before_cash, 0.0)
            portfolio.cash -= budget
            ledger.buy_with_budget(to_asset, budget, to_price, current_date, reason="custom_rule")
        else:
            from_asset.stueckzahl -= value_to_sell / from_price
            to_asset.stueckzahl += value_to_sell / to_price
        return {"type": action.type, "from_asset": from_asset.symbol, "to_asset": to_asset.symbol, "value": float(value_to_sell)}

    if action.type == "split_transfer_position_percent":
        from_asset = _find_asset(portfolio, action.from_asset)
        percent = float(action.percent) / 100
        from_price = _current_price(current_prices, from_asset.symbol)
        shares_to_sell = from_asset.stueckzahl * percent
        gross_value = shares_to_sell * from_price

        if ledger is not None:
            before_cash = float(portfolio.cash)
            ledger.sell_shares(portfolio, from_asset, shares_to_sell, from_price, current_date, reason="custom_rule")
            budget = max(float(portfolio.cash) - before_cash, 0.0)
            portfolio.cash -= budget
        else:
            from_asset.stueckzahl -= shares_to_sell
            budget = gross_value

        allocation_events = []
        spent = 0.0
        for index, allocation in enumerate(action.allocations):
            target_asset = _find_asset(portfolio, allocation.get("asset"))
            target_price = _current_price(current_prices, target_asset.symbol)
            weight = float(allocation.get("percent")) / 100
            allocation_budget = budget * weight
            spent += allocation_budget

            if ledger is not None:
                ledger.buy_with_budget(target_asset, allocation_budget, target_price, current_date, reason="custom_rule")
            else:
                target_asset.stueckzahl += allocation_budget / target_price
            allocation_events.append({"asset": target_asset.symbol, "percent": float(allocation.get("percent")), "value": float(allocation_budget)})

        retained_cash = max(budget - spent, 0.0)
        if retained_cash:
            portfolio.cash += retained_cash

        return {
            "type": action.type,
            "from_asset": from_asset.symbol,
            "percent": float(action.percent),
            "value": float(budget),
            "allocations": allocation_events,
            "retained_cash": float(retained_cash),
        }

    if action.type == "sell_position_percent":
        asset = _find_asset(portfolio, action.asset)
        price = _current_price(current_prices, asset.symbol)
        shares = asset.stueckzahl * (float(action.percent) / 100)
        if ledger is not None:
            result = ledger.sell_shares(portfolio, asset, shares, price, current_date, reason="custom_rule")
            value = float(result.get("net", 0.0))
        else:
            value = shares * price
            asset.stueckzahl -= shares
            portfolio.cash += value
        return {"type": action.type, "asset": asset.symbol, "value": value}

    if action.type == "buy_with_cash_percent":
        asset = _find_asset(portfolio, action.asset)
        price = _current_price(current_prices, asset.symbol)
        budget = float(portfolio.cash) * (float(action.cash_percent) / 100)
        if ledger is not None:
            portfolio.cash -= budget
            ledger.buy_with_budget(asset, budget, price, current_date, reason="custom_rule")
        else:
            portfolio.cash -= budget
            asset.stueckzahl += budget / price
        return {"type": action.type, "asset": asset.symbol, "value": float(budget)}

    raise ValueError(f"Unsupported action: {action.type}")


def _compare(left, operator: str, right) -> bool:
    left_value = float(left)
    right_value = float(right)
    if operator == ">":
        return left_value > right_value
    if operator == ">=":
        return left_value >= right_value
    if operator == "<":
        return left_value < right_value
    if operator == "<=":
        return left_value <= right_value
    if operator == "==":
        return abs(left_value - right_value) < 1e-12
    if operator == "!=":
        return abs(left_value - right_value) >= 1e-12
    raise ValueError(f"Unsupported operator: {operator}")


def _price_series(historical_prices: pd.DataFrame, symbol: str) -> pd.Series:
    normalized = normalize_symbol(symbol)
    if normalized not in historical_prices:
        raise ValueError(f"Missing historical prices for {normalized}")
    series = historical_prices[normalized].dropna().astype(float)
    if series.empty:
        raise ValueError(f"No historical prices for {normalized}")
    return series


def _proxy_series(historical_prices: pd.DataFrame, proxy) -> pd.Series:
    if isinstance(proxy, list):
        series_list = []
        for symbol in proxy:
            series = _price_series(historical_prices, symbol)
            first = float(series.iloc[0])
            series_list.append(series / first * 100 if first else series)
        return pd.concat(series_list, axis=1).mean(axis=1)
    return _price_series(historical_prices, proxy)


def _window(series: pd.Series, window: int) -> pd.Series:
    return series.tail(max(int(window), 1))


def _moving_average(series: pd.Series, window: int) -> float:
    return float(_window(series, int(window)).mean())


def _period_return(series: pd.Series, window: int) -> float:
    values = _window(series, int(window) + 1)
    if len(values) < 2 or float(values.iloc[0]) == 0:
        return 0.0
    return (float(values.iloc[-1]) / float(values.iloc[0])) - 1


def _relative_strength(series_a: pd.Series, series_b: pd.Series, window: int) -> float:
    return (_period_return(series_a, window) - _period_return(series_b, window)) * 100


def _find_asset(portfolio, symbol: str | None):
    normalized = normalize_symbol(symbol)
    for asset in portfolio.assets:
        if normalize_symbol(asset.symbol) == normalized:
            return asset
    raise ValueError(f"Asset {normalized} is not in portfolio")


def _current_price(current_prices, symbol: str) -> float:
    price = float(current_prices[normalize_symbol(symbol)])
    if price <= 0 or math.isnan(price) or math.isinf(price):
        raise ValueError(f"Invalid current price for {symbol}")
    return price
